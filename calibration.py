"""
calibration.py — how honest the model's chances have been, per sport (Nov 2: the "juice factor").

The graded reads show the blended chance runs a little optimistic (NFL reads priced 55-60% hit about half the time).
A ticket priced off inflated chances overstates itself every leg, so ticket math uses an HONEST chance:

    honest = 0.5 + s * (chance - 0.5)          s in [0.5, 1.0]; 1.0 = trust the chance as shown

fit() picks the s that best matches what actually happened (lowest log loss) on the graded reads of the last
TREND_DAYS; daily_review.py refits it every morning and stores it in the report. Nothing changes until an owner
approves an s (model_store.approve_calibration -- Postgame Review shows the before/after); factor() reads the
approved one. Scorer props (Anytime TD, goals) are left out: a 28% "Yes" isn't a lean pulled toward 50%.
"""
from __future__ import annotations

import math
import time
from typing import Dict, Iterable, List, Optional

SKIP_MARKETS = ("Anytime TD", "1st TD", "Last TD", "Goals")
MIN_N = 150
S_RANGE = (0.5, 1.0)
BUCKETS = ((0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 1.01))
CACHE_S = 300
_cache: Dict = {"at": 0.0, "map": {}}


def honest(p: Optional[float], s: float = 1.0) -> Optional[float]:
    if p is None:
        return None
    return min(max(0.5 + s * (float(p) - 0.5), 0.001), 0.999)


def _ll(rows, s):
    tot = 0.0
    for p, y in rows:
        q = honest(p, s)
        tot -= math.log(q) if y else math.log(1 - q)
    return tot / len(rows)


def usable(rows: Iterable[Dict]) -> List[tuple]:
    """(chance of the read's side, hit 0/1) for graded, non-scorer reads."""
    out = []
    for r in rows:
        if r.get("result") not in ("hit", "miss") or r.get("market") in SKIP_MARKETS:
            continue
        try:
            p = float(r.get("chance"))
        except (TypeError, ValueError):
            continue
        if 0.0 < p < 1.0:
            out.append((p, 1 if r["result"] == "hit" else 0))
    return out


def fit(rows: Iterable[Dict]) -> Dict:
    """{"s", "n", "log_loss": (before, after), "brier": (before, after), "buckets": [...] , "enough": bool}."""
    data = usable(rows)
    n = len(data)
    if not n:
        return {"s": 1.0, "n": 0, "enough": False, "buckets": []}
    lo, hi = S_RANGE
    grid = [round(lo + i * 0.01, 2) for i in range(int(round((hi - lo) / 0.01)) + 1)]
    s = min(grid, key=lambda g: _ll(data, g)) if n >= MIN_N else 1.0
    brier = lambda g: sum((honest(p, g) - y) ** 2 for p, y in data) / n
    lean = [(p, y) if p >= 0.5 else (1 - p, 1 - y) for p, y in data]     # each read on its favored side
    buckets = []
    for b_lo, b_hi in BUCKETS:
        g = [(p, y) for p, y in lean if b_lo <= p < b_hi]
        if g:
            buckets.append({"range": f"{b_lo:.0%}–{min(b_hi, 1):.0%}", "n": len(g),
                            "shown": sum(p for p, _ in g) / len(g),
                            "honest": sum(honest(p, s) for p, _ in g) / len(g),
                            "hit": sum(y for _, y in g) / len(g)})
    return {"s": s, "n": n, "enough": n >= MIN_N, "log_loss": (round(_ll(data, 1.0), 4), round(_ll(data, s), 4)),
            "brier": (round(brier(1.0), 4), round(brier(s), 4)), "buckets": buckets}


def clear_cache() -> None:
    _cache["at"] = 0.0
    _cache["map"] = {}


