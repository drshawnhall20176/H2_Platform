"""Nov 18: Dabble's lines for a few players next to the books' -- are its lower lines alternates at a flat price?"""
import os, sys
from collections import Counter, defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD
api = BBD.get_odds_api_key()
date = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
offs = BBD.merge_offers(BBD.fetch_generic_offers("NBA", date, api), BBD.fetch_pickem_extra_offers("NBA", date, api))
by = defaultdict(list)
for o in offs:
    by[(o["player"], o["market"])].append(o)
n_lines = Counter()
for k, v in by.items():
    n_lines[sum(1 for o in v if "dabble_us_dfs" in (o.get("pickem") or {}))] += 1
print("DL dabble lines per player-market", sorted(n_lines.items()))
for who in ("Immanuel Quickley", "Ausar Thompson", "Al Horford"):
    for (p, m), v in by.items():
        if p != who:
            continue
        for o in sorted(v, key=lambda o: o["point"]):
            d = (o.get("pickem") or {}).get("dabble_us_dfs")
            pp = (o.get("pickem") or {}).get("parlayplay")
            print("DL", p, m, o["point"], "dabble", d, "pp", pp, "dk", o["over"].get("draftkings"), o["under"].get("draftkings"),
                  "novig", o["over"].get("novig"), o["under"].get("novig"), "px", o["over"].get("prophetx"), o["under"].get("prophetx"))
