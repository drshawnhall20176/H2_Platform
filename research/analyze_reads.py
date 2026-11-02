"""
research/analyze_reads.py — every saved pre-game read, graded, and sliced to find what separates hits from misses.

For each sport: grades every kickoff snapshot in the model store against ESPN (daily_review.grade_dates), then
reports hit rate by the signals a read carries -- chance, cushion, edge, Use tag, market, side, line gap, price --
how well each signal RANKS reads (AUC: 0.5 = no better than random), and the hit rate of each slate's top 10 / 25
reads by each ranking. Writes graded rows to graded_<sport>.jsonl for further work. Read-only.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def auc(pairs):
    """pairs: [(score, hit 0/1)] -> probability a random hit outranks a random miss."""
    pairs = [(s, y) for s, y in pairs if s is not None]
    pos = [s for s, y in pairs if y]
    neg = [s for s, y in pairs if not y]
    if not pos or not neg:
        return None
    allv = sorted(pairs, key=lambda t: t[0])
    i = 0
    rank_sum = 0.0
    while i < len(allv):
        j = i
        while j < len(allv) and allv[j][0] == allv[i][0]:
            j += 1
        r = (i + j + 1) / 2
        rank_sum += r * sum(1 for k in range(i, j) if allv[k][1])
        i = j
    return (rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def num(x):
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def bucket(rows, key, edges, label):
    out = []
    for lo, hi in zip(edges, edges[1:]):
        g = [r for r in rows if r.get(key) is not None and lo <= r[key] < hi]
        if g:
            out.append(f"{label}{lo:g}..{hi:g}: {sum(r['y'] for r in g) / len(g):.0%} (n={len(g)})")
    return "  ".join(out)


def group(rows, key, min_n=15):
    d = defaultdict(list)
    for r in rows:
        d[r.get(key)].append(r["y"])
    items = sorted(((k, sum(v) / len(v), len(v)) for k, v in d.items() if len(v) >= min_n), key=lambda t: -t[1])
    return "  ".join(f"{k}: {p:.0%} (n={n})" for k, p, n in items)


def main(argv=None) -> int:
    import daily_review as D
    import model_store as MS
    ap = argparse.ArgumentParser()
    ap.add_argument("--sports", default="NBA,NHL,NCAAF,NCAAMB,NFL")
    a = ap.parse_args(argv)
    for sport in a.sports.split(","):
        dates = MS.snapshot_dates(sport)
        graded = D.grade_dates(sport, dates)
        rows = []
        for d, rs in graded.items():
            for r in rs:
                if r.get("result") not in ("hit", "miss"):
                    continue
                price = num(r.get("price"))
                rows.append({"date": d, "game": r.get("game"), "player": r.get("player"), "market": r.get("market"),
                             "slot": r.get("slot"), "side": r.get("side"), "line": num(r.get("line")),
                             "projection": num(r.get("projection")), "chance": num(r.get("chance")),
                             "cushion": num(r.get("cushion")), "ev": num(r.get("ev")), "price": price,
                             "use": r.get("use_tag") or "—", "gap": r.get("gap") or "none", "lean": r.get("lean"),
                             "flags": r.get("flags"), "actual": num(r.get("actual")),
                             "y": 1 if r["result"] == "hit" else 0, "model_hit": r.get("model_hit")})
        with open(f"graded_{sport}.jsonl", "w") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")
        print(f"\n==================== {sport}: {len(rows)} graded reads over {len(graded)} slates "
              f"({', '.join(sorted(graded))})")
        if not rows:
            continue
        print(f"overall hit {sum(r['y'] for r in rows) / len(rows):.1%}")
        print("chance   ", bucket(rows, "chance", [0, .5, .55, .6, .65, .7, .75, .8, 1.01], ""))
        print("cushion  ", bucket(rows, "cushion", [-9, 0, .05, .1, .15, .2, .3, .5, 99], ""))
        print("edge     ", bucket(rows, "ev", [-9, -.05, 0, .03, .06, .1, .15, 9], ""))
        print("use      ", group(rows, "use"))
        print("side     ", group(rows, "side"))
        print("gap      ", group(rows, "gap"))
        print("market   ", group(rows, "market", 30))
        lean = [r for r in rows if (r["chance"] or 0) >= 0.5 and r["market"] not in ("Anytime TD", "Goals")]
        print(f"-- reads the model leans on (chance 50%+, no TD/goal scorer props): {len(lean)}, "
              f"hit {sum(r['y'] for r in lean) / max(len(lean), 1):.1%}")
        for sd in ("Over", "Under"):
            g = [r for r in lean if r["side"] == sd]
            if g:
                print(f"   {sd:5s} n={len(g)} hit {sum(r['y'] for r in g) / len(g):.0%}   by chance: "
                      + bucket(g, "chance", [.5, .55, .6, .65, .7, .8, 1.01], ""))
        ms = defaultdict(list)
        for r in lean:
            ms[(r["market"], r["side"])].append(r["y"])
        print("   market x side: " + "  ".join(f"{m} {sd}: {sum(v) / len(v):.0%} (n={len(v)})"
                                             for (m, sd), v in sorted(ms.items(), key=lambda t: -len(t[1])) if len(v) >= 12))
        print("   use: " + group(lean, "use", 8) + "   | gap: " + group(lean, "gap", 8))
        rules = {
            "Under & chance 60%+": lambda r: r["side"] == "Under" and r["chance"] >= .6,
            "Under & chance 55%+ & no big gap": lambda r: r["side"] == "Under" and r["chance"] >= .55 and not str(r["gap"]).startswith("big"),
            "chance 60%+ & cushion 15%+": lambda r: r["chance"] >= .6 and (r["cushion"] or 0) >= .15,
            "playable Use (not Pass)": lambda r: r["use"] not in ("⛔ Pass", "—"),
            "playable & Under": lambda r: r["use"] not in ("⛔ Pass", "—") and r["side"] == "Under",
            "playable & Over": lambda r: r["use"] not in ("⛔ Pass", "—") and r["side"] == "Over",
        }
        for nm, fn in rules.items():
            g = [r for r in lean if fn(r)]
            if g:
                print(f"   rule {nm:34s} hit {sum(r['y'] for r in g) / len(g):.0%} (n={len(g)}, "
                      f"avg chance {sum(r['chance'] for r in g) / len(g):.0%})")
        for nm, fn in (("chance", lambda r: r["chance"]), ("cushion", lambda r: r["cushion"]),
                       ("edge", lambda r: r["ev"]),
                       ("chance x cushion", lambda r: None if r["chance"] is None or r["cushion"] is None
                        else r["chance"] + 0.25 * max(min(r["cushion"], 0.5), -0.5))):
            a_ = auc([(fn(r), r["y"]) for r in rows])
            tops = {}
            for n in (10, 25):
                hits = tot = 0
                for d in graded:
                    day = sorted((r for r in rows if r["date"] == d and fn(r) is not None), key=fn, reverse=True)[:n]
                    hits += sum(r["y"] for r in day)
                    tot += len(day)
                tops[n] = f"{hits / tot:.0%} (n={tot})" if tot else "—"
            print(f"rank by {nm:18s} AUC {a_ if a_ is None else round(a_, 3)}   top10/slate {tops[10]}   top25/slate {tops[25]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
