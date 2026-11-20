"""Nov 20 (owner): how have 'Today's strongest picks, every sport' (the 15 likeliest saved picks of the day) done?"""
import sys
from collections import defaultdict
from datetime import date, timedelta
sys.path.insert(0, ".")
import props_engine as PE, todays_best as TB
SP = ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB")
agg = defaultdict(lambda: [0, 0, 0.0, 0.0, 0])   # hits, misses, chance sum, units, priced
for k in range(1, 22):
    d = (date.today() - timedelta(days=k)).isoformat()
    try:
        rows = [r for r in TB.collect(d, SP, past=True)["rows"] if r.get("kind") == "Prop"]
    except Exception as e:
        print("SPR fail", d, e); continue
    top = sorted(rows, key=lambda r: -(r.get("chance") or 0))[:15]
    for r in top:
        res = r.get("result")
        if res not in ("win", "loss"):
            continue
        priced = r.get("price") is not None and not r.get("pickem_only")
        for key in ("ALL", f"sport:{r.get('sport')}", "priced" if priced else "no-price", f"day:{d}"):
            a = agg[key]
            a[0] += res == "win"; a[1] += res == "loss"; a[2] += r.get("chance") or 0
            if priced:
                dd = PE.decimal(r["price"])
                a[3] += (dd - 1) if res == "win" else -1; a[4] += 1
for key in sorted(agg, key=lambda k: (k.startswith("day:"), k)):
    h, m, cs, u, n = agg[key]
    t = h + m
    print(f"SPR {key}: {h}-{m} ({h/t:.0%}) said {cs/t:.0%}" + (f" | priced {n}: {u/n:+.1%} per $1" if n else ""))
