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

import pandas as pd

import mlb_engine as E
import statcast_data as SC

# Catchers below this called-pitch floor get dropped during team enrichment, not just left with
# a blank team — a token handful of called pitches wouldn't move team_catcher_framing's own
# weighted average meaningfully anyway (it already weights by called_pitches), so there's no real
# value in spending a lookup on them, and real value in NOT spending ~100+ network calls on
# catchers who'll barely register in the result.
MIN_CALLED_PITCHES_FOR_TEAM_LOOKUP = 100


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

    print(f"\nPulling Statcast pitcher expected-stats (xERA) for {year} from Baseball Savant...")
    try:
        p_path = SC.refresh_pitchers(year)
        p_lookup = SC.load_pitchers(p_path)
        print(f"Cached {len(p_lookup)} pitchers.")
    except Exception as e:  # noqa: BLE001
        # Same non-fatal posture as catcher framing below: a pitcher-xERA failure shouldn't block
        # the batter cache (Dinger Engine's own core dependency) from refreshing successfully.
        # Game Watch's own xERA signal just shows "no data" until this succeeds, same "optional,
        # fails soft" contract the batter data itself already has.
        tb = traceback.format_exc()
        first_line = str(e).replace("\n", " ")[:200]
        print(f"::warning::Pitcher xERA refresh failed (non-fatal, batter cache unaffected): {first_line}")
        print("Full traceback:")
        print(tb)

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
        cf_lookup = {}

    if cf_lookup:
        print(f"\nLooking up each qualified catcher's current team (>= "
             f"{MIN_CALLED_PITCHES_FOR_TEAM_LOOKUP} called pitches)...")
        # Savant's catcher-framing leaderboard has NO team column at all — confirmed directly
        # from a real response's own column list during a real production debugging session, not
        # assumed. team_catcher_framing (statcast_data.py) needs a real team to group by, so this
        # fills that gap with a genuinely different data source (MLB Stats API's own per-player
        # currentTeam), one lookup per qualified catcher — bounded by the called-pitches floor
        # above, not run against the full, unqualified (min_called_p=0) catcher list.
        enriched_rows = []
        for pid, c in cf_lookup.items():
            if c.get("called_pitches", 0) < MIN_CALLED_PITCHES_FOR_TEAM_LOOKUP:
                continue
            team = E.get_player_current_team(pid)
            enriched_rows.append({
                "player_id": pid, "name": c.get("name"),
                "team_id": (team or {}).get("id") or "",   # the real matching key
                "team": (team or {}).get("name") or "",    # display only — see team_catcher_
                                                           # framing's own docstring for why
                                                           # matching by name specifically caused
                                                           # a real production bug
                "called_pitches": c.get("called_pitches", 0.0),
                "strike_rate": c.get("strike_rate", 0.0),
                "framing_runs": c.get("framing_runs", 0.0),
            })
        if enriched_rows:
            pd.DataFrame(enriched_rows).to_csv(cf_path, index=False)
            with_team = sum(1 for r in enriched_rows if r["team_id"])
            without_team = [r["name"] for r in enriched_rows if not r["team_id"]]
            print(f"Wrote {len(enriched_rows)} qualified catchers, {with_team} with a resolved team.")
            if with_team < len(enriched_rows) * 0.5:
                # A REAL diagnostic gap otherwise: "N with a resolved team" alone doesn't say
                # WHICH catchers failed or WHY, and a low resolution rate is exactly the kind of
                # thing that would explain "no qualified data" for a specific team even with a
                # correctly-working id-based match — if a team's own catcher never resolved a
                # team_id at all, no id comparison can ever succeed for that team, real bug or not.
                print(f"::warning::Only {with_team}/{len(enriched_rows)} qualified catchers resolved "
                     f"a team via get_player_current_team — most calls are failing. Sample of "
                     f"catchers with NO resolved team: {without_team[:10]}")
            resolved_sample = [(r["name"], r["team_id"], r["team"]) for r in enriched_rows if r["team_id"]][:5]
            print(f"Sample of resolved catchers (name, team_id, team): {resolved_sample}")
        else:
            print("No catchers met the called-pitches floor for team enrichment — "
                 "leaving the unqualified cache as-is.")

    print("\nThe dashboard will use this automatically on its next refresh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
