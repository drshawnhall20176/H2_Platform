"""
live_now.py -- Today's "🔴 Live now" strip: every game in progress across the sports, its score and clock, who the
live read favours, and how many live edges the Live page has flagged in it today (Nov 27).

Owner, Nov 27: "now we need to make sure the live game data is the best it can be so users can try and catch live
bets." Today is where people land, so a game in progress should be one tap from its live read. Light on purpose:
the scoreboards (cached, one call per league) and the Game Lab's saved pre-game projection -- no odds calls here; the
edge count comes from what the Live page already kept (live_signals.py).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, Iterable, List, Optional

LEAGUES = ("NFL", "NBA", "NHL", "NCAAF", "NCAAMB", "WNBA")
MAX_SHOWN = 12


def board(league: str, day_s: str) -> List[Dict]:
    """The league's scoreboard for the day (live_games.games). Tests stub this (conftest)."""
    from datetime import date
    import live_games as LG
    return LG.games(league, date.fromisoformat(day_s))


def in_progress(leagues: Iterable[str], games_for: Callable[[str], List[Dict]], workers: int = 6) -> List[Dict]:
    leagues = [lg for lg in leagues if lg in LEAGUES]
    if not leagues:
        return []

    def one(lg):
        try:
            return [g for g in games_for(lg) or [] if g.get("state") == "in"]
        except Exception:                                       # noqa: BLE001 -- one feed down never blanks the strip
            return []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(leagues)))) as ex:
        got = list(ex.map(one, leagues))
    return [g for lst in got for g in lst]


def item(g: Dict, pre: Optional[Dict], edges: int = 0) -> Dict:
    """{"league", "score", "clock", "lean", "edges"} -- lean is "Team 72%" from the live read, or "" without one."""
    import live_games as LG
    lean = ""
    try:
        r = LG.read_game(g, pre) if pre else None
        if r:
            wh = r["read"]["win_home"]
            lean = f"{g['home']} {wh:.0%}" if wh >= 0.5 else f"{g['away']} {1 - wh:.0%}"
    except Exception:                                           # noqa: BLE001
        lean = ""
    try:
        clock = LG.clock_text(g)
    except Exception:                                           # noqa: BLE001
        clock = g.get("detail") or ""
    return {"league": g.get("league"), "id": str(g.get("id")),
            "score": f"{g['away']} {float(g.get('away_score') or 0):.0f} @ {g['home']} "
                     f"{float(g.get('home_score') or 0):.0f}",
            "clock": clock, "lean": lean, "edges": int(edges or 0)}


def order(items: List[Dict]) -> List[Dict]:
    """Games with live edges first (most first), then the rest by league as listed."""
    rank = {lg: i for i, lg in enumerate(LEAGUES)}
    return sorted(items, key=lambda x: (-x["edges"], rank.get(x["league"], 99)))


def line(x: Dict) -> str:
    bits = [f"**{x['score']}**", x["clock"]]
    if x["lean"]:
        bits.append(f"live read: {x['lean']}")
    if x["edges"]:
        bits.append(f"🔥 {x['edges']} live edge{'s' if x['edges'] != 1 else ''} flagged")
    return f"{x['league']} · " + " · ".join(b for b in bits if b)
