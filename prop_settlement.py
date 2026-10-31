"""
prop_settlement.py — auto-settle Bet Log player props from ESPN box scores (Oct 31).

The Bet Log could only auto-settle MLB (bet_settlement.py, by player ID). Everything else had to be settled by
hand in a spreadsheet-style grid. This grades NBA / NFL / NCAAF props the same way the Postgame Review grades the
model's snapshots -- the same ESPN fetch (postgame.fetch_results), the same box-score parsing and the same
per-market stat math (postgame.stat_value) -- matching the player by name, since these bets carry no player ID.

Nothing is guessed: a game that isn't final stays pending; a player missing from the box (a DNP, or a name the box
spells differently) or a market the box can't grade is reported as unresolved for a person to settle.

    build_plan(open_bets, sport) -> {"proposed": [...], "still_pending": [...], "unresolved": [...]}

`fetch` is injectable (postgame._http in production) so the whole thing is testable offline.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

import postgame as PG
import props_engine as PE

SPORTS = tuple(PG.ESPN)          # the sports ESPN box scores cover here (NFL, NCAAF, NBA)


def supported(sport: Optional[str]) -> bool:
    return sport in SPORTS


def _teams(game: Optional[str]) -> Optional[Tuple[str, str]]:
    """"Away @ Home" -> (away, home)."""
    parts = [p.strip() for p in str(game or "").split("@")]
    return (parts[0], parts[1]) if len(parts) == 2 and all(parts) else None


def _find_player(box: Dict, player: str) -> Optional[Dict]:
    want = PG._norm(PE.norm_name(player))
    hits = [stats.get(want) for stats in (box.get("teams") or {}).values() if stats.get(want) is not None]
    return hits[0] if len(hits) == 1 else None


def grade(side: str, line: float, actual: float) -> str:
    """win / loss / push for one prop. Yes (an anytime-style prop) reads as Over, No as Under."""
    over = (side or "Over").strip().lower() in ("over", "yes")
    if actual == line:
        return "push"
    return "win" if (actual > line) == over else "loss"


def _describe(b: Dict) -> str:
    line = b.get("line")
    return (f"#{b.get('id')} {b.get('player')} {b.get('market')} {b.get('side')} "
            f"{'' if line is None else f'{float(line):g}'} — {b.get('game')} ({b.get('slate_date')})")


def build_plan(open_bets: Sequence[Dict], sport: str, fetch: Callable = PG._http) -> Dict[str, List[Dict]]:
    plan: Dict[str, List[Dict]] = {"proposed": [], "still_pending": [], "unresolved": []}
    if not supported(sport):
        return plan
    gradable = []
    for b in open_bets:
        if b.get("result") or (b.get("market") or "") == "Parlay":
            continue
        if not b.get("player") or b.get("line") is None or not _teams(b.get("game")) or not b.get("slate_date"):
            plan["unresolved"].append({"bet_id": b.get("id"), "description": _describe(b),
                                       "why": "needs a player, a line, a date and an “Away @ Home” game to grade"})
            continue
        gradable.append(b)
    by_date: Dict[str, List[Dict]] = {}
    for b in gradable:
        by_date.setdefault(str(b["slate_date"])[:10], []).append(b)
    for date, rows in by_date.items():
        games = list(dict.fromkeys(_teams(b["game"]) for b in rows))
        try:
            results = PG.fetch_results(sport, date, games, fetch=fetch)
        except Exception as exc:                                    # noqa: BLE001 — report, never crash the page
            for b in rows:
                plan["still_pending"].append({"bet_id": b.get("id"), "description": _describe(b),
                                              "why": f"couldn't reach the box scores ({type(exc).__name__})"})
            continue
        for b in rows:
            box = results.get(_teams(b["game"]))
            if not box or not box.get("teams"):
                plan["unresolved"].append({"bet_id": b.get("id"), "description": _describe(b),
                                           "why": "no ESPN game found for these teams on this date"})
                continue
            if not box.get("final"):
                plan["still_pending"].append({"bet_id": b.get("id"), "description": _describe(b),
                                              "why": "game not final yet"})
                continue
            stats = _find_player(box, b["player"])
            if stats is None:
                plan["unresolved"].append({"bet_id": b.get("id"), "description": _describe(b),
                                           "why": "player not in the box score (did not play, or a different "
                                                  "spelling) — settle by hand (void for a DNP)"})
                continue
            actual = PG.stat_value(sport, b.get("market") or "", stats)
            if actual is None:
                plan["unresolved"].append({"bet_id": b.get("id"), "description": _describe(b),
                                           "why": f"the box score can't grade “{b.get('market')}”"})
                continue
            plan["proposed"].append({"bet_id": b.get("id"), "description": _describe(b),
                                     "actual": actual, "old_result": b.get("result") or "",
                                     "new_result": grade(b.get("side") or "Over", float(b["line"]), float(actual))})
    return plan
