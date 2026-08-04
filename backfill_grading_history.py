"""
backfill_grading_history.py — grades and persists the last N real past MLB slates in one run,
using the exact same real logic Retrospective's own load_retro_mlb already uses (build the real
historical board, grade it against real results, compute real rank, persist) -- not a
reimplementation, and not fabricated data. Added directly on request: the "Model caught it — by
pre-game rank" chart on Retrospective only fills in as real dates get manually visited there one
at a time, which meant it was still showing just one bucket (Ranks 11+, n=131) with everything
else honestly below the real 20-play floor. This runs the same real pipeline against real games
that have already happened, just for several real dates in one pass instead of one visit at a
time -- real volume, faster, not synthetic volume.

Run it locally or as a one-off GitHub Action (manual "Run workflow", same as refresh-calibration):
    python backfill_grading_history.py                  # last 10 real days ending yesterday
    python backfill_grading_history.py --days 20         # a different real window
    python backfill_grading_history.py --end 2026-07-15  # a different real end date

REAL COST, STATED PLAINLY: each real date is a FULL real board rebuild -- MLB schedule, live odds,
Statcast, weather, the bullpen blend -- the exact same real cost a single real Retrospective visit
already pays, just repeated N times in one run rather than spread across N separate page loads.
Ten real dates is a genuinely heavier run than anything else in this codebase's own scheduled
jobs; this is why it's its own standalone script (run on demand), not folded into the weekly
refresh-calibration job or run automatically on a schedule.

REAL CAVEAT, CARRIED OVER FROM RETROSPECTIVE'S OWN DOCUMENTED ONE, NOT A NEW GAP: rebuilding a
past MLB slate uses CURRENT-season rates, not the rates that existed on that real date, so a row
persisted here reflects "what today's model would say about that game," not a genuine point-in-
time prediction -- real, useful signal for calibration on recently-played dates (little look-ahead
yet, which is exactly what a real "last 10 days" backfill stays within), a real bias for much
older ones. This is the same real reason this script defaults to a real, recent, bounded window
(10 real days) rather than defaulting to "as far back as possible."

Idempotent per (slate_date, sport) -- grading_history.record_graded_slate's own real REPLACE
semantics mean re-running this backfill (to extend the window, or just to refresh) never creates
duplicate rows for a date already graded here or from a real Retrospective visit.

Writes to the SAME database the app reads. REQUIRES DATABASE_URL for a real backfilled row to
persist to where the deployed app actually looks for it -- without it, grading_history would
resolve to an ephemeral local SQLite file and the real work would be lost on the next deploy, same
posture as every other real write job in this codebase.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import best_bets_data as BBD
import grading_history as GH
import mlb_engine as E
import retro as R

FIP_CONSTANT = E.FIP_CONSTANT_DEFAULT


def backfill_one_date(date_str: str) -> Optional[int]:
    """Grades and persists ONE real past MLB date, reusing the exact same real pipeline
    Retrospective's own load_retro_mlb already calls (build_mlb_board -> get_player_results ->
    grade_slate -> rank_within_market -> record_graded_slate) -- no reimplementation, and no
    display-only extras (reports/rows_by_pid/pitcher_rows) this script doesn't need. Returns the
    real number of graded plays persisted for this date, or None if the real board had no games
    or no results yet for this date (an honest skip, not an error -- a real, legitimate case for
    a date with a real off-day, or one whose results genuinely aren't final yet)."""
    rows, meta, plays, _books = BBD.build_mlb_board(date_str, FIP_CONSTANT)
    if not meta:
        return None   # a real off-day for this date -- nothing to grade, not an error

    results = E.get_player_results(date_str)
    graded, summary = R.grade_slate(plays, results)
    if not summary.get("graded"):
        return None   # real games existed, but no real results are final for this date yet

    ranks = R.rank_within_market(graded)
    graded_with_rank = [dict(p, Rank=ranks[p["PlayerId"]][0], OfTotal=ranks[p["PlayerId"]][1])
                        if p.get("PlayerId") in ranks else p for p in graded]
    return GH.record_graded_slate(date_str, "MLB", graded_with_rank)


def real_recent_dates(days: int, end_date: Optional[str] = None) -> List[str]:
    """The last `days` real calendar dates, most recent first, ending at end_date (default:
    yesterday -- today's own games won't have final results yet)."""
    if end_date:
        end = datetime.strptime(end_date, "%Y-%m-%d")
    else:
        end = datetime.now(timezone.utc) - timedelta(days=1)
    return [(end - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=10,
                        help="how many real past days to backfill (default: 10)")
    parser.add_argument("--end", type=str, default=None,
                        help="the real most-recent date to include, YYYY-MM-DD (default: yesterday)")
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL") and not getattr(GH, "USING_POSTGRES", False):
        print("DATABASE_URL not set — real backfilled grading would be written to an ephemeral "
              "SQLite file and lost on the next deploy.\nSet the DATABASE_URL secret (your "
              "Supabase URL) so this actually reads and writes where the deployed app looks.")
        return 1

    dates = real_recent_dates(args.days, args.end)
    print(f"Backfilling {len(dates)} real date(s): {dates[-1]} through {dates[0]}\n")

    total_plays, dates_graded, dates_skipped = 0, 0, 0
    for date_str in dates:
        n = backfill_one_date(date_str)
        if n is None:
            print(f"{date_str}  skipped (no real games or no final results yet)")
            dates_skipped += 1
        else:
            print(f"{date_str}  {n} real play(s) graded and persisted")
            total_plays += n
            dates_graded += 1

    print(f"\n{dates_graded} real date(s) backfilled, {dates_skipped} skipped, "
         f"{total_plays} total real play(s) persisted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