def factor(sport: Optional[str]) -> float:
    """The owner-approved s for this sport; 1.0 (no change) until one is approved or when the store can't be read."""
    if time.time() - _cache["at"] > CACHE_S:
        try:
            import model_store as MS
            _cache["map"] = {c["sport"]: float(c["s"]) for c in MS.list_calibration()}
        except Exception:                                       # noqa: BLE001
            _cache["map"] = {}
        _cache["at"] = time.time()
    lo, hi = S_RANGE
    return max(lo, min(hi, _cache["map"].get(sport or "", 1.0)))


def chance(sport: Optional[str], p: Optional[float], market: Optional[str] = None) -> Optional[float]:
    """The honest chance of one leg for ticket math (scorer props pass through unchanged)."""
    if p is None or market in SKIP_MARKETS:
        return p
    return honest(p, factor(sport))



# --------------------------------------------------------------------------- by side (Nov 5)
# The Nov 5 audit (research/calibration_audit.py, 2,479 NBA reads Oct 30 - Nov 4): the model's UNDER chances were
# honest (said 55%, hit 56%) but its OVER chances weren't (said 53%, hit 45%; Points 54% -> 41%, combos 53-57% ->
# 34-41%). One factor for both sides can't fix that, so each side gets its own. Held out (research/
# side_calibration_test.py, fit on earlier days, scored on later ones): the per-side version beat both "as shown" and
# one shared factor on log loss in every split, and the Overs it stopped calling singles had hit 46-50%.
# Applied to the model's P(over) before the lean, edge and Use tag are worked out (props_engine.read_line), so the
# chance shown, the value and the tags all move together. Owner-approved per sport on Postgame Review, like `s`.
SIDE_S_RANGE = (0.3, 1.0)


def _side_key(sport: Optional[str], side: str) -> str:
    return f"{sport or ''}:{side}"


def side_factors(sport: Optional[str]):
    """(s_over, s_under) approved for this sport; (1.0, 1.0) = no change."""
    factor(None)                                                # refreshes the shared cache when it's stale
    lo, hi = SIDE_S_RANGE
    m = _cache["map"]
    return (max(lo, min(hi, m.get(_side_key(sport, "Over"), 1.0))), max(lo, min(hi, m.get(_side_key(sport, "Under"), 1.0))))


def apply_side(p_over: Optional[float], factors) -> Optional[float]:
    """P(over) with the side factor of whichever side it favors pulled toward 50%."""
    if p_over is None or not factors:
        return p_over
    s_over, s_under = factors
    s = s_over if p_over > 0.5 else s_under
    return honest(p_over, s)


def fit_by_side(rows: Iterable[Dict]) -> Dict:
    """{"Over": fit, "Under": fit} -- the honest-chance factor for each side the model took (range 0.30-1.00)."""
    rows = list(rows)
    out = {}
    for side in ("Over", "Under"):
        data = usable([r for r in rows if (r.get("side") or "Over") == side])
        n = len(data)
        if n < MIN_N:
            out[side] = {"s": 1.0, "n": n, "enough": False}
            continue
        lo, hi = SIDE_S_RANGE
        grid = [round(lo + i * 0.01, 2) for i in range(int(round((hi - lo) / 0.01)) + 1)]
        best = min(grid, key=lambda g: _ll(data, g))
        out[side] = {"s": best, "n": n, "enough": True, "said": sum(p for p, _ in data) / n,
                     "hit": sum(y for _, y in data) / n, "log_loss": (round(_ll(data, 1.0), 4), round(_ll(data, best), 4))}
    return out


# --------------------------------------------------------------------------- learned nightly (Nov 8)
# The owner asked for a system that learns every day as picks reconcile, not one that waits for a study and a button.
# Each morning review (daily_review.review_sport) runs this on the last 30 days of graded reads: for each side, fit the
# factor that would have made the chances honest, then check it the way research/side_calibration_test.py does -- on
# every split, fit on the earlier days and score on the later ones. A change is applied only when it improves the held-out
# log loss in at least two thirds of the splits AND moves the factor by 0.03 or more; it can tighten (chances
# overconfident) or loosen back toward 1.00 (an earlier correction overshot). Every change is written with its evidence
# (calibration table, details.auto = true), shown in that morning's notes, and can be turned off on Postgame Review.
AUTO_MIN_ROWS = 300            # reads on that side in the window
AUTO_MIN_DATES = 3
AUTO_MIN_SPLITS = 2
AUTO_MIN_MOVE = 0.03
AUTO_SPLIT_PASS = 2 / 3
_REL_GRID = [round(0.5 + i * 0.01, 2) for i in range(101)]     # relative to the active factor: 0.50 .. 1.50


