"""
refresh_calibration.py — the job that closes the feedback loop: turns real accumulated
grading_history into a real, fitted calibration correction per (sport, market), stored by
calibration_corrections.py, applied automatically by projections.build_best_bets (and each other
sport's own build_best_bets) -- the one shared source every page's own plays already come from,
so Top Leans, Graded Picks, Suggested Parlays, and Speculative Basket all inherit any real
correction with no separate wiring per page.

Run this on a schedule (GitHub Action, weekly) or by hand:
    python refresh_calibration.py

For every (sport, market) this platform tracks, pulls the FULL real accumulated history
(grading_history.fetch_graded_plays, no since_date cutoff -- more real history is always better
for a fit like this, unlike a "last N days" trend read), fits a real, shrunk correction via
retro.fit_market_calibration (a genuine no-op -- returns None -- for any market with fewer than
retro.CALIBRATION_MIN_N real settled plays, which is most markets, most weeks, at first), and
records every real fit via calibration_corrections.record_fit -- an append-only real audit entry,
never a silent overwrite of a prior one. Confirmed directly with the person building this
platform: 100 real settled plays before any correction is even attempted.

A REAL, SECOND, STACKED PASS -- PLAYER-LEVEL, ADDED DIRECTLY ON REQUEST: a real, specific example
(a hitter who's genuinely been a real "HR or bust" read over their own last 20+ real settled
plays, surfacing as a top play far more consistently than that real pattern justifies) that the
market-wide pass above can't reach on its own, since it corrects every player in a market the
same way. For every sport, ONE real fetch of the FULL real history across every market (retro.
fit_player_calibration pools across markets, the same real pooling player_calibration's own
display already uses -- see either function's own docstring), fits a real, shrunk per-player gap,
and records one via player_calibration_corrections.record_fit for every player who's cleared the
real floor. Confirmed directly with the person building this platform: 20 real settled plays
before any player-specific correction is even attempted -- deliberately lower than market-level's
100 (one specific player accumulating 100 real settled plays in a season would be rare), but
meaningfully higher than player_calibration's own display-only default (that page is a real,
deliberate EXPLORATORY tool for human judgment; this is a real, automatic correction reaching
live predictions, which needs real, proven evidence, not a hot week). RETROACTIVE BY
CONSTRUCTION, not a separate backfill step -- this reads the FULL real accumulated history same
as the market-level pass, so a player who's already cleared 20 real settled plays (including
anything already backfilled) gets a real correction on this very run, not "from now on."

WEEKLY, NOT NIGHTLY, ON PURPOSE: a single day's slate is nowhere near enough real evidence to
responsibly move a live coefficient without just chasing noise -- the exact overfitting explain_
miss's own docstring elsewhere on this platform already warns against. This runs on a real
cadence deliberately slower than the data arrives, so a correction only ever reflects genuine,
persistent evidence, not one unlucky or lucky night. Same real cadence for the player-level pass
too -- no reason for it to run any more often than the market-level one it's stacked alongside.

Writes to the SAME database the app reads. REQUIRES DATABASE_URL for a real fit to persist to
where the deployed app actually looks for it -- without it, grading_history and both correction
stores would each resolve to their own local, ephemeral SQLite file, and the runner refuses to
run, same posture as settle_results.py/capture_closing_lines.py.
"""

import os
import sys
from typing import Dict, Optional

import grading_history as GH
import calibration_corrections as CC
import player_calibration_corrections as PCC
import retro as R
import sports


def refresh_market(sport_key: str, market: str) -> Optional[Dict]:
    """One real (sport, market) refresh: fetch the full real history, fit, record if a real fit
    resulted. Returns the recorded fit dict, or None if grading_history had real plays for this
    market but genuinely fewer than retro.CALIBRATION_MIN_N settled ones -- not enough real
    evidence yet, an honest, expected outcome for most markets early on, not an error."""
    history = GH.fetch_graded_plays(sport_key, market=market)
    fit = R.fit_market_calibration(history)
    if fit is None:
        return None
    CC.record_fit(sport_key, market, fit, min_n_used=R.CALIBRATION_MIN_N)
    return fit


def refresh_players(sport_key: str) -> Dict[int, Dict]:
    """One real sport's player-level refresh: ONE real fetch of the FULL history across every
    market (fit_player_calibration pools across markets itself, so this needs one real fetch, not
    one per market the way refresh_market above does), fit, record one real row per player who's
    cleared the real floor. Returns {player_id: recorded fit} for this run -- a real, empty dict
    when no player has cleared PLAYER_CALIBRATION_MIN_N real settled plays yet for this sport, the
    honest, expected case early on, not an error."""
    history = GH.fetch_graded_plays(sport_key)   # every market, pooled -- fit_player_calibration's own real design
    fits = R.fit_player_calibration(history)
    for player_id, fit in fits.items():
        PCC.record_fit(sport_key, player_id, fit, min_n_used=R.PLAYER_CALIBRATION_MIN_N)
    return fits


def main() -> int:
    if not os.environ.get("DATABASE_URL") and not getattr(GH, "USING_POSTGRES", False):
        print("DATABASE_URL not set — real accumulated grading history and any fitted "
              "correction would be read from and written to an ephemeral SQLite file, lost on "
              "the next deploy.\nSet the DATABASE_URL secret (your Supabase URL) so this "
              "actually reads and writes where the deployed app looks.")
        return 1

    total_fit, total_checked = 0, 0
    total_players_fit = 0
    for sport in sports.REGISTRY.values():
        if not sport.has_projections:
            continue   # outcome-based sports (UFC) have no ModelProb/Conviction to correct
        for market in sport.market_map:
            total_checked += 1
            fit = refresh_market(sport.key, market)
            if fit:
                total_fit += 1
                print(f"{sport.key:6s} {market:28s} n={fit['n']:<5d} slope={fit['slope']:.3f} "
                     f"intercept={fit['intercept']:+.3f}  (shrink weight={fit['weight']:.2f})")

        player_fits = refresh_players(sport.key)
        total_players_fit += len(player_fits)
        for player_id, fit in sorted(player_fits.items(), key=lambda kv: -abs(kv[1]["shrunk_gap"])):
            print(f"{sport.key:6s} player={fit['player']:<22s} n={fit['n']:<5d} "
                 f"raw_gap={fit['raw_gap']:+.3f}  shrunk_gap={fit['shrunk_gap']:+.3f}  "
                 f"(shrink weight={fit['weight']:.2f})")

    print(f"\n{total_fit} of {total_checked} tracked market(s) had enough real evidence "
         f"(>= {R.CALIBRATION_MIN_N} settled plays) to fit or refresh a market-level correction "
         f"this run.")
    print(f"{total_players_fit} player(s), across every sport, had enough real evidence "
         f"(>= {R.PLAYER_CALIBRATION_MIN_N} settled plays) to fit or refresh a player-level "
         f"correction this run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
