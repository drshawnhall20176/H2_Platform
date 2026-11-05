"""
research/side_calibration_test.py — does a SIDE-AWARE honest chance pick better props? (Nov 5). Read-only.

For each sport: fit the honest-chance factor s (calibration.honest) on the earlier half of the graded dates three ways
-- none, one s for both sides (today's approvable factor), and one s per side (Over / Under) -- then on the later
half compare: log loss, and the record and ROI at the posted price of the reads that would qualify as a single
(chance >= 55% and +3% or better at the price) under each version.
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def num(x):
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def dec(a):
    a = num(a)
    if a is None or -100 < a < 100:
        return None
    return 1 + (a / 100 if a > 0 else 100 / -a)


def main() -> int:
    import calibration as CAL
    import daily_review as D
    import model_store as MS
    for sport in (os.environ.get("AUDIT_SPORTS") or "NBA,NHL,NFL").split(","):
        dates = MS.snapshot_dates(sport)
        graded = D.grade_dates(sport, dates)
        rows = []
        for d, rs in graded.items():
            for r in rs:
                if r.get("result") not in ("hit", "miss") or r.get("market") in CAL.SKIP_MARKETS:
                    continue
                p = num(r.get("chance"))
                if p is None or not 0 < p < 1:
                    continue
                rows.append({"date": d, "side": r.get("side") or "Over", "p": p, "y": 1 if r["result"] == "hit" else 0,
                             "price": r.get("price"), "market": r.get("market")})
        ds = sorted({r["date"] for r in rows})
        if len(ds) < 3 or len(rows) < 300:
            print(f"\n{sport}: not enough graded days ({len(ds)}) / reads ({len(rows)})")
            continue
        for cut_i in range(1, len(ds)):                      # every split point: train on days before, test on the rest
            cut = ds[cut_i]
            tr = [r for r in rows if r["date"] < cut]
            te = [r for r in rows if r["date"] >= cut]
            if len(tr) < 200 or len(te) < 200:
                continue
            grid = [round(0.3 + i * 0.01, 2) for i in range(71)]          # 0.30 .. 1.00
            ll = lambda data, s: -sum(math.log(CAL.honest(r["p"], s)) if r["y"] else math.log(1 - CAL.honest(r["p"], s))
                                      for r in data) / len(data)
            s_all = min(grid, key=lambda g: ll(tr, g))
            s_side = {sd: min(grid, key=lambda g: ll([r for r in tr if r["side"] == sd] or tr, g)) for sd in ("Over", "Under")}
            versions = {"as shown": lambda r: r["p"], f"one s={s_all}": lambda r: CAL.honest(r["p"], s_all),
                        f"by side O={s_side['Over']} U={s_side['Under']}": lambda r: CAL.honest(r["p"], s_side[r["side"]])}
            print(f"\n{sport} train {ds[0]}..{ds[cut_i - 1]} ({len(tr)}) -> test {cut}..{ds[-1]} ({len(te)})")
            for name, f in versions.items():
                lls = -sum(math.log(min(max(f(r), 1e-3), 1 - 1e-3)) if r["y"] else math.log(1 - min(max(f(r), 1e-3), 1 - 1e-3))
                           for r in te) / len(te)
                picks = [r for r in te if f(r) >= 0.55 and dec(r["price"]) and f(r) * dec(r["price"]) - 1 >= 0.03]
                w = sum(r["y"] for r in picks)
                roi = (sum((dec(r["price"]) - 1) if r["y"] else -1 for r in picks) / len(picks)) if picks else None
                ov = [r for r in picks if r["side"] == "Over"]
                print(f"   {name:34s} log loss {lls:.4f} | singles {w}-{len(picks) - w} "
                      f"({w / len(picks):.0%})" if picks else f"   {name:34s} log loss {lls:.4f} | no singles", end="")
                if picks:
                    print(f" ROI {roi:+.1%} | of them Overs {len(ov)} hit {sum(r['y'] for r in ov) / len(ov):.0%}" if ov
                          else f" ROI {roi:+.1%} | no Overs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
