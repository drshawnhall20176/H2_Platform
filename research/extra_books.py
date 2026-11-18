"""Nov 18: which of Novig / Dabble / ParlayPlay / Underdog / Kalshi / ProphetX post player props the platform can read?"""
import os, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import odds_api as O, best_bets_data as BBD
api = BBD.get_odds_api_key()
BOOKS = ["novig", "dabble_us_dfs", "parlayplay", "underdog", "kalshi", "prophetx", "polymarket_us", "betopenly"]
for sp, key in (("NBA", "basketball_nba"), ("NHL", "icehockey_nhl"), ("NCAAMB", "basketball_ncaab")):
    evs = O._get(f"/sports/{key}/events", {"apiKey": api})[0] if hasattr(O, "_get") else []
    evs = [e for e in (evs or [])][:2]
    for e in evs:
        mk = ["player_points", "player_rebounds", "player_assists"] if sp != "NHL" else ["player_shots_on_goal", "player_points"]
        js, hdr = O._get(f"/sports/{key}/events/{e['id']}/odds", {"apiKey": api, "bookmakers": ",".join(BOOKS), "markets": ",".join(mk),
                                                                   "oddsFormat": "american", "includeMultipliers": "true"})
        c = Counter()
        ex = {}
        for bm in js.get("bookmakers", []):
            for m in bm.get("markets", []):
                c[bm["key"]] += len(m.get("outcomes", []))
                ex.setdefault(bm["key"], m.get("outcomes", [])[:2])
        print("XB", sp, e.get("home_team"), dict(c), "| used", {k: v for k, v in (hdr or {}).items() if "requests" in k.lower()})
        for k, v in ex.items(): print("XBX", sp, k, v)
