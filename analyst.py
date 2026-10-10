"""
analyst.py — the Analyst Desk's brain: find angles, rank them honestly, write the commentary.

WHAT THIS IS FOR (the request): a page that behaves like a commentator, handicapper and data
analyst at once — it reads the day's board and the live market, points at where to focus, and
keeps score on itself. The product claim is PREDICTABILITY and REPEATABILITY, not "beats the
market": every call it publishes is tied to a named ANGLE, locked at the moment it was first
published (analyst_ledger.py), and graded afterwards, so the page can show which angles have actually
held up. The side street is found the same way the main road is: by measuring, not by assertion.

THE PIECES
  * ANGLES — small, independent detectors over a play (the shape every sport's build_best_bets
    already produces). Each one answers one plain question ("is the model well above the book?",
    "is one book off-market?", "is his recent role bigger than his line assumes?") and returns a
    strength 0-1 plus the evidence in words. They never invent data: a detector with no input
    (no odds, no game log) simply doesn't fire.
  * CONFLUENCE — a "hidden gem" is a play that two or more independent angles agree on and that
    is NOT already chalk (top of the day's conviction list). That is the operational definition of
    "overlooked": agreement the headline ranking doesn't surface.
  * CAUTIONS — honest counter-evidence (line moving against the model, a cold team behind an
    Over, a thin sample). A gem with two cautions is not promoted.
  * LEARNED WEIGHTS — once calls are graded, each angle's ranking weight moves with how its calls
    actually performed against the probabilities the model attached to them, shrunk hard toward
    1.0 until there is real volume. Weights change ORDER only; they never edit a probability.
  * THE SCOREBOARD — per angle: how many calls, hit rate, the model's average stated chance, the
    gap between them, and a Wilson interval, with a status that refuses to claim anything below a
    sample floor. That table IS the proof.
  * COMMENTARY — written from the structured findings only (deterministic, always available), with
    an optional language-model rewrite that is given the same facts and told not to add any.

Pure Python: no Streamlit, no network except the one optional, injectable LLM call. Fully unit
tested (test_analyst.py).
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import odds_api as O
import sports

# ---------------------------------------------------------------------------
# Angle registry
# ---------------------------------------------------------------------------
ANGLES: Dict[str, Tuple[str, str]] = {
    "market_gap":     ("Model vs market",   "The model's chance is well above what the book's price implies."),
    "soft_book":      ("Soft price",        "One book is paying noticeably more than the rest of the market for the same side."),
    "form_run":       ("Form run",          "He has cleared this exact line in nearly every recent game."),
    "role_surge":     ("Role surge",        "His last few games run well away from his earlier baseline in the direction of the play, and the line still looks like the old baseline."),
    "team_surge":     ("Team momentum",     "His whole team is scoring above (or below) its own norm, in the direction of the play."),
    "regression_due": ("Regression due",    "His underlying contact quality says the results should catch up."),
    "line_move":      ("Line moving our way", "The market has moved toward this side since it opened."),
}

# thresholds — named so the tests (and the owner) can see exactly what "fires" means
GAP_MIN = 0.05            # model prob minus book prob, in probability points
SOFT_MIN = 0.03           # median-book implied prob minus best-price implied prob
SOFT_MIN_BOOKS = 3
FORM_MIN_GAMES = 5
FORM_WINDOW = 8
FORM_MIN_RATE = 0.80
SURGE_RATIO = 1.25
SURGE_MIN_GAMES = 6
MOVE_MIN = 0.03           # implied-probability move toward the side
GEM_MIN_ANGLES = 2
GEM_MIN_PROB = 0.55
GEM_MAX_CAUTIONS = 1
CHALK_PERCENTILE = 0.90   # top 10% of the day's conviction is "main road"

# newest-first game logs (nfl_engine.player_recent_games, nhl_engine.get_player_recent_games)
NEWEST_FIRST_SPORTS = {"NFL", "NHL"}


def _norm(s: Optional[str]) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum())


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def call_key(sport: str, date_str: str, player: str, market: str, side: str) -> str:
    return f"{sport}|{date_str}|{player}|{market}|{side}"


# ---------------------------------------------------------------------------
# Odds index (for the soft-price angle)
# ---------------------------------------------------------------------------
def index_offers(offers: Optional[List[Dict]]) -> Dict[Tuple[str, str], List[Dict]]:
    """{(normalized player, odds-api market key): [offer, ...]} — an offer is one line with the
    per-book over/under prices (odds_api.parse_event_offers' own shape)."""
    out: Dict[Tuple[str, str], List[Dict]] = {}
    for o in offers or []:
        out.setdefault((_norm(o.get("player")), o.get("market")), []).append(o)
    return out


# ---------------------------------------------------------------------------
# Detectors — each returns None or {"strength": 0..1, "evidence": str}
# ---------------------------------------------------------------------------
def detect_market_gap(p: Dict, ctx: Dict) -> Optional[Dict]:
    if p.get("ConvictionSource") != "book":
        return None                    # the "reference" was the model's own typical rate, not a market
    mp, conv = p.get("ModelProb"), p.get("Conviction")
    if not mp or not conv or conv <= 0:
        return None
    ref = mp / conv                    # Conviction = model prob / reference prob
    gap = mp - ref
    if gap < GAP_MIN:
        return None
    return {"strength": _clip(gap / 0.15),
            "evidence": f"model {mp:.0%} vs market {ref:.0%} (+{gap * 100:.0f} pts)"}


def detect_soft_book(p: Dict, ctx: Dict) -> Optional[Dict]:
    idx, omap = ctx.get("offer_index"), ctx.get("odds_map") or {}
    okey = omap.get(p.get("Market"))
    if not idx or not okey or p.get("Line") is None:
        return None
    side = "over" if p.get("Side") == "Over" else "under"
    best = None
    for o in idx.get((_norm(p.get("Player")), okey), []):
        pt = o.get("point")
        if pt is None or abs(float(pt) - float(p["Line"])) > 1e-6:
            continue
        prices = {b: pr for b, pr in (o.get(side) or {}).items() if pr is not None}
        if len(prices) < SOFT_MIN_BOOKS:
            continue
        probs = sorted((O.implied_prob(pr), b, pr) for b, pr in prices.items())
        mid = probs[len(probs) // 2][0] if len(probs) % 2 else (probs[len(probs) // 2 - 1][0] + probs[len(probs) // 2][0]) / 2
        top = probs[0]                  # lowest implied prob = richest payout
        gap = mid - top[0]
        if best is None or gap > best[0]:
            best = (gap, top[1], top[2], mid, len(probs))
    if not best or best[0] < SOFT_MIN:
        return None
    gap, book, price, mid, n = best
    return {"strength": _clip(gap / 0.08),
            "evidence": f"{O.book_label(book)} pays {price:+.0f} while the median of {n} books implies {mid:.0%} "
                        f"({gap * 100:.1f} pts richer)"}


def _values(p: Dict, sport_key: str) -> List[float]:
    """The play's recent stat values, OLDEST first (or [] when the play carries no usable log)."""
    log, key = p.get("_game_log"), p.get("_stat_key")
    if not log or not key:
        return []
    out: List[float] = []
    for g in log:
        if not isinstance(g, dict):
            continue
        v = g.get(key)
        if v is None and key == "scrimmage_tds":
            v = (g.get("rushing_tds") or 0) + (g.get("receiving_tds") or 0)
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out[::-1] if sport_key in NEWEST_FIRST_SPORTS else out


def _clears(v: float, line: float, side: str) -> bool:
    return v > line if side == "Over" else v < line


def detect_form_run(p: Dict, ctx: Dict) -> Optional[Dict]:
    vals = _values(p, ctx.get("sport_key", ""))[-FORM_WINDOW:]
    line, side = p.get("Line"), p.get("Side")
    if len(vals) < FORM_MIN_GAMES or line is None or side not in ("Over", "Under"):
        return None
    hits = sum(1 for v in vals if _clears(v, line, side))
    rate = hits / len(vals)
    if rate < FORM_MIN_RATE or (p.get("ModelProb") or 0) < 0.55:
        return None
    return {"strength": _clip((rate - 0.5) / 0.5),
            "evidence": f"{'cleared' if side == 'Over' else 'stayed under'} {line:g} in {hits} of his last {len(vals)}"}


def detect_role_surge(p: Dict, ctx: Dict) -> Optional[Dict]:
    vals = _values(p, ctx.get("sport_key", ""))
    line, side = p.get("Line"), p.get("Side")
    if len(vals) < SURGE_MIN_GAMES or line is None or side not in ("Over", "Under"):
        return None
    recent, base = vals[-3:], vals[:-3]
    r3, b = sum(recent) / len(recent), sum(base) / len(base)
    if side == "Over":
        if b <= 0 or r3 < b * SURGE_RATIO or r3 <= line:
            return None
        ratio = r3 / b
        # the "line lag" half of the idea: the line should still sit nearer the old baseline
        if line > (r3 + b) / 2:
            return None
    else:
        if b <= 0 or r3 > b / SURGE_RATIO or r3 >= line:
            return None
        ratio = b / r3 if r3 > 0 else 3.0
        if line < (r3 + b) / 2:
            return None
    return {"strength": _clip((ratio - 1) / 0.6),
            "evidence": f"last 3 games average {r3:.1f} against {b:.1f} before that — the {line:g} line still reads like the old baseline"}


def detect_team_surge(p: Dict, ctx: Dict) -> Optional[Dict]:
    tag, side = str(p.get("TeamTrend") or ""), p.get("Side")
    ratio = p.get("TeamTrendRatio")
    hot, cold = "Hot" in tag, "Cold" in tag
    if not ((hot and side == "Over") or (cold and side == "Under")):
        return None
    s = _clip(abs((ratio or 1.0) - 1.0) / 0.5) if ratio else 0.4
    word = "above" if hot else "below"
    r = f" (x{ratio:.2f})" if ratio else ""
    return {"strength": max(0.25, s), "evidence": f"{p.get('Team') or 'his team'} is scoring {word} its own norm{r}"}


def detect_regression_due(p: Dict, ctx: Dict) -> Optional[Dict]:
    due = p.get("Due")
    if p.get("Market") != "Batter HR" or p.get("Side") != "Over" or due is None or due <= 0.01:
        return None
    return {"strength": _clip(due / 0.03),
            "evidence": f"barrel quality implies about {due * 100:.1f} more HR per 100 PA than his results show"}


def detect_line_move(p: Dict, ctx: Dict) -> Optional[Dict]:
    """Uses line_history rows (price/line over time) via ctx['history_fn']; fires only when the
    market has moved TOWARD the play's side by MOVE_MIN implied-probability points."""
    move = line_move_toward(p, ctx)
    if move is None or move < MOVE_MIN:
        return None
    return {"strength": _clip(move / 0.08), "evidence": f"the market has moved {move * 100:.1f} pts toward this side since it opened"}


def line_move_toward(p: Dict, ctx: Dict) -> Optional[float]:
    """Implied-probability change toward the play's side (+ = toward, - = away), or None."""
    fn = ctx.get("history_fn")
    ids = ctx.get("history_ids")
    if not fn or (ids is not None and id(p) not in ids):
        return None
    try:
        rows = fn(ctx.get("sport_key"), p.get("Player"), p.get("Market"), p.get("Side")) or []
    except Exception:           # noqa: BLE001 — history is context, never a reason to break the page
        return None
    by_book: Dict[str, List[Dict]] = {}
    for r in rows:
        if r.get("price") is not None and r.get("line") == p.get("Line"):
            by_book.setdefault(r.get("book") or "?", []).append(r)
    best: Optional[float] = None
    for series in by_book.values():
        if len(series) < 2:
            continue
        d = O.implied_prob(series[-1]["price"]) - O.implied_prob(series[0]["price"])
        if best is None or abs(d) > abs(best):
            best = d
    return best


DETECTORS: Dict[str, Callable[[Dict, Dict], Optional[Dict]]] = {
    "market_gap": detect_market_gap,
    "soft_book": detect_soft_book,
    "form_run": detect_form_run,
    "role_surge": detect_role_surge,
    "team_surge": detect_team_surge,
    "regression_due": detect_regression_due,
    "line_move": detect_line_move,
}


# ---------------------------------------------------------------------------
# Cautions (counter-evidence)
# ---------------------------------------------------------------------------
def cautions_for(p: Dict, ctx: Dict) -> List[str]:
    out: List[str] = []
    tag, side = str(p.get("TeamTrend") or ""), p.get("Side")
    if "Cold" in tag and side == "Over":
        out.append(f"{p.get('Team') or 'his team'} is scoring below its own norm")
    if "Hot" in tag and side == "Under":
        out.append(f"{p.get('Team') or 'his team'} is scoring above its own norm")
    mv = line_move_toward(p, ctx)
    if mv is not None and mv <= -MOVE_MIN:
        out.append(f"the market has moved {abs(mv) * 100:.1f} pts away from this side")
    vals = _values(p, ctx.get("sport_key", ""))
    if p.get("_game_log") and 0 < len(vals) < FORM_MIN_GAMES:
        out.append(f"only {len(vals)} recent game(s) behind the numbers")
    if p.get("LineSource") not in (None, "book") and ctx.get("expect_book_lines"):
        out.append("priced off the model's default line, not a posted book line")
    return out


# ---------------------------------------------------------------------------
# Game times (slot + kickoff), shared by the scan, the commentary and the page filters
# ---------------------------------------------------------------------------
SLOT_TITLES = {"Afternoon": "Afternoon games (before 5 PM ET)", "Evening": "Evening games (5–8 PM ET)",
               "Late": "Late games (8 PM ET and after)", "TBD": "Start time not posted yet"}


def time_info(game_iso: Optional[str], with_day: bool = False) -> Dict:
    """{"start", "slot", "kickoff"} for one game's start (UTC ISO or a bare date). A game with no clock
    time is slot "TBD" and sorts last; start is the ISO string used only to order games."""
    dt = sports.game_dt(game_iso)
    return {"start": game_iso if dt is not None else None, "slot": sports.slot_of(dt),
            "kickoff": sports.kickoff_text(dt, with_day) if dt is not None else "time TBD"}


def game_times(meta: Iterable[Dict], with_day: bool = False) -> Dict[str, Dict]:
    """{game label: time_info} for every game on the slate (from the engine's per-game meta)."""
    return {m["label"]: time_info(m.get("game_date"), with_day) for m in meta or [] if m.get("label")}


def chrono_key(slot: str, start: Optional[str], tiebreak=0):
    """Sort key: slot order, then actual start, then the tiebreak (a score, descending)."""
    return (sports.SLOT_ORDER.get(slot, 9), start or "~", tiebreak)


# ---------------------------------------------------------------------------
# Scan -> calls
# ---------------------------------------------------------------------------
def _percentile_cut(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(math.ceil(q * len(s))) - 1)]


def scan(plays: Iterable[Dict], sport_key: str, date_str: str, *, offers: Optional[List[Dict]] = None,
         odds_map: Optional[Dict[str, str]] = None, history_fn: Optional[Callable] = None,
         weights: Optional[Dict[str, float]] = None, expect_book_lines: bool = False,
         history_limit: int = 60, times: Optional[Dict[str, Dict]] = None,
         with_day: bool = False) -> List[Dict]:
    """Run every detector over every play. Returns one CALL per play that has at least one angle,
    ranked best-first. A call:
        key, sport, date, player, player_id, team, game, game_date, market, side, line, model_prob,
        conviction, price, price_book, why, angles [{angle,label,strength,evidence}], cautions,
        score, chalk (bool), gem (bool), slot, kickoff, start (when the game starts)
    """
    plays = list(plays)
    weights = weights or {}
    # line history costs one lookup per play (a database round trip on the cloud backend), so only
    # the `history_limit` highest-conviction plays are checked for movement.
    top = sorted(plays, key=lambda q: q.get("Conviction") or 0, reverse=True)[:max(0, history_limit)]
    ctx = {"sport_key": sport_key, "offer_index": index_offers(offers), "odds_map": odds_map or {},
           "history_fn": history_fn, "expect_book_lines": expect_book_lines,
           "history_ids": {id(q) for q in top}}
    by_market: Dict[str, List[float]] = {}
    for p in plays:
        if p.get("Conviction") is not None:
            by_market.setdefault(p.get("Market"), []).append(p["Conviction"])
    cuts = {m: _percentile_cut(v, CHALK_PERCENTILE) for m, v in by_market.items()}

    calls: List[Dict] = []
    for p in plays:
        if p.get("Side") not in ("Over", "Under") or p.get("ModelProb") is None:
            continue
        hits = []
        for name, fn in DETECTORS.items():
            r = fn(p, ctx)
            if r:
                hits.append({"angle": name, "label": ANGLES[name][0],
                             "strength": round(r["strength"], 3), "evidence": r["evidence"]})
        if not hits:
            continue
        cuts_m = cuts.get(p.get("Market"))
        chalk = bool(cuts_m is not None and p.get("Conviction") is not None
                     and len(by_market.get(p.get("Market"), [])) >= 10 and p["Conviction"] >= cuts_m)
        cautions = cautions_for(p, ctx)
        score = sum(weights.get(h["angle"], 1.0) * h["strength"] for h in hits)
        gem = (len(hits) >= GEM_MIN_ANGLES and not chalk and p["ModelProb"] >= GEM_MIN_PROB
               and len(cautions) <= GEM_MAX_CAUTIONS)
        calls.append({
            "key": call_key(sport_key, date_str, p.get("Player"), p.get("Market"), p.get("Side")),
            "sport": sport_key, "date": date_str, "player": p.get("Player"), "player_id": p.get("PlayerId"),
            "team": p.get("Team"), "game": p.get("Game"), "game_date": p.get("GameDate"),
            "market": p.get("Market"), "side": p.get("Side"), "line": p.get("Line"),
            "model_prob": p.get("ModelProb"), "conviction": p.get("Conviction"),
            "price": p.get("RealPrice"), "price_book": p.get("RealPriceBook"), "why": p.get("Why"),
            "angles": hits, "cautions": cautions, "score": round(score - 0.25 * len(cautions), 3),
            "chalk": chalk, "gem": gem, **_call_time(p, times, with_day),
        })
    calls.sort(key=lambda c: (c["gem"], c["score"], c["model_prob"]), reverse=True)
    return calls


def _call_time(p: Dict, times: Optional[Dict[str, Dict]], with_day: bool) -> Dict:
    info = (times or {}).get(p.get("Game")) or time_info(p.get("GameDate"), with_day)
    return {"slot": info["slot"], "kickoff": info["kickoff"], "start": info["start"]}


def angle_names(call: Dict) -> List[str]:
    return [a["angle"] for a in call.get("angles", [])]


# ---------------------------------------------------------------------------
# Scoreboard + learned weights (from graded ledger rows)
# ---------------------------------------------------------------------------
STATUS_MIN_N = 30
STATUS_BAND = 0.05
WEIGHT_PRIOR_N = 30
WEIGHT_RANGE = (0.5, 1.5)


def wilson(hits: int, n: int, z: float = 1.96) -> Tuple[Optional[float], Optional[float]]:
    if n <= 0:
        return None, None
    p = hits / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def _summ(rows: List[Dict]) -> Dict:
    graded = [r for r in rows if r.get("hit") in (0, 1, True, False) and r.get("hit") is not None]
    n = len(graded)
    hits = sum(1 for r in graded if r["hit"])
    probs = [r["model_prob"] for r in graded if r.get("model_prob") is not None]
    mean_p = sum(probs) / len(probs) if probs else None
    brier = (sum((r["model_prob"] - (1.0 if r["hit"] else 0.0)) ** 2 for r in graded
                 if r.get("model_prob") is not None) / len(probs)) if probs else None
    lo, hi = wilson(hits, n)
    rate = hits / n if n else None
    gap = (rate - mean_p) if (rate is not None and mean_p is not None) else None
    if n < STATUS_MIN_N or gap is None:
        status = f"Collecting data ({n}/{STATUS_MIN_N})"
    elif lo is not None and lo > mean_p:
        status = "Beating its stated odds"
    elif hi is not None and hi < mean_p:
        status = "Falling short of its stated odds"
    elif abs(gap) <= STATUS_BAND:
        status = "Calibrated"
    else:
        status = "Within the noise"
    return {"n": n, "hits": hits, "hit_rate": rate, "mean_prob": mean_p, "gap": gap,
            "brier": brier, "ci_low": lo, "ci_high": hi, "status": status}


def scoreboard(rows: List[Dict]) -> List[Dict]:
    """One line per angle (plus ALL and Hidden gems) from SETTLED ledger rows. Each row needs
    angles (list of names), model_prob, hit, gem."""
    out = [{"angle": "ALL", "label": "All published calls", **_summ(rows)},
           {"angle": "gem", "label": "Hidden gems (2+ angles, not chalk)", **_summ([r for r in rows if r.get("gem")])}]
    for name, (label, _desc) in ANGLES.items():
        sub = [r for r in rows if name in (r.get("angles") or [])]
        out.append({"angle": name, "label": label, **_summ(sub)})
    return out


def learned_weights(rows: List[Dict]) -> Dict[str, float]:
    """Ranking weight per angle: 1.0 + 4 x (hit rate - stated chance) shrunk by n/(n+30), clipped
    to 0.5-1.5. No data -> 1.0. Order only; probabilities are never touched."""
    w: Dict[str, float] = {}
    for name in ANGLES:
        s = _summ([r for r in rows if name in (r.get("angles") or [])])
        if s["n"] == 0 or s["gap"] is None:
            w[name] = 1.0
            continue
        shrink = s["n"] / (s["n"] + WEIGHT_PRIOR_N)
        w[name] = round(_clip(1.0 + 4.0 * s["gap"] * shrink, *WEIGHT_RANGE), 3)
    return w


def reliability(rows: List[Dict], bins: Tuple[float, ...] = (0.0, 0.5, 0.6, 0.7, 0.8, 1.01)) -> List[Dict]:
    """Stated chance vs actual hit rate, by bucket — the calibration picture."""
    graded = [r for r in rows if r.get("hit") is not None and r.get("model_prob") is not None]
    out = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        g = [r for r in graded if lo <= r["model_prob"] < hi]
        if g:
            out.append({"bucket": f"{lo:.0%}–{min(hi, 1.0):.0%}", "n": len(g),
                        "stated": sum(r["model_prob"] for r in g) / len(g),
                        "actual": sum(1 for r in g if r["hit"]) / len(g)})
    return out


# ---------------------------------------------------------------------------
# Game notes (context that isn't a pick)
# ---------------------------------------------------------------------------
def game_notes(meta: Iterable[Dict]) -> Dict[str, List[str]]:
    """{game label: [plain-language context lines]} from the slate meta — rest edges today."""
    notes: Dict[str, List[str]] = {}
    for m in meta or []:
        lab = m.get("label")
        if not lab:
            continue
        hr, ar = m.get("home_rest"), m.get("away_rest")
        try:
            hr, ar = (None if hr is None else float(hr)), (None if ar is None else float(ar))
        except (TypeError, ValueError):
            hr = ar = None
        if hr is not None and ar is not None and abs(hr - ar) >= 3:
            fresher, tired = (m.get("home_name"), m.get("away_name")) if hr > ar else (m.get("away_name"), m.get("home_name"))
            notes.setdefault(lab, []).append(
                f"{fresher} has {abs(hr - ar):.0f} more days of rest than {tired}")
    return notes


# ---------------------------------------------------------------------------
# Commentary (deterministic; always available)
# ---------------------------------------------------------------------------
def _count(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _pick(options: List[str], seed: str) -> str:
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    return options[h % len(options)]


def describe_call(c: Dict) -> str:
    line = f"{c['player']} {c['side']} {c['line']:g} {c['market']}" if c.get("line") is not None else f"{c['player']} {c['side']} {c['market']}"
    return f"{line} ({c['model_prob']:.0%})"


def focus_areas(calls: List[Dict], top: int = 5) -> List[Dict]:
    """Cluster calls by (game, market): where the angles pile up. Ranked by total score."""
    groups: Dict[Tuple[str, str], List[Dict]] = {}
    for c in calls:
        groups.setdefault((c.get("game") or "?", c.get("market") or "?"), []).append(c)
    out = []
    for (game, market), cs in groups.items():
        names = sorted({a for c in cs for a in angle_names(c)})
        out.append({"game": game, "market": market, "n": len(cs), "angles": names,
                    "score": round(sum(c["score"] for c in cs), 3), "calls": cs})
    out.sort(key=lambda g: (g["score"], g["n"]), reverse=True)
    return out[:top]


def write_commentary(calls: List[Dict], *, sport_label: str, date_str: str, n_games: int,
                     notes: Optional[Dict[str, List[str]]] = None,
                     board: Optional[List[Dict]] = None,
                     times: Optional[Dict[str, Dict]] = None) -> Dict:
    """The day, in words. Returns {"headline", "overview", "focus": [..], "games": [{game, text, calls}],
    "facts": <the JSON-able facts the LLM layer is given>}. Wording only ever restates numbers that
    are in `calls`; with no calls it says so plainly.

    `times` ({game label: time_info}) puts the game-by-game read in start-time order — every game in
    it is listed, with or without a call — each entry carrying its slot and kickoff text, so the page
    can group them under Afternoon / Evening / Late headers. Without it, games with calls are ordered
    by how much angle support they have."""
    notes = notes or {}
    times = times or {}
    gems = [c for c in calls if c["gem"]]
    angle_counts: Dict[str, int] = {}
    for c in calls:
        for a in angle_names(c):
            angle_counts[a] = angle_counts.get(a, 0) + 1
    top_angles = sorted(angle_counts, key=lambda a: -angle_counts[a])[:3]

    if not calls:
        headline = f"{sport_label}: a quiet read for {date_str}"
        overview = (f"I looked at {_count(n_games, 'game')} and no play had a single angle clear its bar today. "
                    f"That is information too: nothing here is worth forcing.")
    else:
        headline = _pick([f"{sport_label}: where the angles pile up on {date_str}",
                          f"{sport_label} desk — {date_str}",
                          f"What the numbers are saying in {sport_label} ({date_str})"], date_str + sport_label)
        parts = [f"{_count(n_games, 'game')} on the slate; {_count(len(calls), 'play')} "
                 f"{'has' if len(calls) == 1 else 'have'} at least one angle behind "
                 f"{'it' if len(calls) == 1 else 'them'}"
                 + (f", and {len(gems)} of those {'is a hidden-gem candidate' if len(gems) == 1 else 'are hidden-gem candidates'} "
                    f"(two or more independent angles agreeing, off the chalk list)." if gems else ".")]
        if top_angles:
            parts.append("The angles carrying the day: " + ", ".join(
                f"{ANGLES[a][0].lower()} ({angle_counts[a]})" for a in top_angles) + ".")
        overview = " ".join(parts)

    focus = []
    for f in focus_areas(calls):
        lead = f["calls"][0]
        why = "; ".join(a["evidence"] for a in lead["angles"][:2])
        when = f" ({lead['kickoff']})" if lead.get("kickoff") and lead["kickoff"] != "time TBD" else ""
        text = (f"{f['market']} in {f['game']}{when}: {describe_call(lead)} — {why}."
                if f["n"] == 1 else
                f"{f['market']} in {f['game']}{when}: {f['n']} plays with angles, led by {describe_call(lead)} — {why}.")
        focus.append({"game": f["game"], "market": f["market"], "text": text, "n": f["n"],
                      "keys": [c["key"] for c in f["calls"]]})

    games: List[Dict] = []
    by_game: Dict[str, List[Dict]] = {}
    for c in calls:
        by_game.setdefault(c.get("game") or "?", []).append(c)
    def _info(g):
        if g in times:
            return times[g]
        cs0 = by_game.get(g) or []
        return ({"slot": cs0[0].get("slot", "TBD"), "kickoff": cs0[0].get("kickoff", "time TBD"), "start": cs0[0].get("start")}
                if cs0 else {"slot": "TBD", "kickoff": "time TBD", "start": None})

    def _order(g):
        i = _info(g)
        return chrono_key(i["slot"], i["start"], -sum(c["score"] for c in by_game.get(g, [])))

    for game in sorted(set(by_game) | set(notes) | set(times), key=_order):
        cs = by_game.get(game, [])
        info = _info(game)
        bits: List[str] = []
        if cs:
            top = cs[0]
            bits.append(f"The best-supported play is {describe_call(top)}: "
                        + "; ".join(a["evidence"] for a in top["angles"]) + ".")
            if top["cautions"]:
                bits.append("Against it: " + "; ".join(top["cautions"]) + ".")
            extra = [c for c in cs[1:3]]
            if extra:
                bits.append("Also worth a look: " + "; ".join(describe_call(c) for c in extra) + ".")
        else:
            bits.append("No play clears an angle here.")
        for n in notes.get(game, []):
            bits.append(n[0].upper() + n[1:] + ".")
        games.append({"game": game, "text": " ".join(bits), "keys": [c["key"] for c in cs],
                      "slot": info["slot"], "kickoff": info["kickoff"]})

    facts = {
        "sport": sport_label, "date": date_str, "games_on_slate": n_games,
        "calls": [{"key": c["key"], "game": c["game"], "kickoff": c.get("kickoff"), "play": describe_call(c), "team": c.get("team"),
                   "gem": c["gem"], "chalk": c["chalk"], "angles": [a["evidence"] for a in c["angles"]],
                   "cautions": c["cautions"], "book_price": c.get("price")} for c in calls[:25]],
        "game_notes": notes,
    }
    if board:
        facts["track_record"] = [{"angle": r["label"], "settled_calls": r["n"],
                                  "hit_rate": None if r["hit_rate"] is None else round(r["hit_rate"], 3),
                                  "avg_stated_chance": None if r["mean_prob"] is None else round(r["mean_prob"], 3),
                                  "status": r["status"]} for r in board if r["n"]][:8]
    return {"headline": headline, "overview": overview, "focus": focus, "games": games, "facts": facts}


# ---------------------------------------------------------------------------
# Optional language-model rewrite (same facts, told not to add any)
# ---------------------------------------------------------------------------
LLM_URL = "https://api.anthropic.com/v1/messages"
LLM_DEFAULT_MODEL = "claude-sonnet-5-5"
LLM_SYSTEM = (
    "You are the on-air analyst for H2 Sports, a sports-analytics community. Write a daily desk "
    "segment: a short headline, a paragraph that frames the day, then the focus areas and a "
    "game-by-game read, in the voice of a sharp, warm broadcast analyst. HARD RULES: use ONLY the "
    "facts in the JSON the user sends — never add a stat, injury, quote, weather detail, odds figure "
    "or storyline that is not in it; keep every number exactly as given; never promise or guarantee "
    "an outcome, never tell anyone to bet any amount, and say plainly where the evidence is thin or "
    "a caution is listed; if track_record is present you may mention how an angle has performed, "
    "using those numbers only. Plain markdown, no tables, under 450 words."
)


def facts_hash(facts: Dict) -> str:
    return hashlib.sha1(json.dumps(facts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def llm_commentary(facts: Dict, api_key: str, model: Optional[str] = None,
                   post: Optional[Callable] = None, timeout: int = 60) -> str:
    """One Messages-API call. Raises RuntimeError with a plain reason on ANY failure so the page can
    say why (never a silent fallback). `post` is injectable for tests."""
    if not api_key:
        raise RuntimeError("no Anthropic API key configured (set ANTHROPIC_API_KEY in the app secrets)")
    if post is None:
        import requests
        post = requests.post
    body = {"model": model or LLM_DEFAULT_MODEL, "max_tokens": 1200, "system": LLM_SYSTEM,
            "messages": [{"role": "user", "content": json.dumps(facts, default=str)}]}
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    try:
        resp = post(LLM_URL, headers=headers, json=body, timeout=timeout)
    except Exception as exc:                                        # noqa: BLE001
        raise RuntimeError(f"could not reach the Anthropic API ({type(exc).__name__}: {str(exc)[:120]})") from exc
    status = getattr(resp, "status_code", 0)
    if status != 200:
        detail = ""
        try:
            detail = (resp.json().get("error") or {}).get("message", "")
        except Exception:                                           # noqa: BLE001
            pass
        raise RuntimeError(f"the Anthropic API answered {status}" + (f": {detail[:160]}" if detail else ""))
    try:
        text = "".join(b.get("text", "") for b in resp.json().get("content", []) if b.get("type") == "text").strip()
    except Exception as exc:                                        # noqa: BLE001
        raise RuntimeError("the Anthropic API reply could not be read") from exc
    if not text:
        raise RuntimeError("the Anthropic API returned no text")
    return text
