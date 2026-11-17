import os, sys, json
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, todays_best as TB
for r in MS.load_game_picks("NCAAMB", ungraded=True):
    n = (str(r.get("home")) + str(r.get("away"))).lower()
    if any(k in n for k in ("hofstra", "rutgers", "notre dame")):
        keep = {k: r.get(k) for k in ("home", "away", "kickoff", "line", "open_line", "model_margin", "edge", "pick",
                                      "p_cover", "best_home_spread", "best_away_spread", "neutral", "sharp", "lean", "total", "flags")}
        keep.update(TB.spread_move(r, "NCAAMB"))
        print("G", json.dumps(keep, default=str))