# Nov 15 (owner: NFL and college football seasons are 17 and ~13 games -- "waiting on more games may never happen"):
# 1) Every graded chance is put on today's footing instead of being thrown away when a factor changes: the chance was
#    shown with the factor active when its read was saved, so it's unscaled by that factor and rescaled by the active
#    one (factor_history / rescale). The whole window counts, not just the days since the last change.
# 2) Weekly sports hold out GAMES, not days: one NFL Sunday is a dozen games, so the fit is checked on games it never
#    saw (5 folds by game) and needs 2 slate days, not 3 + day-by-day splits that a once-a-week sport can't supply.
WEEKLY_SPORTS = ("NFL", "NCAAF")
WEEKLY_FOLDS = 5
WEEKLY_MIN_DATES = 2


def factor_history(key: str) -> List[tuple]:
    """[(approved date-time, s)] for one calibration key (e.g. "NFL:Over"), oldest first, from every row ever approved."""
    try:
        import model_store as MS
        rows = [(str(c.get("approved_ts") or ""), float(c["s"])) for c in MS.list_calibration(active_only=False)
                if c.get("sport") == key]
    except Exception:                                           # noqa: BLE001
        return []
    return sorted(rows)


def factor_at(hist: List[tuple], when: str, default: float = 1.0) -> float:
    s = default
    for ts, v in hist:
        if ts and ts <= when:
            s = v
    return s


def rescale(p: float, s_then: float, s_now: float) -> float:
    """A chance shown under factor s_then, as it would be shown under s_now."""
    if not s_then:
        return p
    raw = 0.5 + (p - 0.5) / s_then
    return min(max(0.5 + s_now * (raw - 0.5), 0.001), 0.999)


def _game_folds(rows: List[Dict], k: int = WEEKLY_FOLDS) -> List[set]:
    import hashlib
    games = sorted({str(r.get("game") or r["date"]) + "|" + r["date"] for r in rows},
                   key=lambda g: hashlib.md5(g.encode()).hexdigest())
    return [set(games[i::k]) for i in range(k)] if len(games) >= k else []


def _ll_rel(rows, s):
    tot = 0.0
    for r in rows:
        q = min(max(honest(r["p"], s), 1e-3), 1 - 1e-3)
        tot -= math.log(q) if r["y"] else math.log(1 - q)
    return tot / len(rows)


def held_out_side(rows: List[Dict], weekly: bool = False) -> Dict:
    """rows: [{"date", "p" (chance as graded, active factor already in it), "y"[, "game"]}] for ONE side.
    -> {"rel": fit on everything (relative to active), "splits": n, "passed": n, "gain": mean held-out improvement}.
    weekly=True (NFL, college football): held out by game -- 5 folds -- instead of by later day."""
    ds = sorted({r["date"] for r in rows})
    out = {"rel": 1.0, "splits": 0, "passed": 0, "gain": 0.0, "n": len(rows), "dates": len(ds)}
    if len(rows) < 2 or not ds:
        return out
    out["rel"] = min(_REL_GRID, key=lambda g: _ll_rel(rows, g))
    gains = []
    if weekly:
        for fold in _game_folds(rows):
            key = lambda r: str(r.get("game") or r["date"]) + "|" + r["date"]
            tr = [r for r in rows if key(r) not in fold]
            te = [r for r in rows if key(r) in fold]
            if len(tr) < 100 or len(te) < 30:
                continue
            s_ = min(_REL_GRID, key=lambda g: _ll_rel(tr, g))
            gains.append(_ll_rel(te, 1.0) - _ll_rel(te, s_))
        out["splits"] = len(gains)
        out["passed"] = sum(1 for g in gains if g > 0)
        out["gain"] = sum(gains) / len(gains) if gains else 0.0
        return out
    for cut in ds[1:]:
        tr = [r for r in rows if r["date"] < cut]
        te = [r for r in rows if r["date"] >= cut]
        if len(tr) < 100 or len(te) < 100:
            continue
        s = min(_REL_GRID, key=lambda g: _ll_rel(tr, g))
        g = _ll_rel(te, 1.0) - _ll_rel(te, s)
        gains.append(g)
    out["splits"] = len(gains)
    out["passed"] = sum(1 for g in gains if g > 0)
    out["gain"] = sum(gains) / len(gains) if gains else 0.0
    return out


