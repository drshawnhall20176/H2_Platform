"""Nov 20 (owner): last 30 days of game lines -- did the model's PICK or its WINNER hit more, and which made money?"""
import sys
from collections import defaultdict
from datetime import date, timedelta
sys.path.insert(0, ".")
import todays_best as TB
import props_engine as PE


def dec(p):
    try:
        return PE.decimal(float(p))
    except (TypeError, ValueError):
        return None


agg = defaultdict(lambda: {"w": [0, 0, 0.0, 0], "p": [0, 0, 0.0, 0], "pm": defaultdict(lambda: [0, 0])})
for k in range(1, 31):
    d = (date.today() - timedelta(days=k)).isoformat()
    try:
        rows = TB.winner_rows(d, past=True)
    except Exception as e:
        print("PVW fail", d, e); continue
    for r in rows:
        lg = r.get("sport") if r.get("sport") != "INTL" else "INTL"
        for key, res, price in (("w", r.get("winner_result"), r.get("price")), ("p", r.get("best_result"), r.get("bet_price"))):
            if res not in ("win", "loss"):
                continue
            a = agg[lg][key]; a[0] += res == "win"; a[1] += 1
            dd = dec(price)
            if dd:
                a[2] += (dd - 1) if res == "win" else -1; a[3] += 1
            if key == "p":
                agg[lg]["pm"][r.get("bet_market")][0] += res == "win"
                agg[lg]["pm"][r.get("bet_market")][1] += 1
tot = {"w": [0, 0, 0.0, 0], "p": [0, 0, 0.0, 0]}
for lg, a in sorted(agg.items()):
    for key in ("w", "p"):
        for i in range(4):
            tot[key][i] += a[key][i]
    w, p = a["w"], a["p"]
    f = lambda x: f"{x[0]}-{x[1]-x[0]} ({x[0]/x[1]:.1%})" if x[1] else "-"
    g = lambda x: f"{x[2]/x[3]:+.1%} over {x[3]} priced" if x[3] else "no prices"
    print(f"PVW {lg}: WINNER {f(w)} roi {g(w)} | PICK {f(p)} roi {g(p)} | pick markets " +
          ", ".join(f"{m}:{v[0]}-{v[1]-v[0]}" for m, v in a["pm"].items()))
w, p = tot["w"], tot["p"]
print(f"PVW ALL: WINNER {w[0]}-{w[1]-w[0]} ({w[0]/w[1]:.1%}) roi {w[2]/max(w[3],1):+.1%} ({w[3]}) | PICK {p[0]}-{p[1]-p[0]} ({p[0]/max(p[1],1):.1%}) roi {p[2]/max(p[3],1):+.1%} ({p[3]})")
