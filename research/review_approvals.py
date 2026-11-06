"""Nov 6: go through every sport's Postgame Review approvals (owner asked). Dry run unless APPLY.
A) NFL: retire the 23 market adjustments approved this morning (fitted to one Sunday; failed held-out checks).
B) Every sport: each pending market adjustment passes only if (1) at least two slates with 5+ props each point the
   same way as the adjustment and (2) leave-one-slate-out it lowers the error on the held-out slates overall.
C) Every sport not yet on it: the Overs vs Unders correction passes only if, fitted on earlier days, it beats the
   current chances on log loss on every later split with 150+ reads, and its singles don't do worse at the price."""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APPLY = False
SPORTS = ("NFL", "NCAAF", "NBA", "NCAAMB", "NHL")


def dec(a):
    try:
        a = float(a)
    except (TypeError, ValueError):
        return None
    if -100 < a < 100:
        return None
    return 1 + (a / 100 if a > 0 else 100 / -a)


def tuning_check(rows, f):
    by = {}
    for r in rows:
        by.setdefault(r["date"], []).append(r)
    agree = 0
    for d, g in by.items():
        if len(g) >= 5:
            ratio = sum(r["actual"] for r in g) / max(1e-9, sum(r["projection"] for r in g))
            agree += 1 if (ratio - 1) * (f - 1) > 0 else 0
    a = b = 0.0
    n = 0
    for d, te in by.items():
        tr = [r for r in rows if r["date"] != d]
        if len(tr) < 10:
            continue
        ratio = sum(r["actual"] for r in tr) / max(1e-9, sum(r["projection"] for r in tr))
        ratio = max(0.9, min(1.1, ratio))
        a += sum(abs(r["actual"] - r["projection"]) for r in te)
        b += sum(abs(r["actual"] - r["projection"] * ratio) for r in te)
        n += len(te)
    return agree, (a / n if n else None), (b / n if n else None)


def main():
    import calibration as CAL, daily_review as D, model_store as MS, postgame as PG
    # A
    nfl = [t for t in MS.list_tuning() if t["sport"] == "NFL"]
    print(f"## A) NFL active adjustments: {len(nfl)} -> retire all")
    if APPLY:
        print("   retired:", sum(1 for t in nfl if MS.retire_tuning(int(t["id"]))))
    for sport in SPORTS:
        dates = MS.snapshot_dates(sport)
        graded = D.grade_dates(sport, dates)
        rows = [dict(r, date=d) for d, rs in graded.items() for r in rs if r.get("result") in ("hit", "miss", "push")]
        print(f"\n## {sport}: {len(rows)} graded over {len(graded)} slates")
        active = {(t["sport"], t["market"], t.get("slot") or ""): float(t["factor"]) for t in MS.list_tuning()}
        if sport == "NFL" and APPLY:
            active = {k: v for k, v in active.items() if k[0] != "NFL"}
        sugg = [s for s in PG.suggestions(rows, active) if s["kind"] == "tuning"]
        print(f"B) {len(sugg)} market adjustment(s) suggested")
        for s in sugg:
            cur = active.get((s["sport"], s["market"], s["slot"] or ""), 1.0)
            step = s["factor"] / cur
            g = [r for r in rows if r.get("market") == s["market"] and r.get("actual") is not None
                 and r.get("projection") is not None and (not s["slot"] or str(r.get("slot") or "") == s["slot"])]
            agree, e0, e1 = tuning_check(g, step)
            ok = agree >= 2 and e0 is not None and e1 is not None and e1 < e0
            print(f"   {'APPROVE' if ok else 'skip   '} {s['market']} · {s['slot'] or 'all'} ×{s['factor']:.3f} "
                  f"(n={len(g)}, slates agreeing {agree}, held-out error {e0 and round(e0, 3)} -> {e1 and round(e1, 3)})")
            if ok and APPLY:
                MS.approve_tuning(s["sport"], s["market"], s["factor"],
                                  s["text"] + " [Nov 6 review: passed held-out check]", s["slot"])
        # C
        cur_side = CAL.side_factors(sport)
        if cur_side != (1.0, 1.0):
            print(f"C) Overs vs Unders already on {cur_side} -- left as is")
            continue
        data = [dict(date=r["date"], side=r.get("side") or "Over", p=float(r["chance"]), y=1 if r["result"] == "hit" else 0,
                     price=r.get("price")) for r in rows
                if r["result"] in ("hit", "miss") and r.get("chance") is not None and 0 < float(r["chance"]) < 1
                and r.get("market") not in CAL.SKIP_MARKETS]
        ds = sorted({r["date"] for r in data})
        grid = [round(0.3 + i * 0.01, 2) for i in range(71)]
        cl = lambda x: min(max(x, 1e-3), 1 - 1e-3)
        ll = lambda dd, f: -sum(math.log(cl(f(r))) if r["y"] else math.log(1 - cl(f(r))) for r in dd) / len(dd)
        wins = tests = 0
        roi_ok = True
        for i in range(1, len(ds)):
            tr = [r for r in data if r["date"] < ds[i]]
            te = [r for r in data if r["date"] >= ds[i]]
            if len(tr) < 150 or len(te) < 150:
                continue
            ss = {sd: min(grid, key=lambda g: ll([r for r in tr if r["side"] == sd] or tr, lambda r, g=g: CAL.honest(r["p"], g)))
                  for sd in ("Over", "Under")}
            f_new = lambda r: CAL.honest(r["p"], ss[r["side"]])
            l0, l1 = ll(te, lambda r: r["p"]), ll(te, f_new)
            def roi(f):
                pk = [r for r in te if f(r) >= 0.55 and dec(r["price"]) and f(r) * dec(r["price"]) - 1 >= 0.03]
                return (sum((dec(r["price"]) - 1) if r["y"] else -1 for r in pk) / len(pk), len(pk)) if pk else (None, 0)
            r0, r1 = roi(lambda r: r["p"]), roi(f_new)
            tests += 1
            wins += l1 < l0
            if r0[0] is not None and r1[0] is not None and r1[0] < r0[0] - 0.02:
                roi_ok = False
            print(f"   split {ds[i]}: fit O={ss['Over']} U={ss['Under']}  log loss {l0:.4f} -> {l1:.4f}  "
                  f"singles ROI {r0[0] if r0[0] is None else round(r0[0], 3)} ({r0[1]}) -> "
                  f"{r1[0] if r1[0] is None else round(r1[0], 3)} ({r1[1]})")
        full = CAL.fit_by_side([{"side": r["side"], "chance": r["p"], "result": "hit" if r["y"] else "miss"} for r in data])
        so, su = full["Over"]["s"], full["Under"]["s"]
        ok = tests >= 1 and wins == tests and roi_ok and full["Over"]["enough"] and full["Under"]["enough"]
        print(f"C) Overs vs Unders O={so} U={su}: {'APPROVE' if ok else 'skip'} (held-out wins {wins}/{tests}, singles ok {roi_ok})")
        if ok and APPLY:
            why = {"source": "Nov 6 approvals review (research/review_approvals.py), held-out by date",
                   "evidence": f"log loss better on {wins}/{tests} later splits"}
            print("   Over:", MS.approve_calibration(f"{sport}:Over", so, why), "Under:", MS.approve_calibration(f"{sport}:Under", su, why))


if __name__ == "__main__":
    main()
