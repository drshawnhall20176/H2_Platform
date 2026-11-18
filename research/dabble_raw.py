"""Nov 18: what Dabble's per-pick 'price' means -- one event, every outcome for two players, plus price spread."""
import os, sys, json
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import odds_api as O, best_bets_data as BBD
api = BBD.get_odds_api_key()
evs = O._get("sports/basketball_nba/events", {"apiKey": api})[0]
for e in evs[:2]:
    js, _ = O._get(f"sports/basketball_nba/events/{e['id']}/odds",
                   {"apiKey": api, "bookmakers": "dabble_us_dfs,parlayplay,draftkings", "markets": "player_points,player_assists",
                    "oddsFormat": "american", "includeMultipliers": "true"})
    for bm in js.get("bookmakers", []):
        prices = Counter()
        for m in bm["markets"]:
            for oc in m["outcomes"]:
                prices[(oc.get("price"), oc.get("multiplier"))] += 1
        print("DR", e["home_team"], bm["key"], "price/multiplier spread", prices.most_common(12))
        first = None
        for m in bm["markets"]:
            for oc in m["outcomes"]:
                first = first or oc.get("description")
                if oc.get("description") == first:
                    print("DRX", bm["key"], m["key"], json.dumps(oc))
