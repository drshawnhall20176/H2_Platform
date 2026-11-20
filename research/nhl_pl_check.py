"""Nov 20: NHL puck-line pick prices -- which side's price is stored?"""
import sys, json
sys.path.insert(0, ".")
import model_store as MS, todays_best as TB
recs = MS.load_game_picks("NHL", ungraded=False)
print("PL n records", len(recs))
keys = sorted({k for r in recs[:50] for k in r})
print("PL keys", keys)
g = [r for r in recs if r.get("final_home") is not None][-12:]
for r in g:
    print("PL", json.dumps({k: r.get(k) for k in ("game_date", "home", "away", "home_spread", "spread_price", "spread_home_price",
          "spread_away_price", "best_home", "best_away", "model_margin", "final_home", "final_away", "home_p") if k in r}, default=str))
# what the rows show
from datetime import date, timedelta
for k in range(1, 6):
    d = (date.today() - timedelta(days=k)).isoformat()
    for w in TB.winner_rows(d, leagues=["NHL"], past=True):
        if w.get("bet_market") == "Spread":
            print("PLW", d, w.get("game"), w.get("best"), "line", w.get("bet_line"), "price", w.get("bet_price"), w.get("best_result"))
