"""Nov 7: which MMA markets does The Odds API carry per book for tonight's UFC bouts?"""
import os, sys, json
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ufc_engine as E
key = os.environ.get("ODDS_API_KEY")
evs = E.get_ufc_events(key, "2026-11-07")
pick = [e for e in evs if any(n in (e.get("home_team", "") + e.get("away_team", "")) for n in ("Walker", "Ko", "Parsons", "Henrique", "Souza"))]
for e in pick[:5]:
    data, hdr = E._get(f"sports/{E.UFC_SPORT}/events/{e['id']}/markets", {"apiKey": key, "regions": "us,us2,us_ex"})
    allm = Counter()
    per = {}
    for bk in (data or {}).get("bookmakers") or []:
        ks = [m.get("key") for m in bk.get("markets") or []]
        per[bk.get("key")] = ks
        allm.update(ks)
    print("MK", e.get("commence_time"), e.get("away_team"), "vs", e.get("home_team"), "| markets:", dict(allm))
    print("MK   draftkings:", per.get("draftkings"))
# try pulling the extra markets for one bout
if pick:
    eid = pick[0]["id"]
    for mk in ("spreads", "totals", "h2h_lay", "alternate_spreads", "alternate_totals"):
        try:
            d, h = E._get(f"sports/{E.UFC_SPORT}/events/{eid}/odds", {"apiKey": key, "regions": "us", "markets": mk, "oddsFormat": "american"})
            n = sum(1 for b in d.get("bookmakers") or [] for m in b.get("markets") or [])
            ex = next(((b["key"], m["outcomes"][:4]) for b in d.get("bookmakers") or [] for m in b.get("markets") or []), None)
            print("MK try", mk, "markets returned", n, "| e.g.", json.dumps(ex)[:300])
        except Exception as x:
            print("MK try", mk, "ERR", str(x)[:200])
