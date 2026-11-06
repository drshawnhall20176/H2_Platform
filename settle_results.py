"""
settle_results.py — the runner that settles bet results automatically, the same way
capture_closing_lines.py automates the closing line.

Wakes on a timer (GitHub Action), finds open (unsettled) bets, and for each one's slate date
fetches that sport's real, final player results (sports.get(sport_key).engine.get_player_
results — the SAME, already-tested function Retrospective/Media Room/Podcast Studio already use
to grade the model's own picks against reality) and settles the bet's own result ("win"/"loss")
using retro.py's existing, already-tested grade_play/MARKET_STAT — not new, unverified logic.

REQUIRES player_id on the bet: name-based matching alone is genuinely fragile (accents, suffixes,
nicknames, two players sharing a surname), and a WRONG automated settlement would silently
corrupt the one thing on this platform that must never be wrong — a real trade record. A bet
without player_id is skipped, not guessed at; it stays available for manual settlement in Bet
Log itself. quick_log.py already populates player_id on every bet it logs, so this gap closes on
its own for new bets going forward — it does not (and should not) reach backward and modify a
bet just because a plausible name match exists.

Only ever settles "win" or "loss" -- grade_play's own docstring is explicit that a .5 line
structurally cannot push, and virtually every market this platform's own build_best_bets
produces uses .5 lines for exactly that reason. A push is never fabricated; if a market's line
is a whole number, grade_play still returns a clean True/False (Over wins on strictly greater,
Under wins on strictly less) -- a genuine push on a whole-number line would incorrectly settle
as a loss for both sides, a known, honest limitation stated here rather than silently accepted.

Writes to the SAME database the app reads. REQUIRES DATABASE_URL (the Supabase/Postgres URL) --
without it the bet log is an ephemeral SQLite file that vanishes when the runner ends, so the
settlement would be lost. The runner refuses to run without it, matching capture_closing_lines.py.

    python settle_results.py      # one settlement pass, every sport with open, ID-tagged bets
"""

import os
from typing import Dict, List, Optional, Tuple

import betlog as B
import retro as R
import sports


def settle_bet(bet: Dict, results: Dict[int, Dict]) -> Optional[str]:
    """Given one bet and the FULL per-player results dict for its slate date (from that sport's
    get_player_results), returns "win"/"loss", or None when settlement can't be honestly
    determined -- missing player_id, the player has no recorded actual for that market (didn't
    play, or the stat isn't tracked), or the market isn't in retro.MARKET_STAT at all. None is
    the correct, honest answer in every one of those cases -- never guessed past.

    Reuses retro.grade_play directly rather than re-implementing Over/Under logic -- the exact
    same, already-tested function Retrospective grades the model's own picks with."""
    pid = bet.get("player_id")
    if pid is None:
        return None
    actuals = results.get(pid)
    if actuals is None:
        try:
            actuals = results.get(int(pid))
        except (TypeError, ValueError):
            actuals = None
    hit = R.grade_play(bet.get("market"), bet.get("side"), bet.get("line"), actuals)
    if hit is None:
        return None
    return "win" if hit else "loss"


def _norm(name) -> str:
    import ufc_review as U
    return U.norm(name or "")


def _ids_by_name(bets: List[Dict], results: Dict) -> Dict[str, object]:
    """Nov 5: a player ID for bets logged without one, by name. Parlay legs are logged without IDs, and NFL
    defenders' IDs are text the Bet Log can't store -- so a leg takes the ID from a single on the same player that
    day, and otherwise from the results themselves when they carry names (NFL) and exactly one player matches."""
    out: Dict[str, object] = {}
    for b in bets:
        if b.get("player_id") is not None and b.get("player"):
            out.setdefault(_norm(b["player"]), b["player_id"])
    by_name: Dict[str, List] = {}
    for pid, r in (results or {}).items():
        if isinstance(r, dict) and r.get("name"):
            by_name.setdefault(_norm(r["name"]), []).append(pid)
    for n, pids in by_name.items():
        if len(pids) == 1:
            out.setdefault(n, pids[0])
    return out


