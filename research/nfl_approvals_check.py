"""Nov 6: the owner approved every NFL suggestion on the Postgame page. List what's active and test each:
does the multiplier bring projections closer to what happened, on slates it wasn't fitted to (leave-one-slate-out),
and would the reads it flips have won?"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    import daily_review as D, model_store as MS
    print("## NFL tuning (all rows)")
    tun = [t for t in MS.list_tuning(active_only=False) if t.get("sport") == "NFL"]
    for t in tun:
        print(f"  id {t['id']} active={t['active']} {t['market']} · {t.get('slot') or '(all)'} ×{float(t['factor']):.3f} "
              f"approved {t.get('approved_ts')}")
    print("## NFL calibration rows")
    for c in MS.list_calibration(active_only=False):
        if str(c.get("sport", "")).startswith("NFL") or "NFL" in str(c):
            print("  ", {k: c.get(k) for k in ("id", "sport", "market", "factor", "s", "active", "approved_ts", "ts")})
    graded = D.grade_dates("NFL", MS.snapshot_dates("NFL"))
    rows, seen = [], set()
    for d, recs in graded.items():
        for r in recs:
            if r.get("actual") is None or r.get("projection") is None or r.get("line") is None:
                continue
            k = (d, r.get("player"), r.get("market"), r.get("line"))
            if k in seen:
                continue
            seen.add(k)
            rows.append(dict(r, date=d))
    print(f"## {len(rows)} graded NFL reads, slates {sorted(graded)}")
    active = [t for t in tun if t["active"]]
    for t in active:
        f = float(t["factor"])
        m, slot = t["market"], (t.get("slot") or "")
        g = [r for r in rows if r.get("market") == m and (not slot or str(r.get("slot") or "") == slot)]
        if not g:
            print(f"\n{m} · {slot or 'all'} ×{f:.3f}: no graded rows"); continue
        # note: snapshot projections may already include earlier tuning; treat as the baseline
        mae0 = sum(abs(r["actual"] - r["projection"]) for r in g) / len(g)
        mae1 = sum(abs(r["actual"] - r["projection"] * f) for r in g) / len(g)
        # leave-one-slate-out ratio
        loso = []
        for d in sorted({r["date"] for r in g}):
            tr = [r for r in g if r["date"] != d]
            te = [r for r in g if r["date"] == d]
            if not tr or not te:
                continue
            ratio = sum(r["actual"] for r in tr) / max(1e-9, sum(r["projection"] for r in tr))
            a = sum(abs(r["actual"] - r["projection"]) for r in te) / len(te)
            b = sum(abs(r["actual"] - r["projection"] * ratio) for r in te) / len(te)
            loso.append((d, len(te), ratio, a, b))
        flips = [r for r in g if (r["projection"] > r["line"]) != (r["projection"] * f > r["line"])]
        fw = sum(1 for r in flips if (r["actual"] > r["line"]) == (r["projection"] * f > r["line"]) and r["actual"] != r["line"])
        print(f"\n{m} · {slot or 'all'} ×{f:.3f}  n={len(g)}  avg error {mae0:.2f} -> {mae1:.2f}  "
              f"flips {len(flips)} (new side right {fw})")
        for d, n, ratio, a, b in loso:
            print(f"   held-out {d}: n={n} fit ×{ratio:.3f} on other slates  error {a:.2f} -> {b:.2f}")


if __name__ == "__main__":
    main()
