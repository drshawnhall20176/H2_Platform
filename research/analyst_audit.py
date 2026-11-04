"""research/analyst_audit.py — what the Analyst Record says the model needs (Nov 4). Read-only."""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def dec(a):
    try:
        a = float(a)
    except (TypeError, ValueError):
        return None
    return 1 + (a / 100 if a > 0 else 100 / -a) if abs(a) >= 100 else None


def line(label, rows):
    n = len(rows)
    if not n:
        return
    h = sum(1 for r in rows if r["hit"])
    said = sum(r["model_prob"] for r in rows if r.get("model_prob") is not None) / max(1, sum(1 for r in rows if r.get("model_prob") is not None))
    priced = [r for r in rows if dec(r.get("price"))]
    prof = (sum((dec(r["price"]) - 1) if r["hit"] else -1 for r in priced) / len(priced)) if priced else None
    print(f"{label:46s} n={n:4d} hit {h / n:5.1%}  said {said:5.1%}  gap {h / n - said:+5.1%}  "
          f"profit/$1 {('—' if prof is None else f'{prof:+.1%}'):>7s} (priced {len(priced)})")


def main() -> int:
    import analyst_calibration as CAL
    import analyst_ledger as AL
    rows = AL.fetch_calls()
    g = [r for r in rows if r.get("hit") is not None]
    print(f"calls {len(rows)}, graded {len(g)}, voids/open {len(rows) - len(g)}; dates {rows[0]['call_date'] if rows else '-'} → {rows[-1]['call_date'] if rows else '-'}")
    print("```")
    line("ALL", g)
    print("-- by sport --")
    for s in sorted({r["sport"] for r in g}):
        line(f"  {s}", [r for r in g if r["sport"] == s])
    print("-- by stated chance --")
    for lo, hi in ((0, .5), (.5, .55), (.55, .6), (.6, .65), (.65, .7), (.7, .8), (.8, 1.01)):
        line(f"  {lo:.0%}-{hi:.0%}", [r for r in g if r.get("model_prob") is not None and lo <= r["model_prob"] < hi])
    print("-- by side --")
    for sd in ("Over", "Under", "Yes"):
        line(f"  {sd}", [r for r in g if r["side"] == sd])
    print("-- by sport x side --")
    for s in sorted({r["sport"] for r in g}):
        for sd in ("Over", "Under"):
            line(f"  {s} {sd}", [r for r in g if r["sport"] == s and r["side"] == sd])
    print("-- by market (10+) --")
    bym = defaultdict(list)
    for r in g:
        bym[(r["sport"], r["market"], r["side"])].append(r)
    for k, v in sorted(bym.items(), key=lambda kv: -len(kv[1])):
        if len(v) >= 10:
            line(f"  {k[0]} {k[1]} {k[2]}", v)
    print("-- by angle (each call counted under every angle it had) --")
    bya = defaultdict(list)
    for r in g:
        for a in r.get("angles") or []:
            key = a.get("family") or a.get("kind") or a.get("name") if isinstance(a, dict) else str(a)
            bya[str(key)[:40]].append(r)
    for k, v in sorted(bya.items(), key=lambda kv: -len(kv[1])):
        if len(v) >= 8:
            line(f"  angle {k}", v)
    print("-- number of angles / cautions --")
    for n in range(0, 5):
        line(f"  {n} angles", [r for r in g if len(r.get("angles") or []) == n])
    for n in range(0, 4):
        line(f"  {n} cautions", [r for r in g if len(r.get("cautions") or []) == n])
    print("-- gem / chalk --")
    line("  gem", [r for r in g if r.get("gem")])
    line("  chalk (main road)", [r for r in g if r.get("chalk")])
    line("  neither", [r for r in g if not r.get("gem") and not r.get("chalk")])
    print("-- conviction / score terciles --")
    for key in ("conviction", "score"):
        vals = sorted(r[key] for r in g if r.get(key) is not None)
        if len(vals) >= 30:
            t1, t2 = vals[len(vals) // 3], vals[2 * len(vals) // 3]
            line(f"  {key} low (<{t1:.2f})", [r for r in g if r.get(key) is not None and r[key] < t1])
            line(f"  {key} mid", [r for r in g if r.get(key) is not None and t1 <= r[key] < t2])
            line(f"  {key} high (>={t2:.2f})", [r for r in g if r.get(key) is not None and r[key] >= t2])
    print("-- calibration test per sport (fit on older calls, score on newest) --")
    for s in sorted({r["sport"] for r in g}):
        ev = CAL.evaluate([r for r in g if r["sport"] == s])
        if ev["status"] == "ok":
            m = ev["model"]
            print(f"  {s}: train {ev['n_train']} test {ev['n_test']} · test said {ev['test_stated']:.1%} hit {ev['test_hit']:.1%} "
                  f"adjusted {ev['test_adjusted']:.1%} · Brier raw {ev['brier_raw']:.4f} adj {ev['brier_adj']:.4f} "
                  f"helps={ev['helps']} · curve a={m['a']:.2f} b={m['b']:.2f} · 60%→{CAL.apply(m, .6):.1%} 70%→{CAL.apply(m, .7):.1%}")
        else:
            print(f"  {s}: not enough (n={ev['n']}, train {ev['n_train']}, test {ev['n_test']})")
    print("-- by week --")
    byw = defaultdict(list)
    for r in g:
        byw[str(r["date"])[:8] + ("1" if int(str(r["date"])[8:10]) <= 15 else "2")].append(r)
    for k in sorted(byw):
        line(f"  {k} (half-month)", byw[k])
    print("```")
    return 0


if __name__ == "__main__":
    sys.exit(main())