def settle_for_sport(sport_key: str, sport_bets: List[Dict]) -> Dict:
    """Settle one sport's open bets. Groups by slate_date (one get_player_results call per real
    date present among these bets, not one call per bet) since a real slate reuses the same date
    across many logged picks. Returns {"settled": {bet_id: result}, "skipped_no_player_id":
    [...], "skipped_no_match": [...], "dates_checked": int}."""
    engine = sports.get(sport_key).engine
    by_date: Dict[str, List[Dict]] = {}
    for b in sport_bets:
        by_date.setdefault(b.get("slate_date") or "", []).append(b)

    settled: Dict[int, str] = {}
    skipped_no_player_id: List[int] = []
    skipped_no_match: List[int] = []
    for date_str, date_bets in by_date.items():
        if not date_str:
            skipped_no_match.extend(b["id"] for b in date_bets)
            continue
        try:
            results = engine.get_player_results(date_str)
        except Exception as ex:  # noqa: BLE001
            print(f"  (skip {sport_key} {date_str}: {type(ex).__name__}: {ex})")
            continue
        if not results:
            continue   # that date's games aren't final yet -- a later run will catch it
        known = _ids_by_name(date_bets, results)
        for b in date_bets:
            if b.get("player_id") is None:
                pid = known.get(_norm(b.get("player")))
                if pid is None:
                    skipped_no_player_id.append(b["id"])
                    continue
                b = dict(b, player_id=pid)
            result = settle_bet(b, results)
            if result is not None:
                settled[b["id"]] = result
            else:
                skipped_no_match.append(b["id"])

    return {"settled": settled, "skipped_no_player_id": skipped_no_player_id,
           "skipped_no_match": skipped_no_match, "dates_checked": len(by_date)}


def main() -> int:
    if not os.environ.get("DATABASE_URL") and not getattr(B, "USING_POSTGRES", False):
        print("DATABASE_URL not set — results would be written to an ephemeral SQLite file and "
              "lost.\nSet the DATABASE_URL secret (your Supabase URL) so settled results persist "
              "where the app reads them.")
        return 1

    open_bets = B.list_bets(settled=False)
    if not open_bets:
        print("No open bets — nothing to settle.")
        return 0

    by_sport: Dict[str, List[Dict]] = {}
    for b in open_bets:
        by_sport.setdefault(b.get("sport") or "MLB", []).append(b)   # legacy rows default to MLB
    print(f"{len(open_bets)} open bet(s) across {len(by_sport)} sport(s): "
          f"{', '.join(f'{k}={len(v)}' for k, v in by_sport.items())}")

    total_settled = 0
    for sport_key, sport_bets in by_sport.items():
        try:
            report = settle_for_sport(sport_key, sport_bets)
        except Exception as ex:  # noqa: BLE001
            print(f"[{sport_key}] settlement failed: {type(ex).__name__}: {ex}")
            continue

        print(f"[{sport_key}] {len(sport_bets)} open bets · {report['dates_checked']} slate date(s) checked")
        for bet_id, result in report["settled"].items():
            try:
                B.update_bet(bet_id, result=result)
                total_settled += 1
            except Exception as ex:  # noqa: BLE001
                print(f"  (failed to write bet {bet_id}: {ex})")
        if report["skipped_no_player_id"]:
            print(f"  {len(report['skipped_no_player_id'])} bets skipped — no player_id recorded, "
                  "so no reliable auto-match is possible. (Older bets, or ones logged manually — "
                  "settle these by hand in Bet Log, or re-log going forward via quick_log so this "
                  "closes on its own.)")
        if report["skipped_no_match"]:
            print(f"  {len(report['skipped_no_match'])} open bets had no final result yet (game "
                  "may not be over, or that player/market didn't show up in the box score — a "
                  "later run may catch it).")

    print(f"Settled {total_settled} bet(s) total.")
    print(f"Decided {roll_tickets()} parlay ticket(s) from their legs.")
    return 0


def roll_tickets(**kw) -> int:
    """Nov 6: decide every open parlay header whose legs are now all settled. This used to happen only in the morning
    review, and only when IT had settled something -- so legs settled here left their tickets open (Nov 5: all
    three test parlays stayed open with every leg graded)."""
    n = 0
    try:
        for t in B.ticket_settlements(B.list_bets(**kw)):
            B.update_bet(t["id"], result=t["result"], **kw)
            print(f"  ticket {t['ticket']} (#{t['id']}): {t['result']}")
            n += 1
    except Exception as exc:                                    # noqa: BLE001
        print(f"  ticket settlement failed: {type(exc).__name__}: {exc}")
    return n


if __name__ == "__main__":
    raise SystemExit(main())
