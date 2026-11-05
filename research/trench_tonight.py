"""research/trench_tonight.py — tonight's linemen / corners / edge rushers out for a game, as the model sees them."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    import position_data as PD
    import sports
    eng = sports.get("NFL").engine
    season, week = 2026, 9
    teams = ("JAX", "BAL")
    inj = {t: {i.get("player"): PD.clean_status(i.get("status")) for i in eng.get_team_injuries(t, season, week)} for t in teams}
    for t in teams:
        print(t, "injury report:", {k: v for k, v in inj[t].items() if v})
    snaps = PD._snap_counts(season)
    for t in teams:
        print(t, "regulars:", PD.trench_regulars(snaps, t, week))
    print("OUT:", PD.nfl_trench_report(season, week, teams, inj))
    return 0


if __name__ == "__main__":
    sys.exit(main())
