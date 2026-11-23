import sys, os, json; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB
rows = TB.winner_rows("2026-11-22", leagues=["NCAAMB"], past=True)
keys = ["time","game","final","money_pick","money_market","money_side","money_line","money_price","money_score","money_chance","money",
        "best","best_chance","best_tested","backtest","lean_record","winner","chance","price","spread_txt","total_txt","model_txt",
        "spread_move","spread_move_why","money_result","best_result","winner_result","lock"]
out = []
for r in rows:
    f = r.get("_full") or {}
    d = {k: r.get(k) for k in keys}
    d.update({k: f.get(k) for k in ("home","away","home_spread","line","close_line","model_margin","model_p","fair_home","line_total","model_total","neutral","edge","close_edge","use","final_home","final_away","rescored","best_home","best_away")})
    out.append(d)
print("N", len(out))
print("JSON" + json.dumps(out, default=str))
