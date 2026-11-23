import sys, os, json; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
F = ("kickoff","home","away","home_spread","line","open_line","model_margin","line_total","model_total","model_p","fair_home",
     "best_home","best_away","final_home","final_away","spread_price_home","spread_price_away","over_price","under_price","neutral")
for lg in ("NBA", "NHL", "NFL", "NCAAF"):
    recs = [p for p in MS.load_game_picks(lg) if p.get("final_home") is not None and str(p.get("kickoff"))[:10] >= "2026-10-15"]
    rows = [{k: p.get(k) for k in F} for p in recs]
    print("N", lg, len(rows))
    for i in range(0, len(rows), 40): print("J", lg, json.dumps(rows[i:i+40], default=str))
