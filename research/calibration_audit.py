"""
research/calibration_audit.py — full calibration audit of the props model (Nov 5). Read-only.

Grades every saved pre-game read (kickoff snapshots, all dates, every props sport) against ESPN box scores and
answers, per sport and market:
  * side lean      -- how often the model takes the Under, and how each side hits vs the chance it stated
  * beat the model -- how often the player finishes ABOVE the projection, and the typical miss (actual / projection)
  * the book line  -- how often the Over cleared the posted line (what "always Over" would have done)
  * held-out fix   -- if the projections were scaled by the ratio learned on the EARLIER half of the dates, would the
                      model's side have hit more often on the LATER half? (only those that improve out of sample count)
Prints a compact report; writes per-market results to stdout as JSON lines prefixed "J " for further use.
"""
from __future__ import annotations

import json
import math
import os
import statistics as stx
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def num(x):
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def pct(a, b):
    return f"{a / b:.0%}" if b else "—"


def side_hit(actual, line, side):
    import props_engine as PE
    thr = PE.threshold(line)
    if actual == thr:
        return None
    return (actual > thr) == (side == "Over")


def summarize(rows):
    n = len(rows)
    under = [r for r in rows if r["side"] == "Under"]
    over = [r for r in rows if r["side"] == "Over"]
    u_hit = sum(r["y"] for r in under)
    o_hit = sum(r["y"] for r in over)
    beat = [r for r in rows if r["projection"] and r["actual"] != r["projection"]]
    above = sum(1 for r in beat if r["actual"] > r["projection"])
    ratios = [r["actual"] / r["projection"] for r in rows if r["projection"] and r["projection"] > 0]
    over_line = [r for r in rows if r["actual"] != r["thr"]]
    cleared = sum(1 for r in over_line if r["actual"] > r["thr"])
    said_u = stx.mean([r["chance"] for r in under if r["chance"] is not None]) if any(r["chance"] is not None for r in under) else None
    said_o = stx.mean([r["chance"] for r in over if r["chance"] is not None]) if any(r["chance"] is not None for r in over) else None
    return {"n": n, "under_share": len(under) / n if n else None, "under_n": len(under), "under_hit": u_hit / len(under) if under else None,
            "under_said": said_u, "over_n": len(over), "over_hit": o_hit / len(over) if over else None, "over_said": said_o,
            "beat_proj": above / len(beat) if beat else None, "median_ratio": stx.median(ratios) if ratios else None,
            "over_cleared_line": cleared / len(over_line) if over_line else None}


