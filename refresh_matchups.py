"""
refresh_matchups.py — pull a season of pitch-level Statcast and cache the Matchup Lab tables.

HEAVY JOB. This pulls the whole league's pitches for the season (chunked by day inside
pybaseball) and writes two compact tables the dashboard reads instantly:
    data/pitcher_arsenals.csv      (pitcher x pitch-type: usage, whiff, put-away, velo)
    data/hitter_pitch_splits.csv   (batter x family: whiff, SLG-against, xwOBA-against)

Run it in a scheduled job (GitHub Action), NOT in the app — a full-season pitch pull is far too
slow/heavy for the Streamlit free tier.

    python refresh_matchups.py            # current season
    python refresh_matchups.py 2026       # explicit season

Requires pybaseball:  pip install pybaseball
"""

import sys
from datetime import date

import matchup_data as MD


def main() -> int:
    year = int(sys.argv[1]) if len(sys.argv) > 1 else date.today().year
    print(f"Pulling pitch-level Statcast for {year} from Baseball Savant (this is slow)...")
    try:
        arsenal_path, hitter_path, hitter_type_path = MD.refresh(year)
    except ImportError:
        print("pybaseball is not installed. Run:  pip install pybaseball")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"Refresh failed: {e}")
        print("If pybaseball's column names drifted, tell Claude and we'll adjust the aggregation.")
        return 1
    print(f"Done.\n  {arsenal_path}\n  {hitter_path}\n  {hitter_type_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
