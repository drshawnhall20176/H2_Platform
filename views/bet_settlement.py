"""
bet_settlement.py — automated Bet Log result settlement.

Turns retro.py's existing, already-tested grading machinery (the same real pipeline
Retrospective/Model Dashboard already use to grade the model's own board against real results)
toward a DIFFERENT target: a person's own real, logged bets. The betlog.py schema's own
player_id column was added specifically for this purpose (see its own comment there) — this
module is what actually uses it, which had never been built until now.

MLB ONLY FOR NOW, same honest scope as Bullpen Watch/Game Watch/the win-probability work: built
directly on mlb_engine, not routed through sports.active(). A bet logged for any other sport is
left in "unresolved" (see build_settlement_plan's own return shape below) rather than silently
mishandled — an honest gap, not a wrong result.

SAFETY-FIRST DESIGN, given this touches real financial/track-record data, a materially different
risk class from everything else built on this platform so far (which has all been read-only
analysis):
  - NEVER settles a bet whose game isn't confirmed Final via the schedule's own real status field
    — the exact same check ("final" in status.lower()) already used in five other places in
    mlb_engine.py, not a new, separately-invented one. A still-in-progress game's "0 hits so far"
    is not a loss, it's not determinable yet.
  - build_settlement_plan below only ever PROPOSES changes — it never writes to the database
    itself. The caller (Bet Log's own view) is responsible for showing the person a real preview
    and requiring an explicit confirmation before calling apply_settlement_plan, which is the
    only function in this file that actually calls betlog.update_bet.
"""

from typing import Any, Dict, List, Optional

import mlb_engine as E
import retro as R
import betlog as B


def _describe(bet: Dict[str, Any]) -> str:
    """A short, real, human-readable label for one bet, used in the settlement preview — reuses
    exactly the fields already on the bet row, not a new lookup."""
    who = bet.get("player") or bet.get("side") or "?"
    line = bet.get("line")
    line_str = f" {line:g}" if line is not None else ""
    return f"{who} · {bet.get('market', '?')} {bet.get('side', '')}{line_str}"


def build_settlement_plan(bets: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Given a list of OPEN (unsettled) bets, checks each one's real logged game against the
    real MLB schedule and — only for a game confirmed Final — determines its real result.

    Groups bets by slate_date so each date's schedule is fetched exactly once no matter how many
    bets reference it, and caches each game's own boxscore (needed only for player-prop bets, not
    moneylines, which settle directly off the schedule's own real score) so multiple bets sharing
    one game don't re-fetch it.

    Returns three real, separately-labeled buckets, never silently merged:
      "proposed": a real result was determined — {"bet_id", "description", "old_result",
        "new_result"} — ready to write once the caller gets explicit confirmation.
      "still_pending": the real game hasn't gone Final yet — correctly left alone, not guessed at.
      "unresolved": couldn't determine a result at all — {"bet_id", "description", "reason"} —
        flagged for manual entry, never silently skipped without explanation. Real reasons: no
        player_id and not a moneyline (can't auto-match at all), the bet's own game label didn't
        match any real game on that date, or the game is Final but the specific market/player
        combination still couldn't be resolved (an unrecognized market, for instance).
    """
    proposed: List[Dict[str, Any]] = []
    still_pending: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []

    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for b in bets:
        by_date.setdefault(b.get("slate_date"), []).append(b)

    for slate_date, date_bets in by_date.items():
        if not slate_date:
            unresolved.extend({"bet_id": b.get("id"), "description": _describe(b),
                               "reason": "no slate_date on this bet"} for b in date_bets)
            continue

        schedule = E.get_schedule(slate_date)
        by_label = {f"{g.get('away_name')} @ {g.get('home_name')}": g for g in schedule}
        boxscore_cache: Dict[Any, Dict[int, Dict]] = {}

        for b in date_bets:
            game_label = b.get("game")
            g = by_label.get(game_label)
            if g is None:
                unresolved.append({"bet_id": b.get("id"), "description": _describe(b),
                                   "reason": f"couldn't match '{game_label}' to a real game on {slate_date}"})
                continue

            if "final" not in (g.get("status", "") or "").lower():
                still_pending.append({"bet_id": b.get("id"), "description": _describe(b),
                                      "game": game_label, "status": g.get("status")})
                continue

            is_moneyline = (b.get("market") == "Moneyline")
            if is_moneyline:
                new_result = R.settle_moneyline_result(
                    b.get("side"), g.get("home_name"), g.get("away_name"),
                    g.get("home_score"), g.get("away_score"))
            elif b.get("player_id"):
                gid = g.get("gamePk")
                if gid not in boxscore_cache:
                    box = E.fetch_json(f"{E.BASE}/game/{gid}/boxscore")
                    boxscore_cache[gid] = E.parse_boxscore_results(box)
                actuals = boxscore_cache[gid].get(int(b["player_id"]))
                new_result = R.settle_bet_result(b.get("market"), b.get("side"), b.get("line"), actuals)
            else:
                unresolved.append({"bet_id": b.get("id"), "description": _describe(b),
                                   "reason": "no player_id on this bet, and not a moneyline — can't auto-match"})
                continue

            if new_result is None:
                unresolved.append({"bet_id": b.get("id"), "description": _describe(b),
                                   "reason": f"game is Final but couldn't determine a real result "
                                             f"for market '{b.get('market')}'"})
                continue

            proposed.append({"bet_id": b.get("id"), "description": _describe(b),
                             "old_result": b.get("result") or "(unsettled)", "new_result": new_result})

    return {"proposed": proposed, "still_pending": still_pending, "unresolved": unresolved}


def apply_settlement_plan(proposed: List[Dict[str, Any]]) -> int:
    """Actually writes the proposed results to the Bet Log. ONLY meant to be called after the
    caller's own UI has shown a real preview of `proposed` and gotten explicit confirmation —
    this function itself does not gate that; it trusts the caller, the same "confirm before
    mutating" responsibility split already established for every other real write on this
    platform. Returns the real count of bets updated."""
    for item in proposed:
        B.update_bet(item["bet_id"], result=item["new_result"])
    return len(proposed)