def auto_side(sport: str, graded_by_date: Dict[str, List[Dict]], morning: str, write: bool = True) -> List[Dict]:
    """Learn each side's factor from the window; apply what passes. Returns the decisions (applied or not, and why)."""
    rows = {"Over": [], "Under": []}
    for d, rs in graded_by_date.items():
        for r in rs:
            if r.get("result") not in ("hit", "miss") or r.get("market") in SKIP_MARKETS:
                continue
            try:
                p = float(r.get("chance"))
            except (TypeError, ValueError):
                continue
            if 0 < p < 1 and r.get("side") in rows:
                rows[r["side"]].append({"date": d, "p": p, "y": 1 if r["result"] == "hit" else 0,
                                        "game": r.get("game"), "ts": str(r.get("ts") or f"{d}T23:59")})
    active = dict(zip(("Over", "Under"), side_factors(sport)))
    weekly = sport in WEEKLY_SPORTS
    hist = {side: factor_history(f"{sport}:{side}") for side in rows}
    if any(hist.values()):                                      # Nov 15: every read on today's footing (rescale)
        for side in rows:
            for r in rows[side]:
                r["p"] = rescale(r["p"], factor_at(hist[side], r["ts"]), active[side])
    # A graded chance carries the factor that was active when its snapshot was taken, so a side is judged only on days
    # since its current factor went live -- otherwise a fresh correction would be applied again on top of itself.
    since = {}
    try:
        import model_store as MS
        for c in MS.list_calibration():
            if c["sport"] in (f"{sport}:Over", f"{sport}:Under"):
                since[c["sport"].split(":")[1]] = str(c.get("approved_ts") or "")[:10]
    except Exception:                                           # noqa: BLE001
        pass
    if not any(hist.values()):                                  # no history on file: the old rule (days since)
        for side in rows:
            if since.get(side):
                rows[side] = [r for r in rows[side] if r["date"] >= since[side]]
    out = []
    lo, hi = SIDE_S_RANGE
    min_dates = WEEKLY_MIN_DATES if weekly else AUTO_MIN_DATES
    for side, rs in rows.items():
        h = held_out_side(rs, weekly=weekly)
        new = round(max(lo, min(hi, active[side] * h["rel"])), 2)
        dec = {"sport": sport, "side": side, "active": active[side], "new": new, **h, "applied": False,
               "since": since.get(side), "weekly": weekly}
        if h["n"] < AUTO_MIN_ROWS or h["dates"] < min_dates:
            dec["why"] = f"not enough yet ({h['n']} reads over {h['dates']} days)"
        elif h["splits"] < AUTO_MIN_SPLITS:
            dec["why"] = "not enough games to hold any out" if weekly else "not enough days to hold any out"
        elif abs(new - active[side]) < AUTO_MIN_MOVE:
            dec["why"] = f"already honest (best {new:.2f} vs active {active[side]:.2f})"
        elif h["passed"] < AUTO_SPLIT_PASS * h["splits"] or h["gain"] <= 0:
            dec["why"] = (f"didn't hold up on held-out {'games' if weekly else 'days'} ({h['passed']} of {h['splits']})")
        else:
            dec["why"] = f"held up on {h['passed']} of {h['splits']} held-out {'game groups' if weekly else 'splits'}"
            if write:
                import model_store as MS
                dec["applied"] = MS.approve_calibration(f"{sport}:{side}", new, {
                    "auto": True, "morning": morning, "n": h["n"], "rel_fit": h["rel"], "splits": h["splits"],
                    "passed": h["passed"], "held_out_gain": round(h["gain"], 5), "was": active[side]})
        out.append(dec)
    return out


