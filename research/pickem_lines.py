import os, sys
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD, slate_store as SS
day = SS._today_et(); api = BBD.get_odds_api_key()
offers = BBD.fetch_generic_offers("NBA", day, api)
g = defaultdict(list)
for o in offers:
    for app, sides in (o.get("pickem") or {}).items():
        g[(app, o["player"], o["market"])].append((o["point"], sides))
cnt = Counter((k[0], len(v)) for k, v in g.items())
print("PL lines per player-market by app", dict(cnt))
n = 0
for k, v in g.items():
    if len(v) > 1 and n < 8:
        print("PLX", k, v); n += 1
mult = sum(1 for v in g.values() for p, s in v for side in s.values() if side.get("multiplier") is not None)
print("PL entries with multiplier", mult, "of", sum(len(s) for v in g.values() for p, s in v))
ex = [(k, v) for k, v in g.items() if k[0] == "prizepicks"][:3]
print("PLE", ex)
