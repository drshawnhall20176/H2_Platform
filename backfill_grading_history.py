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
    python backfill_grading_history.py                  # last 5 real days ending yesterday
    python backfill_grading_history.py --days 20         # a different real window
    python backfill_grading_history.py --end 2026-07-15  # a different real end date
    python backfill_grading_history.py --force            # re-grade dates that already have real data too

REAL COST, CONFIRMED DIRECTLY, NOT JUST ESTIMATED: a real run against 10 real dates genuinely ran
past 30 real minutes on a GitHub Actions runner and got killed by the job timeout -- each real
date is a FULL real board rebuild (schedule, live odds, Statcast, weather, the bullpen blend,
PLUS build_slate's own real per-player fetch fan-out -- confirmed elsewhere in this codebase to
mean roughly 250-300 individual real MLB Stats API calls for a full slate, already parallelized
at max_workers=8, so ~30-35 real sequential waves EVEN with that concurrency). Ten of those back
to back is a real, substantial amount of real network time, not a small job -- the default here
is 5 real days for exactly this reason (a real, comfortable default that finishes reliably),
with --days available for a longer real run for anyone willing to raise the workflow's own
timeout to match.

RESUME-AWARE, ADDED DIRECTLY AFTER A REAL TIMEOUT: if a run gets killed partway through (the
exact real scenario that prompted this), grading_history.record_graded_slate's own real REPLACE-
per-day semantics mean every date that DID finish before the cutoff is already safely persisted,
not lost -- but re-running the same window from scratch used to redo that already-finished real
work for no reason, real cost paid twice. Each date is now checked against what's already
persisted before doing the real work again; a date with real data already stored is skipped by
default (real, fast) unless --force is passed (e.g., because results were corrected since the
first real grading).

REAL CAVEAT, CARRIED OVER FROM RETROSPECTIVE'S OWN DOCUMENTED ONE, NOT A NEW GAP: rebuilding a
past MLB slate uses CURRENT-season rates, not the rates that existed on that real date, so a row
persisted here reflects "what today's model would say about that game," not a genuine point-in-
time prediction -- real, useful signal for calibration on recently-played dates (little look-ahead
yet, which is exactly what a real recent-days backfill stays within), a real bias for much older
ones. This is the same real reason this script defaults to a real, recent, bounded window rather
than defaulting to "as far back as possible."

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


def date_already_backfilled(date_str: str, sport: str = "MLB") -> bool:
    """True if real graded data already exists for this exact (date_str, sport) -- the real
    resume check: fetch_graded_plays' own since_date is an inclusive LOWER bound (matches this
    date and every later one too), so this filters the real result down to an exact match on
    that one date's own real rows rather than a broader window."""
    rows = GH.fetch_graded_plays(sport, since_date=date_str)
    return any(r.get("_slate_date") == date_str for r in rows)


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
    parser.add_argument("--days", type=int, default=5,
                        help="how many real past days to backfill (default: 5 -- see this "
                            "script's own module docstring for why 10 genuinely timed out once)")
    parser.add_argument("--end", type=str, default=None,
                        help="the real most-recent date to include, YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--force", action="store_true",
                        help="re-grade a date even if real data is already persisted for it "
                            "(default: skip it, real and fast -- see this script's own "
                            "RESUME-AWARE docstring section)")
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL") and not getattr(GH, "USING_POSTGRES", False):
        print("DATABASE_URL not set — real backfilled grading would be written to an ephemeral "
              "SQLite file and lost on the next deploy.\nSet the DATABASE_URL secret (your "
              "Supabase URL) so this actually reads and writes where the deployed app looks.",
              flush=True)
        return 1

    dates = real_recent_dates(args.days, args.end)
    print(f"Backfilling {len(dates)} real date(s): {dates[-1]} through {dates[0]}\n", flush=True)

    total_plays, dates_graded, dates_skipped, dates_already_done = 0, 0, 0, 0
    for date_str in dates:
        if not args.force and date_already_backfilled(date_str):
            print(f"{date_str}  already has real data -- skipping (use --force to re-grade)", flush=True)
            dates_already_done += 1
            continue
        n = backfill_one_date(date_str)
        if n is None:
            print(f"{date_str}  skipped (no real games or no final results yet)", flush=True)
            dates_skipped += 1
        else:
            print(f"{date_str}  {n} real play(s) graded and persisted", flush=True)
            total_plays += n
            dates_graded += 1

    print(f"\n{dates_graded} real date(s) backfilled, {dates_already_done} already done, "
         f"{dates_skipped} skipped, {total_plays} total real play(s) persisted.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