def auto_notes(decisions: List[Dict]) -> List[str]:
    notes = []
    for d in decisions:
        if d.get("applied"):
            if "trust" in str(d["side"]):
                way = ("toward the books' price (the model ran overconfident where it disagreed with them)"
                       if d["new"] < d["active"] else "back toward the model's own number")
                what = "TD-scorer trust in the model" if d.get("kind") == "td" else "prop trust in the model"
                notes.append(f"🤖 Learned overnight: {d['sport']} {what} {d['active']:.2f} → {d['new']:.2f}, pulled {way}; "
                             f"{d['why']}. Undo on Postgame Review.")
                continue
            way = "toward 50% (they ran overconfident)" if d["new"] < d["active"] else "back out (the last correction overshot)"
            what = "ticket-math confidence" if d["side"] == "overall" else f"{d['side']} chances"
            notes.append(f"🤖 Learned overnight: {d['sport']} {what} {d['active']:.2f} → {d['new']:.2f}, "
                         f"pulled {way}; {d['why']} ({d['n']} reads). Undo on Postgame Review.")
    return notes


# --------------------------------------------------------------------------- the overall factor learns too (Nov 10)
# The owner: "the calibrations should be done automatically as the model learns." The per-side factors already did
# (auto_side). The overall factor `s` -- the one ticket and parlay math uses on top of the chance shown -- was still a
# suggestion waiting for approval every morning. Same rule as the sides: fit on the window, applied only when it holds
# up on held-out days. Graded chances don't carry `s` (it's applied after, in chance()), so the fit IS the new `s`; the
# window starts when the side factors last changed, because that's when the shown chances last moved.
def auto_global(sport: str, graded_by_date: Dict[str, List[Dict]], morning: str, write: bool = True) -> Dict:
    since = ""
    try:
        import model_store as MS
        for c in MS.list_calibration():
            if c["sport"] in (f"{sport}:Over", f"{sport}:Under"):
                since = max(since, str(c.get("approved_ts") or "")[:10])
    except Exception:                                           # noqa: BLE001
        pass
    weekly = sport in WEEKLY_SPORTS
    hist = {sd: factor_history(f"{sport}:{sd}") for sd in ("Over", "Under")}
    act = dict(zip(("Over", "Under"), side_factors(sport)))
    rescaled = any(hist.values())
    rows = []
    for d, rs in graded_by_date.items():
        if since and d < since and not rescaled:
            continue
        for r in rs:
            u = usable([r])
            if not u:
                continue
            p, y = u[0]
            if rescaled and r.get("side") in hist:              # Nov 15: on today's side factors, like auto_side
                p = rescale(p, factor_at(hist[r["side"]], str(r.get("ts") or f"{d}T23:59")), act[r["side"]])
            rows.append({"date": d, "p": p, "y": y, "game": r.get("game")})
    h = held_out_side(rows, weekly=weekly)
    active = factor(sport)
    lo, hi = S_RANGE
    new = round(max(lo, min(hi, h["rel"])), 2)
    dec = {"sport": sport, "side": "overall", "active": active, "new": new, **h, "applied": False, "since": since or None}
    if h["n"] < AUTO_MIN_ROWS or h["dates"] < (WEEKLY_MIN_DATES if weekly else AUTO_MIN_DATES):
        dec["why"] = f"not enough yet ({h['n']} reads over {h['dates']} days)"
    elif h["splits"] < AUTO_MIN_SPLITS:
        dec["why"] = "not enough games to hold any out" if weekly else "not enough days to hold any out"
    elif abs(new - active) < AUTO_MIN_MOVE:
        dec["why"] = f"already honest (best {new:.2f} vs active {active:.2f})"
    elif h["passed"] < AUTO_SPLIT_PASS * h["splits"] or h["gain"] <= 0:
        dec["why"] = f"didn't hold up on held-out {'games' if weekly else 'days'} ({h['passed']} of {h['splits']})"
    else:
        dec["why"] = f"held up on {h['passed']} of {h['splits']} held-out splits"
        if write:
            import model_store as MS
            dec["applied"] = MS.approve_calibration(sport, new, {
                "auto": True, "morning": morning, "n": h["n"], "splits": h["splits"], "passed": h["passed"],
                "held_out_gain": round(h["gain"], 5), "was": active, "since": since})
    return dec


