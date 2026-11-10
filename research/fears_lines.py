import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as D
snaps = [s for s in MS.load_snapshots("NBA", ["2026-11-09"]) if "fears" in str(s.get("player", "")).lower()]
print("FL snapshot rows", len(snaps))
graded = [r for rows in D.grade_dates("NBA", ["2026-11-09"]).values() for r in rows if "fears" in str(r.get("player", "")).lower()]
for r in graded:
    print("FL", r.get("game"), "|", r.get("market"), r.get("side"), r.get("line"), r.get("price"), "| model", r.get("chance"), "| proj", r.get("projection"), "| actual", r.get("actual"), r.get("result"), "|", r.get("use"))
for s in snaps[:3]:
    print("FL keys", sorted(s.keys())[:25])
