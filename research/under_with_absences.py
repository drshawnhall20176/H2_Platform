"""Nov 7: after the model's own usage bump, do its NBA Unders lose when teammates are out? Graded snapshots."""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import daily_review as D     # noqa: E402
import model_store as MS     # noqa: E402

graded = D.grade_dates("NBA", MS.snapshot_dates("NBA"))
cell = defaultdict(lambda: [0, 0])
for d, rs in graded.items():
    for r in rs:
        if r.get("result") not in ("hit", "miss"):
            continue
        try:
            flags = " ".join(json.loads(r.get("flags") or "[]"))
        except Exception:                                       # noqa: BLE001
            flags = str(r.get("flags") or "")
        bump = "usage bump" in flags
        team_news = ("🩹" in flags) and (" out" in flags)
        play = r.get("use_tag") in ("🔒 Parlay + Single", "🎟️ Parlay + Single", "🎟️ Parlay leg", "🎯 Single only") or \
            (r.get("use_tag") or "").startswith(("🎟", "🎯"))
        tag = "bump" if bump else ("news, no bump" if team_news else "no news")
        for key in ((r.get("side"), tag, "all"), (r.get("side"), tag, "playable" if play else "pass")):
            c = cell[key]
            c[0] += r["result"] == "hit"
            c[1] += 1
for side in ("Under", "Over"):
    for tag in ("no news", "news, no bump", "bump"):
        for grp in ("all", "playable"):
            h, n = cell[(side, tag, grp)]
            if n:
                print(f"UA {side:5s} {tag:14s} {grp:8s} hit {h / n:.1%} (n={n})")