# --------------------------------------------------------------------------- trust the market (Nov 17)
# The owner: "find a way to force this" -- on the bets he logged the model said 68% and they hit 55%. The side factors
# pull every chance toward 50%; the error is somewhere else: it's largest exactly where the model DISAGREES with the
# books, which is where every bet comes from. Measured (research/trust_test.py, graded reads, last 30 days / 63 for
# NFL): q = market + t x (chance - market) fits best at t ~0.54 for NBA and NFL props (held out on later days: 7/7 and
# 2/2), t = 0 for NFL Anytime TD (the books' price was simply better), and the bet-tagged NBA reads said 58.9% and
# hit 53.3%. So after the side factor, each chance moves toward the books' no-vig chance by a learned "trust" in the
# model (1.0 = the model as is, 0.1 = nearly the market). Refit every morning; a move TOWARD the market applies as soon
# as the window says so (forced: it can only remove edges, never invent them); a move back toward the model has to
# hold up on held-out days like every other factor.
TRUST_RANGE = (0.1, 1.0)
TRUST_REL_GRID = [round(i * 0.02, 2) for i in range(0, 76)]     # 0.00 .. 1.50, relative to the active trust
TRUST_MIN_ROWS = {"props": 300, "td": 200}
TD_MARKETS = ("Anytime TD", "1st TD", "Last TD")


def _trust_key(sport: Optional[str], market: Optional[str] = None) -> str:
    return f"{sport or ''}:trust" + (":TD" if market in TD_MARKETS else "")


def trust(sport: Optional[str], market: Optional[str] = None) -> float:
    """How far a chance keeps its distance from the books' (1.0 = all of it; 0.1 = almost none)."""
    factor(None)                                                # refreshes the shared cache when it's stale
    lo, hi = TRUST_RANGE
    return max(lo, min(hi, _cache["map"].get(_trust_key(sport, market), 1.0)))


def apply_trust(p: Optional[float], p_mkt: Optional[float], t: Optional[float]) -> Optional[float]:
    """P(over) moved toward the market's P(over): market + t x (p - market)."""
    if p is None or p_mkt is None or t is None or t >= 1.0:
        return p
    return min(max(float(p_mkt) + t * (float(p) - float(p_mkt)), 0.001), 0.999)


def _q(r, rel):
    return min(max(r["m"] + rel * (r["p"] - r["m"]), 1e-3), 1 - 1e-3)


def _ll_trust(rows, rel):
    return -sum(math.log(_q(r, rel)) if r["y"] else math.log(1 - _q(r, rel)) for r in rows) / len(rows)


