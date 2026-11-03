"""
research/single_bar_study.py — is the NFL single bar (value >= 5%, chance >= 55%) too tight? (Nov 2)

Grades every priced kickoff snapshot for a sport and reports the ACTUAL profit per $1 at the posted price for reads
that clear different (value, chance) bars, plus value buckets -- so the bar is set from results, not feel. Read-only.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _dec(a):
    a = float(a)
    return 1 + (a / 100 if a > 0 else 100 / -a)


def summarize(rows, label):
    n = len(rows)
    if not n:
        return f"{label:44s} n=   0"
    hits = sum(r["y"] for r in rows)
    profit = sum((_dec(r["price"]) - 1) if r["y"] else -1 for r in rows)
    imp = sum(1 / _dec(r["price"]) for r in rows) / n
    return (f"{label:44s} n={n:4d}  hit {hits / n:5.1%}  break-even {imp:5.1%}  profit/$1 {profit / n:+6.1%}  "
            f"(total {profit:+.1f}u)")


def main(argv=None) -> int:
    import daily_review as D
    import model_store as MS
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", default="NFL")
    a = ap.parse_args(argv)
    dates = MS.snapshot_dates(a.sport)
    graded = D.grade_dates(a.sport, dates)
    rows, seen = [], set()
    for d, recs in graded.items():
        for r in recs:
            if r.get("result") not in ("hit", "miss") or r.get("price") is None or r.get("chance") is None:
                continue
            k = (d, r.get("player"), r.get("market"), r.get("side"), r.get("line"))
            if k in seen:
                continue
            seen.add(k)
            ev = r.get("ev")
            if ev is None:
                ev = r["chance"] * _dec(r["price"]) - 1
            rows.append({"y": 1 if r["result"] == "hit" else 0, "price": r["price"], "chance": r["chance"], "ev": ev,
                         "market": r.get("market"), "side": r.get("side"), "date": d,
                         "defense": r.get("market") in ("Tackles + Assists", "Solo Tackles", "Sacks", "Assists",
                                                        "Interceptions")})
    print(f"## {a.sport} single-bar study — {len(rows)} priced, graded reads over {len(graded)} slate(s) "
          f"({min(graded) if graded else '—'} → {max(graded) if graded else '—'})\n```")
    print(summarize(rows, "every priced read"))
    print("-- by the model's value (edge) --")
    for lo, hi in [(-9, 0), (0, .02), (.02, .05), (.05, .08), (.08, .15), (.15, 9)]:
        print(summarize([r for r in rows if lo <= r["ev"] < hi], f"value {lo:+.0%} to {hi:+.0%}"))
    print("-- candidate bars (value >= v AND chance >= c) --")
    for v in (0.0, 0.02, 0.03, 0.05):
        for c in (0.0, 0.50, 0.52, 0.55, 0.58):
            print(summarize([r for r in rows if r["ev"] >= v and r["chance"] >= c], f"value>={v:.0%} chance>={c:.0%}"))
    print("-- the current bar, split --")
    cur = [r for r in rows if r["ev"] >= .05 and r["chance"] >= .55]
    print(summarize([r for r in cur if r["defense"]], "current bar: defense props"))
    print(summarize([r for r in cur if not r["defense"]], "current bar: offense/other"))
    print(summarize([r for r in rows if .02 <= r["ev"] < .05 and r["chance"] >= .55], "near miss: value 2-5%, chance>=55%"))
    print(summarize([r for r in rows if r["ev"] >= .05 and .50 <= r["chance"] < .55], "near miss: value>=5%, chance 50-55%"))
    print(summarize([r for r in rows if r["ev"] >= .05 and r["chance"] < .50], "value>=5%, chance <50% (longshots)"))
    print("-- by date (current bar) --")
    for d in sorted({r["date"] for r in rows}):
        print(summarize([r for r in cur if r["date"] == d], f"  {d}"))
    print("```")
    return 0


if __name__ == "__main__":
    sys.exit(main())