def heldout(rows, min_train=40, min_test=40):
    """Scale projections by median(actual/projection) learned on the earlier dates; compare the model side's hit rate
    on the later dates with and without the scale."""
    dates = sorted({r["date"] for r in rows})
    if len(dates) < 4:
        return None
    cut = dates[len(dates) // 2]
    train = [r for r in rows if r["date"] < cut and r["projection"] and r["projection"] > 0]
    test = [r for r in rows if r["date"] >= cut and r["projection"] and r["projection"] > 0]
    if len(train) < min_train or len(test) < min_test:
        return None
    k = stx.median([r["actual"] / r["projection"] for r in train])
    base = fixed = cnt = 0
    flips = 0
    for r in test:
        a = side_hit(r["actual"], r["line"], "Over" if r["projection"] > r["thr"] else "Under")
        b = side_hit(r["actual"], r["line"], "Over" if r["projection"] * k > r["thr"] else "Under")
        if a is None or b is None:
            continue
        cnt += 1
        base += a
        fixed += b
        flips += (r["projection"] > r["thr"]) != (r["projection"] * k > r["thr"])
    if not cnt:
        return None
    return {"k": round(k, 3), "test_n": cnt, "base": base / cnt, "fixed": fixed / cnt, "flipped": flips, "cut": cut}


def main() -> int:
    import daily_review as D
    import model_store as MS
    import props_engine as PE
    sports_list = (os.environ.get("AUDIT_SPORTS") or "NBA,NHL,NFL,NCAAF,NCAAMB").split(",")
    for sport in sports_list:
        dates = MS.snapshot_dates(sport)
        if not dates:
            print(f"\n######## {sport}: no saved reads")
            continue
        graded = D.grade_dates(sport, dates)
        rows = []
        for d, rs in graded.items():
            for r in rs:
                if r.get("result") not in ("hit", "miss"):
                    continue
                line, act, proj = num(r.get("line")), num(r.get("actual")), num(r.get("projection"))
                if line is None or act is None:
                    continue
                rows.append({"date": d, "market": r.get("market"), "side": r.get("side") or "Over", "line": line,
                             "thr": PE.threshold(line), "actual": act, "projection": proj, "chance": num(r.get("chance")),
                             "use": r.get("use_tag") or "—", "y": 1 if r["result"] == "hit" else 0,
                             "price": num(r.get("price")), "gap": r.get("gap") or "none"})
        if not rows:
            print(f"\n######## {sport}: nothing graded")
            continue
        s = summarize(rows)
        print(f"\n######## {sport}: {s['n']} graded reads over {len(graded)} slates ({min(graded)}..{max(graded)})")
        print(f"  model took the Under {s['under_share']:.0%} of the time; Over at the line cleared {s['over_cleared_line']:.0%}")
        print(f"  Under picks: {s['under_n']} hit {s['under_hit'] or 0:.0%} (said {s['under_said'] or 0:.0%}) | "
              f"Over picks: {s['over_n']} hit {s['over_hit'] or 0:.0%} (said {s['over_said'] or 0:.0%})")
        print(f"  player finished ABOVE the projection {s['beat_proj']:.0%}; median actual/projection {s['median_ratio']:.2f}")
        by_m = defaultdict(list)
        for r in rows:
            by_m[r["market"]].append(r)
        print(f"  {'market':26s} {'n':>5s} {'under%':>7s} {'U hit':>6s} {'U said':>7s} {'O hit':>6s} {'O said':>7s} "
              f"{'>proj':>6s} {'act/prj':>8s} {'O clr':>6s} | held-out scale: k, base->fixed (test n, flips)")
        for m, rs in sorted(by_m.items(), key=lambda kv: -len(kv[1])):
            if len(rs) < 30:
                continue
            q = summarize(rs)
            h = heldout(rs)
            f = lambda v: "—" if v is None else f"{v:.0%}"
            hs = "" if not h else f"k={h['k']:.2f} {h['base']:.1%}->{h['fixed']:.1%} (n={h['test_n']}, flips {h['flipped']})"
            print(f"  {str(m)[:26]:26s} {q['n']:5d} {f(q['under_share']):>7s} {f(q['under_hit']):>6s} {f(q['under_said']):>7s} "
                  f"{f(q['over_hit']):>6s} {f(q['over_said']):>7s} {f(q['beat_proj']):>6s} "
                  f"{(q['median_ratio'] or 0):8.2f} {f(q['over_cleared_line']):>6s} | {hs}")
            print("J " + json.dumps({"sport": sport, "market": m, **{k: (round(v, 4) if isinstance(v, float) else v)
                                                                     for k, v in q.items()}, "heldout": h}))
        # by Use tag and side
        by_u = defaultdict(list)
        for r in rows:
            by_u[(r["use"], r["side"])].append(r["y"])
        print("  by Use tag and side: " + "; ".join(f"{u} {sd} {sum(v)}/{len(v)} ({sum(v) / len(v):.0%})"
                                                     for (u, sd), v in sorted(by_u.items()) if len(v) >= 20))
        # projection size relative to the line: how far the model's number sat below / above the line on its Unders
        bands = [(-9, -0.3), (-0.3, -0.15), (-0.15, -0.05), (-0.05, 0), (0, 0.05), (0.05, 0.15), (0.15, 0.3), (0.3, 9)]
        out = []
        for lo, hi in bands:
            g = [r for r in rows if r["projection"] and r["line"] > 0 and lo <= (r["projection"] - r["line"]) / r["line"] < hi]
            if len(g) >= 20:
                ov = [r for r in g if r["actual"] != r["thr"]]
                out.append(f"proj {lo:+.0%}..{hi:+.0%} of line: Over cleared {pct(sum(1 for r in ov if r['actual'] > r['thr']), len(ov))} (n={len(g)})")
        print("  " + "\n  ".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
