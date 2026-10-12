"""
td_evidence.py — an independent read on "who scores, and who scores the LONGEST touchdown", for the Media Room's
King of the End Zone ranking and its Check-a-player box.

WHY THIS EXISTS: the original ranking used one source — the player's last five games — twice: once for his chance to
score (the share of those games with a TD, pulled toward 50%) and again for his big-play ability (yards per touch over
the same games, from as few as 3 touches). A returning player has a thin log, a role player's hot week looked like a
talent, and the sportsbook's own price and the injury report never entered the ranking. This module builds the
ranking from separate evidence instead, the way the Analyst Desk does:

  * the BOOK'S anytime-TD price (the market's own chance to score),
  * his SEASON-long TD rate and role, pulled toward his position's typical rate (not toward 50%),
  * the GAME ENVIRONMENT — the team's implied points from the spread and total,
  * BIG-PLAY ability from the whole season (yards per touch and average depth of target), shrunk toward the position's
    typical value until there are enough touches to trust it, and
  * the INJURY REPORT — a player listed Out or Doubtful is not picked.

Everything is plain dicts in, plain dicts out (unit tested). The loaders at the bottom are injected, fail-soft: a
missing source returns an empty result and a plain-language note, and the ranking simply rests on what is left. The
weights below are hypotheses, named so the owner can see them — not fitted values.
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional, Tuple

import analyst as A
import odds_api as O

# what a typical player at the position does, used until his own sample is big enough to trust
POS_TD_RATE = {"RB": 0.30, "WR": 0.22, "TE": 0.18, "QB": 0.10, "FB": 0.08}      # share of games with a rushing/receiving TD
POS_YPT = {"RB": 5.0, "WR": 11.0, "TE": 9.5, "QB": 5.0, "FB": 4.0}               # rushing+receiving yards per touch
POS_ADOT = 9.0                                                                  # average depth of target, pass-catchers
PRIOR_GAMES = 6          # a player's TD rate counts as this many games of "typical" before his own games take over
PRIOR_TOUCHES = 20       # same idea for yards per touch
PRIOR_TARGETS = 15       # …and for depth of target
LEAGUE_TEAM_POINTS = 22.5
SCRIPT_EXPONENT = 0.8    # how strongly a team's implied points scale its players' scoring chance
SCRIPT_MIN, SCRIPT_MAX = 0.8, 1.25
BOOK_MARGIN = 1.10       # an anytime-TD price carries roughly this much hold; the implied chance is divided by it
MARKET_WEIGHT = 0.6      # with a book price: this share market, the rest his season role
QB_EXPLOSIVE = 0.2       # a QB's rushing TDs are mostly sneaks and goal-line runs — almost never the longest of the night
OUT_STATUSES = {"out", "doubtful"}
NOTE_STATUSES = {"questionable"}


def _f(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if x == x else 0.0


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _scrimmage_tds(g: Dict) -> float:
    v = g.get("scrimmage_tds")
    if v is not None and v == v:
        return _f(v)
    return _f(g.get("rushing_tds")) + _f(g.get("receiving_tds"))


# ---------------------------------------------------------------------------
# Pure pieces
# ---------------------------------------------------------------------------
def season_summary(position: Optional[str], season_games: Optional[List[Dict]], recent_games: Optional[List[Dict]]) -> Dict:
    """His role and big-play numbers. Reads the season log when there is one (`src` 'season'), else the recent log
    the board already carries (`src` 'recent'). Rates are pulled toward the position's typical value."""
    pos = (position or "").upper()
    log = list(season_games or [])
    src = "season"
    if not log:
        log, src = list(recent_games or []), "recent"
    n = len(log)
    td_games = sum(1 for g in log if _scrimmage_tds(g) > 0)
    base = POS_TD_RATE.get(pos, 0.15)
    td_rate = (td_games + PRIOR_GAMES * base) / (n + PRIOR_GAMES)
    yds = sum(_f(g.get("rushing_yards")) + _f(g.get("receiving_yards")) for g in log)
    touches = sum(_f(g.get("carries")) + _f(g.get("receptions")) for g in log)
    base_ypt = POS_YPT.get(pos, 8.0)
    ypt = (yds + PRIOR_TOUCHES * base_ypt) / (touches + PRIOR_TOUCHES)
    targets = sum(_f(g.get("targets")) for g in log)
    air = sum(_f(g.get("receiving_air_yards")) for g in log)
    has_air = any(g.get("receiving_air_yards") is not None for g in log)
    adot = (air + PRIOR_TARGETS * POS_ADOT) / (targets + PRIOR_TARGETS) if has_air else None
    return {"games": n, "td_games": td_games, "td_rate": td_rate, "touches": touches, "ypt": ypt,
            "ypt_raw": (yds / touches) if touches else None, "targets_pg": (targets / n) if n else None,
            "carries_pg": (sum(_f(g.get("carries")) for g in log) / n) if n else None, "adot": adot, "src": src}


