"""
approve_tuning.py — turn on owner-approved projection multipliers without a browser (the same store and effect as
Postgame Review → Approved adjustments, where each one can be retired). Run by the approve-tuning workflow.

  python approve_tuning.py --sport NBA --factors '{"Points": 0.95, "Assists": 0.96}' --reason "..."
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    import model_store as MS
    import model_tuning as MT
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", required=True)
    ap.add_argument("--factors", required=True, help='JSON {market: factor} or {"market|slot": factor}')
    ap.add_argument("--reason", required=True)
    a = ap.parse_args(argv)
    lo, hi = MT.FACTOR_RANGE
    bad = 0
    for key, f in json.loads(a.factors).items():
        market, _, slot = key.partition("|")
        f = float(f)
        if market == "calibration":
            ok = MS.approve_calibration(a.sport, f, {"reason": a.reason})
            print(f"{'approved' if ok else 'FAILED  '} {a.sport} honest-chance factor {f}")
            bad += 0 if ok else 1
            continue
        if not lo <= f <= hi:
            print(f"skip {key}: {f} is outside {lo}-{hi}")
            bad += 1
            continue
        ok = MS.approve_tuning(a.sport, market, f, a.reason, slot=slot)
        print(f"{'approved' if ok else 'FAILED  '} {a.sport} {market}{' · ' + slot if slot else ''} x{f}")
        bad += 0 if ok else 1
    print("Active now:", [(t["sport"], t["market"], t.get("slot") or "", t["factor"]) for t in MS.list_tuning()
                          if t["sport"] == a.sport])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
