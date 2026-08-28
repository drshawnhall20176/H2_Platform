"""
refresh_ncaaf.py — pull the season's CFBD roster, player season stats, and schedule, and cache
them to disk. Run on a schedule (GitHub Action) or manually. ncaaf_engine.py (not yet built)
reads the cached files and never talks to CFBD directly, the same relationship
matchup_data.py/refresh_matchups.py already have for pitch-level Statcast data.

    python refresh_ncaaf.py            # current season
    python refresh_ncaaf.py 2026       # explicit season

Requires CFBD_API_KEY (env var or Streamlit secret). No extra package beyond `requests` (already
a dependency) -- see ncaaf_data.py's own docstring for why this deliberately does NOT use the
official `cfbd` client package (a real, tested pydantic-version conflict with nflreadpy, not a
style preference).

COST NOTE: this makes 3 CFBD API calls per run for roster/season-stats/schedule, PLUS one
additional call per completed week for per-game player stats (typically 0-15 depending on how
far into the season it is) -- see ncaaf_data.refresh_player_game_stats's own docstring for the
full accounting. A full season pulled once totals roughly 3 + 15 = 18 calls; even run daily
through an entire season that's comfortably inside the provider's ~1,000-calls/month free-tier
budget. Not something to run on a tight loop regardless -- daily/weekly is the intended cadence,
not per-page-load.
"""

import os
import sys
import traceback
from datetime import date

import ncaaf_data as ND


