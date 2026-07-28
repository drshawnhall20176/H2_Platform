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

COST NOTE: this makes 3 CFBD API calls per run (roster, player season stats, schedule) --
comfortably inside the provider's ~1,000-calls/month free-tier budget even run daily through a
full season. See ncaaf_data.py's own docstring for the full accounting. Not something to run on
a tight loop regardless -- daily/weekly is the intended cadence, not per-page-load.
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
    try:
        path = ND.refresh_player_season_stats(year, api_key)
        stats = ND.load_player_stats(path)
        print(f"Cached {len(stats)} players' season stat lines.")
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        first_line = str(e).replace("\n", " ")[:300]
        print(f"::error::NCAAF player season stats refresh failed: {first_line}")
        print("Full traceback:")
        print(tb)
        return 1

    print(f"\nPulling NCAAF schedule for {year}...")
    try:
        path = ND.refresh_schedule(year, api_key)
        games = ND.load_schedule(path)
        print(f"Cached {len(games)} games.")
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

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