def team_points(entry: Optional[Dict], side: Optional[str]) -> Optional[float]:
    """The team's implied points from the game's spread and total: half the total, moved by half the spread (a 3-point
    favorite in a 45 total is 24 points). None when the game has no posted lines or the side is unknown."""
    if not entry or side not in ("home", "away"):
        return None
    total, spread = entry.get("total"), entry.get(f"{side}_spread")
    if total is None or spread is None:
        return None
    return float(total) / 2.0 - float(spread) / 2.0


def market_chance(price: Optional[float]) -> Optional[float]:
    """The book's own chance to score from an American price, less the assumed hold."""
    if price is None:
        return None
    return max(0.01, O.implied_prob(float(price)) / BOOK_MARGIN)


def scoring_chance(summary: Dict, price: Optional[float], points: Optional[float]) -> Dict:
    """{chance, role, market, script} — role is his season rate scaled by the team's implied points; with a book price the
    result is MARKET_WEIGHT market and the rest role."""
    script = 1.0
    if points is not None:
        script = _clip((points / LEAGUE_TEAM_POINTS) ** SCRIPT_EXPONENT, SCRIPT_MIN, SCRIPT_MAX)
    role = _clip(summary["td_rate"] * script, 0.02, 0.85)
    mkt = market_chance(price)
    chance = role if mkt is None else MARKET_WEIGHT * mkt + (1 - MARKET_WEIGHT) * role
    return {"chance": _clip(chance, 0.02, 0.9), "role": role, "market": mkt, "script": script}


def explosive_index(position: Optional[str], summary: Dict) -> float:
    """Big-play multiplier for the longest-TD ranking: 8 yards per touch is neutral. Pass-catchers also count how far
    downfield they are targeted. QBs are fixed low."""
    pos = (position or "").upper()
    if pos == "QB":
        return QB_EXPLOSIVE
    idx = _clip(summary["ypt"] / 8.0, 0.5, 1.8)
    if pos in ("WR", "TE") and summary.get("adot") is not None:
        idx = 0.6 * idx + 0.4 * _clip(summary["adot"] / POS_ADOT, 0.6, 1.6)
    return idx


def evaluate(play: Dict, season_games: Optional[List[Dict]], status: Optional[str], entry: Optional[Dict]) -> Dict:
    """Everything the ranking and the Check-a-player box need about one player."""
    pos = play.get("Position")
    s = season_summary(pos, season_games, play.get("_game_log"))
    side = A.team_side(play, entry) if entry else None
    pts = team_points(entry, side)
    price = play.get("RealPrice") if play.get("PriceSource") == "book" else None
    c = scoring_chance(s, price, pts)
    st = str(status or "").strip()
    return {"chance": c["chance"], "role": c["role"], "market": c["market"], "script": c["script"],
            "price": price, "price_book": play.get("RealPriceBook") if price is not None else None,
            "points": pts, "explosive": explosive_index(pos, s), "summary": s, "status": st or None,
            "out": st.lower() in OUT_STATUSES, "score": c["chance"] * explosive_index(pos, s)}