def main() -> int:
    year = int(sys.argv[1]) if len(sys.argv) > 1 else date.today().year

    api_key = os.environ.get("CFBD_API_KEY")
    try:
        import streamlit as st
        api_key = api_key or st.secrets.get("CFBD_API_KEY")
    except Exception:
        pass
    if not api_key:
        print("CFBD_API_KEY not set — cannot fetch CollegeFootballData.com data.")
        return 1

    print(f"Pulling NCAAF roster data for {year} from CollegeFootballData.com...")
    try:
        path = ND.refresh_rosters(year, api_key)
        rosters = ND.load_rosters(path)
        print(f"Cached {len(rosters)} roster players.")
        if not rosters:
            # Distinguish "this season's data isn't posted to CFBD yet" (a real, mundane
            # possibility a month before kickoff -- rosters often aren't finalized in their
            # system until fall camp) from "something is structurally wrong with the request"
            # (bad param, endpoint issue, etc.) -- one extra cheap probe call, only spent when
            # the primary pull actually came back empty, not on every run.
            try:
                prior = ND._get("/roster", {"year": year - 1}, api_key)
                print(f"::warning::0 roster rows for {year}. Probed {year - 1} for comparison: "
                     f"{len(prior)} rows. "
                     + (f"{year - 1} has real data -- {year}'s roster likely just isn't posted "
                        f"to CFBD yet (common a month before the season starts)."
                        if prior else
                        f"{year - 1} is ALSO empty -- this points to something structural "
                        f"(request params, account access), not a 'too early in the season' gap."))
            except Exception as probe_e:  # noqa: BLE001
                print(f"::warning::0 roster rows for {year}, and the {year - 1} comparison "
                     f"probe itself failed: {probe_e}")
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        first_line = str(e).replace("\n", " ")[:300]
        print(f"::error::NCAAF roster refresh failed: {first_line}")
        print("Full traceback:")
        print(tb)
        return 1

    print(f"\nPulling NCAAF player season stats for {year}...")
    stats_year = year
    try:
        path = ND.refresh_player_season_stats(year, api_key)
        stats = ND.load_player_stats(path)
        print(f"Cached {len(stats)} players' season stat lines.")
        if stats and stats[0].get("season") is not None:
            stats_year = int(stats[0]["season"])
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        first_line = str(e).replace("\n", " ")[:300]
        print(f"::error::NCAAF player season stats refresh failed: {first_line}")
        print("Full traceback:")
        print(tb)
        return 1

    # Real bug this fixes, confirmed via a live run: refresh_schedule used to pull only `year`.
    # When player season stats fall back to year-1 (the block above), ncaaf_engine.
    # _team_games_played_for_stats_season needs THAT year's own schedule too, to count its real
    # completed games as the rate denominator -- without it, every team's games-played resolves
    # to 0 and player_row's own zero-games guard silently drops every player from the slate. See
    # ncaaf_data.refresh_schedule's own docstring for the full story.
    needed_years = sorted({year, stats_year})
    print(f"\nPulling NCAAF schedule for {needed_years}...")
    completed_weeks: list = []
    try:
        path = ND.refresh_schedule(needed_years, api_key)
        games = ND.load_schedule(path)
        print(f"Cached {len(games)} games total.")
        # Per-game stats below stay scoped to the TARGET year's own completed weeks only, not
        # stats_year's -- week numbers collide across seasons (both have a "week 6"), and the
        # per-game cache doesn't carry a season column yet, so mixing years in there would let
        # player_recent_games silently blend two different seasons' games together. A real,
        # separate concern from this fix, not solved here -- the bootstrap upgrade stays on its
        # honest parametric fallback until the TARGET season has its own completed weeks, even
        # though season-average projections now work correctly via the fix above.
        completed_weeks = sorted({g["week"] for g in games
                                  if g.get("season") == year and g.get("completed")
                                  and g.get("week") is not None})
    except Exception as e:  # noqa: BLE001
        # Non-fatal, same posture refresh_statcast.py already has for its own secondary pulls:
        # roster + player stats are the core dependency for a projections engine; the schedule
        # is needed for week resolution but a failure here shouldn't discard the two successful
        # pulls above.
        tb = traceback.format_exc()
        first_line = str(e).replace("\n", " ")[:300]
        print(f"::warning::NCAAF schedule refresh failed (roster/stats still cached): {first_line}")
        print("Full traceback:")
        print(tb)

    print(f"\nPulling NCAAF per-game player stats for {len(completed_weeks)} completed week(s)...")
    if not completed_weeks:
        print("No completed weeks yet this season (schedule failed above, or the season hasn't "
             "started) -- skipping. Real bootstrap projections and Retrospective grading fall "
             "back to their honest degraded paths until this has real data (see ncaaf_engine.py "
             "and ncaaf_projections.py's own docstrings for what those fallbacks are).")
    else:
        try:
            path = ND.refresh_player_game_stats(year, api_key, completed_weeks)
            game_stats = ND.load_player_game_stats(path)
            print(f"Cached {len(game_stats)} player-game row(s).")
        except Exception as e:  # noqa: BLE001
            # Non-fatal, same posture as the schedule pull above: this is what upgrades the
            # projections from parametric to bootstrap and enables real Retrospective grading,
            # but the platform still functions on the season-average fallback without it.
            tb = traceback.format_exc()
            first_line = str(e).replace("\n", " ")[:300]
            print(f"::warning::NCAAF per-game stats refresh failed (roster/season-stats/schedule "
                 f"still cached): {first_line}")
            print("Full traceback:")
            print(tb)

    print(f"\nPulling NCAAF drives for {len(completed_weeks)} completed week(s)...")
    if not completed_weeks:
        print("No completed weeks yet this season -- skipping. Drive-level simulation stays on "
             "its own honest \"no data yet\" path until this has real data (see ncaaf_engine.py's "
             "own get_team_drive_outcomes docstring for what that fallback is).")
    else:
        try:
            path = ND.refresh_drives(year, api_key, completed_weeks)
            drives = ND.load_drives(path)
            print(f"Cached {len(drives)} drive row(s).")
        except Exception as e:  # noqa: BLE001
            # Non-fatal, same posture as the two pulls above: this is what powers the real
            # possession-level drive simulation, but the platform still functions -- including
            # every other real NCAAF signal already built -- without it.
            tb = traceback.format_exc()
            first_line = str(e).replace("\n", " ")[:300]
            print(f"::warning::NCAAF drives refresh failed (roster/season-stats/schedule/"
                 f"player-game-stats still cached): {first_line}")
            print("Full traceback:")
            print(tb)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
