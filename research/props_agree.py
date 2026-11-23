import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import daily_review as DR, model_store as MS, props_money as PM
for sp in ("NBA", "NHL", "NFL", "NCAAMB", "NCAAF"):
    try:
        g = DR.grade_dates(sp, [d for d in MS.snapshot_dates(sp) if d >= "2026-10-20"])
    except Exception as e:
        print("ERR", sp, e); continue
    rows = PM.rows_from_graded([r for rs in g.values() for r in rs])
    b = {}
    for r in rows:
        pm, pmod, y = r["pm"], r["pmod"], r["y"]
        over = pmod > pm
        side_m, side_mod, hit = (pm, pmod, y) if over else (1 - pm, 1 - pmod, 1 - y)
        gap = abs(pmod - pm)
        agree_fav = (pm > 0.5) == (pmod > 0.5)
        key = ("same fav" if agree_fav else "opposite fav", "<3%" if gap < .03 else "3-6%" if gap < .06 else "6-10%" if gap < .10 else "10%+")
        b.setdefault(key, []).append((hit, side_m, side_mod))
    for k in sorted(b):
        v = b[k]; n = len(v)
        h = sum(x[0] for x in v) / n; mk = sum(x[1] for x in v) / n; md = sum(x[2] for x in v) / n
        print("PA", sp, k, "n", n, f"hit {h:.3f} market said {mk:.3f} model said {md:.3f} edge vs market {h-mk:+.3f}")
