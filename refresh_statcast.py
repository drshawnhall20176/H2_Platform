"""
refresh_statcast.py — pull the season's Statcast batter and catcher-framing data and cache it
to disk.

Run this once a day (manually, or via Task Scheduler / cron). The dashboard reads the
cached files instantly and never blocks on Baseball Savant.

    python refresh_statcast.py            # current season
    python refresh_statcast.py 2026       # explicit season

Requires pybaseball:  pip install pybaseball
"""

import sys
import traceback
from datetime import date

import statcast_data as SC


def main():
    year = int(sys.argv[1]) if len(sys.argv) > 1 else (date.today().year)
    print(f"Pulling Statcast batter data for {year} from Baseball Savant...")
    try:
        path = SC.refresh(year)
    except ImportError:
        print("pybaseball is not installed. Run:  pip install pybaseball")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"Refresh failed: {e}")
        print("If column names changed in your pybaseball version, tell Claude and we'll adjust.")
        return 1
    # quick sanity read-back
    lookup, k = SC.load(path)
    print(f"Cached {len(lookup)} batters. Calibration k = {round(k, 3) if k else 'n/a'}.")

    print(f"\nPulling catcher framing data for {year} from Baseball Savant...")
    try:
        cf_path = SC.refresh_catcher_framing(year)
        cf_lookup = SC.load_catcher_framing(cf_path)
        print(f"Cached {len(cf_lookup)} catchers.")
    except Exception as e:  # noqa: BLE001
        # Catcher framing is a newer addition, deliberately non-fatal to the whole refresh run —
        # a failure here shouldn't block the batter data (Dinger Engine's own core dependency)
        # from refreshing successfully. Matchup Lab's catcher framing section just shows nothing
        # until this succeeds, same "optional, fails soft" posture as the batter data itself.
        #
        # BUT non-fatal must not mean invisible — a plain print() here was a real diagnosis gap:
        # a run can show a green checkmark in the Actions list (the batter cache committed fine)
        # while catcher framing silently failed again underneath, exactly the same way twice in a
        # row, with no easy way to tell from the run list alone. "::warning::" is a real GitHub
        # Actions workflow command — any line printed with this prefix surfaces as an annotation
        # on the run's own summary page, not just buried in one step's raw log that has to be
        # opened and scrolled to find. The full traceback (not just str(e)) is also printed to
        # the regular log right after, for whoever does open the step and needs the real detail.
        tb = traceback.format_exc()
        first_line = str(e).replace("\n", " ")[:200]
        print(f"::warning::Catcher framing refresh failed (non-fatal, batter cache unaffected): {first_line}")
        print("Full traceback:")
        print(tb)

    print("\nThe dashboard will use this automatically on its next refresh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
