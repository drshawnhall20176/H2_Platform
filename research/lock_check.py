"""research/lock_check.py — are 🔒 Most probable picks reaching the graded snapshots? Per sport and slate: snapshots,
locks by the stored fields, and the stored morning report's lock record. Read-only (Nov 3)."""
from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    import daily_review as D
    import model_store as MS
    import props_engine as PE
    for sport in ("NFL", "NBA", "NCAAF", "NHL", "NCAAMB"):
        dates = MS.snapshot_dates(sport)[-6:]
        snaps = MS.load_snapshots(sport, dates)
        print(f"== {sport}: {len(snaps)} snapshots on {dates}")
        for d in dates:
            day = [s for s in snaps if s["slate_date"] == d]
            locks = [s for s in day if PE.most_probable(s.get("chance"), s.get("cushion"), s.get("gap"))]
            hi = [s for s in day if (s.get("chance") or 0) >= 0.60]
            print(f"  {d}: {len(day)} snaps · chance>=60%: {len(hi)} · +cushion>=15%: "
                  f"{sum(1 for s in hi if (s.get('cushion') or 0) >= 0.15)} · locks: {len(locks)} · "
                  f"gaps among 60%+: {Counter(str(s.get('gap')) for s in hi).most_common(4)} · "
                  f"sources: {Counter(s.get('source') for s in day).most_common(3)}")
        for m in MS.daily_review_mornings(sport)[:3]:
            rep = MS.load_daily_review(sport, m) or {}
            print(f"  morning {m}: " + "; ".join(f"{d}: {s.get('most_probable')}" for d, s in (rep.get("slates") or {}).items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
