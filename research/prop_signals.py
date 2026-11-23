import sys, os, json; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import daily_review as DR, model_store as MS, props_engine as PE
def dec(a):
    a = float(a); return 1 + (a / 100 if a > 0 else 100 / -a)
for sp in ("NBA", "NHL", "NFL", "NCAAF"):
    g = DR.grade_dates(sp, [d for d in MS.snapshot_dates(sp) if d >= "2026-10-15"])
    agg = {}
    for day, rs in g.items():
        half = "A" if day < "2026-11-09" else "B"
        for r in rs:
            if r.get("actual") is None or r.get("p_model") is None or r.get("p_market") is None or r.get("line") is None: continue
            if (r.get("book") or "") in PE.PICKEM_BOOKS or r.get("over_price") is None or r.get("under_price") is None: continue
            thr = PE.threshold(float(r["line"]))
            if r["actual"] == thr: continue
            pm, pmod = float(r["p_market"]), float(r["p_model"])
            over = pmod > pm
            side = "Over" if over else "Under"
            price = r["over_price"] if over else r["under_price"]
            hit = (r["actual"] > thr) == over
            gap = abs(pmod - pm)
            same = (pm > 0.5) == (pmod > 0.5)
            gb = "<3" if gap < .03 else "3-6" if gap < .06 else "6-10" if gap < .10 else "10+"
            u = dec(price) - 1 if hit else -1.0
            for key in [("side", side), ("side|gap", side, gb), ("dir|gap", "same" if same else "opp", gb),
                        ("side|dir", side, "same" if same else "opp"), ("mkt|side", r.get("market"), side)]:
                a = agg.setdefault("|".join(map(str, key)) + "#" + half, [0, 0, 0.0])
                a[0] += 1; a[1] += hit; a[2] += u
    for k, (n, h, u) in sorted(agg.items()):
        if n >= 60: print("PS", sp, k, n, h, round(u, 2))