def trust_rows(sport: str, graded_by_date: Dict[str, List[Dict]], kind: str) -> List[Dict]:
    """Graded reads with the books' chance for the read's side, rescaled to today's trust."""
    active = trust(sport, "Anytime TD" if kind == "td" else None)
    hist = factor_history(_trust_key(sport, "Anytime TD" if kind == "td" else None))
    out = []
    for d, rs in graded_by_date.items():
        for r in rs:
            if r.get("result") not in ("hit", "miss") or (r.get("market") in TD_MARKETS) != (kind == "td"):
                continue
            try:
                p, pm = float(r.get("chance")), float(r.get("p_market"))
            except (TypeError, ValueError):
                continue
            if not (0 < p < 1 and 0 < pm < 1):
                continue
            m = pm if r.get("side") in ("Over", "Yes") else 1 - pm
            then = factor_at(hist, str(r.get("ts") or f"{d}T23:59"), 1.0)
            if then <= 0:
                continue
            out.append({"date": d, "game": r.get("game"), "m": m, "p": m + (active / then) * (p - m),
                        "y": 1 if r["result"] == "hit" else 0})
    return out


def auto_trust(sport: str, graded_by_date: Dict[str, List[Dict]], morning: str, write: bool = True) -> List[Dict]:
    """Refit the model-vs-market trust for props and (football) TD scorers; apply per the rule above."""
    out = []
    weekly = sport in WEEKLY_SPORTS
    lo, hi = TRUST_RANGE
    for kind in ("props", "td"):
        rows = trust_rows(sport, graded_by_date, kind)
        if kind == "td" and not rows:
            continue
        market = "Anytime TD" if kind == "td" else None
        active = trust(sport, market)
        ds = sorted({r["date"] for r in rows})
        dec = {"sport": sport, "side": "TD market trust" if kind == "td" else "market trust", "kind": kind,
               "active": active, "new": active, "n": len(rows), "dates": len(ds), "applied": False, "weekly": weekly}
        if len(rows) < TRUST_MIN_ROWS[kind] or len(ds) < (WEEKLY_MIN_DATES if weekly else AUTO_MIN_DATES):
            dec["why"] = f"not enough yet ({len(rows)} reads over {len(ds)} days)"
            out.append(dec)
            continue
        rel = min(TRUST_REL_GRID, key=lambda g: _ll_trust(rows, g))
        new = round(max(lo, min(hi, active * rel)), 2)
        gains = []
        for cut in ds[1:]:
            tr = [r for r in rows if r["date"] < cut]
            te = [r for r in rows if r["date"] >= cut]
            if len(tr) < 100 or len(te) < 50:
                continue
            g = min(TRUST_REL_GRID, key=lambda x: _ll_trust(tr, x))
            gains.append(_ll_trust(te, 1.0) - _ll_trust(te, g))
        passed = sum(1 for g in gains if g > 0)
        dec.update(new=new, rel_fit=rel, splits=len(gains), passed=passed,
                   gain=sum(gains) / len(gains) if gains else 0.0,
                   log_loss=(round(_ll_trust(rows, 1.0), 4), round(_ll_trust(rows, rel), 4)))
        if abs(new - active) < AUTO_MIN_MOVE:
            dec["why"] = f"already right (best {new:.2f} vs active {active:.2f})"
        elif new < active:
            dec["why"] = (f"the books were closer on {len(rows)} graded reads (log loss {dec['log_loss'][0]} -> "
                          f"{dec['log_loss'][1]}; held out {passed} of {len(gains)})")
        elif gains and passed >= AUTO_SPLIT_PASS * len(gains) and dec["gain"] > 0:
            dec["why"] = f"the model earned more trust: held up on {passed} of {len(gains)} held-out splits"
        else:
            dec["why"] = f"more trust didn't hold up on held-out days ({passed} of {len(gains)})"
            out.append(dec)
            continue
        if not dec["why"].startswith("already") and write:
            import model_store as MS
            dec["applied"] = MS.approve_calibration(_trust_key(sport, market), new, {
                "auto": True, "morning": morning, "n": len(rows), "rel_fit": rel, "splits": len(gains),
                "passed": passed, "held_out_gain": round(dec["gain"], 5), "was": active, "kind": kind})
        out.append(dec)
    return out
