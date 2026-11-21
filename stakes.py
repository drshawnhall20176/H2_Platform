"""
stakes.py — the day's 💰 stake budget (Nov 20).

Owner (yes to "a daily cap that scales every stake down to fit"): each 💰 pick's quarter-Kelly stake
(props_engine.stake_units) is scaled so the whole day's 💰 picks -- props and game lines, every sport -- add up to
DAILY_CAP units at most (1u = 1% of the bankroll). On the first live slate, 19 college basketball game lines at the 2u
cap alone came to ~35u, a third of a bankroll on a rule with 13 days of evidence. Read from the saved boards (no Odds
API credits); refreshed every 10 minutes.
"""
from __future__ import annotations

import time
from typing import Dict, Optional

DAILY_CAP = 5.0          # Nov 21 (owner: "you make the call"): 5u a day while the edge is unproven (was 10u)
_CACHE: Dict[str, tuple] = {}


def raw_total(day: str, rows=None, games=None) -> float:
    """The day's uncapped 💰 stakes, in units."""
    import props_engine as PE
    if rows is None:
        import todays_best as TB
        rows = TB.collect(day, ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"))["rows"]
    if games is None:
        import money_score as MSC
        import todays_best as TB
        games = TB.winner_rows(day, leagues=list(MSC.MONEY_LEAGUES))
    tot = 0.0
    for r in rows or []:
        if r.get("kind") == "Prop" and r.get("money"):
            tot += PE.stake_units(r.get("chance"), r.get("price"), capped=False) or 0.0
    for g in games or []:
        if g.get("money"):
            tot += PE.stake_units(g.get("money_chance"), g.get("money_price"), capped=False) or 0.0
    return tot


def factor(day: Optional[str] = None, cap: float = DAILY_CAP) -> float:
    """1.0, or the share every 💰 stake is scaled by so the day fits `cap`."""
    import props_engine as PE
    d = (day or PE._et_today())[:10]
    hit = _CACHE.get(d)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    try:
        tot = raw_total(d)
    except Exception:                                           # noqa: BLE001 -- never blocks a page
        tot = 0.0
    f = 1.0 if tot <= cap or tot <= 0 else cap / tot
    _CACHE[d] = (time.time(), f)
    return f


def summary(day: Optional[str] = None) -> Dict:
    import props_engine as PE
    d = (day or PE._et_today())[:10]
    tot = raw_total(d)
    return {"raw": tot, "cap": DAILY_CAP, "factor": factor(d)}