def enrich_pool(pool: Iterable[Dict], season_logs: Optional[Dict], injuries: Optional[Dict[str, str]],
                game_env: Optional[Dict[str, Dict]]) -> List[Dict]:
    """Each pool play gets `_td_ev` (see evaluate). `season_logs` is {player id: games, newest first}; `injuries` is
    {normalized player name: report status}; `game_env` is analyst_context.load_game_env's dict."""
    out = []
    for p in pool:
        q = dict(p)
        q["_td_ev"] = evaluate(q, (season_logs or {}).get(q.get("PlayerId")),
                               (injuries or {}).get(A._norm(q.get("Player"))), (game_env or {}).get(q.get("Game")))
        out.append(q)
    return out


def popular_ids(plays: List[Dict], n: int = 3) -> set:
    """The n players the crowd most likely backs: the shortest anytime-TD prices at the book, else the highest chance.
    Popularity is not measured; price is its best available proxy, because bettors pile onto short prices."""
    ev = lambda p: p["_td_ev"]
    pool = [p for p in plays if not ev(p)["out"]]
    keyed = sorted(pool, key=lambda p: (ev(p)["market"] if ev(p)["market"] is not None else ev(p)["chance"]), reverse=True)
    return {id(p) for p in keyed[:n]}


def evidence_text(ev: Dict) -> str:
    """One readable clause per piece of evidence, for the pick line."""
    s, bits = ev["summary"], []
    bits.append(f"TDs in {s['td_games']} of {s['games']} game(s)" + (" this season" if s["src"] == "season" else " (recent games only)"))
    if s["touches"] >= 1:
        bits.append(f"{s['ypt']:.1f} yds/touch (season, {s['touches']:.0f} touches)")
    if s.get("targets_pg") is not None and s["targets_pg"] >= 1:
        bits.append(f"{s['targets_pg']:.1f} targets/game")
    if ev.get("points") is not None:
        bits.append(f"team implied ~{ev['points']:.0f} pts")
    return ", ".join(bits)


# ---------------------------------------------------------------------------
# Loaders (network / engine; injected, fail-soft)
# ---------------------------------------------------------------------------
def load_context(sport_key: str, date_str: str, engine, rows: List[Dict], meta: List[Dict], api_key: Optional[str],
                 odds_sport_key: str, env_loader: Optional[Callable] = None) -> Tuple[Dict, Dict, Dict, List[str]]:
    """(season_logs, injuries, game_env, notes). Each source fails on its own; `notes` says what is missing."""
    notes: List[str] = []
    logs: Dict = {}
    inj: Dict[str, str] = {}
    env: Dict = {}
    try:
        pids = sorted({r.get("_pid") for r in rows if r.get("_pid")})
        logs = engine.get_season_logs(date_str, pids)
        if not logs:
            notes.append("season-long stats aren't available, so the ranking uses each player's last few games only")
    except Exception as exc:                                    # noqa: BLE001 — context, never a reason to break the page
        notes.append(f"season-long stats couldn't be loaded ({str(exc)[:70]}), so the ranking uses each player's last few games only")
    try:
        teams = sorted({r.get("Team") for r in rows if r.get("Team")})
        for t in teams:
            for row in engine.get_team_injuries_for_date(t, date_str) or []:
                if row.get("player") and row.get("status"):
                    inj[A._norm(row["player"])] = str(row["status"])
        if not inj:
            notes.append("no injury report is posted yet, so nobody was screened out")
    except Exception as exc:                                    # noqa: BLE001
        notes.append(f"the injury report couldn't be loaded ({str(exc)[:70]}), so nobody was screened out")
    try:
        if env_loader is None:
            import analyst_context as AC
            env_loader = AC.load_game_env
        env, env_note = env_loader(sport_key, date_str, meta, api_key, odds_sport_key)
        if env_note:
            notes.append(env_note.replace("the game-script angle is off", "game script is left out")
                         .replace("so the game-script angle is quiet", "so game script is left out"))
    except Exception as exc:                                    # noqa: BLE001
        notes.append(f"the spreads and totals couldn't be loaded ({str(exc)[:70]}), so game script is left out")
    return logs, inj, env, notes
