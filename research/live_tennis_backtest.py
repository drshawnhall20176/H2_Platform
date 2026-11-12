"""Nov 12: the live tennis read on past matches. For every graded Tennis Lab pick (pre-match chance saved before the
match), take ESPN's per-set games and score the read at each set break against who won: Brier, calibration, and the
pre-match Brier for reference. Free, read-only."""
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import intl_hoops as I                                           # noqa: E402
import live_games as LG                                          # noqa: E402
import live_model as LM                                          # noqa: E402
import model_store as MS                                         # noqa: E402

picks = [p for p in MS.load_game_picks("TENNIS") if p.get("model_p") is not None and p.get("kickoff")]
days = sorted({p["kickoff"][:10] for p in picks})
print("TB picks", len(picks), "days", len(days))
matches = []
for d in days:
    for k in (0, 1):
        day = datetime.strptime(d, "%Y-%m-%d").date() + timedelta(days=k)
        matches += [m for m in LG.tennis_matches(day) if m["state"] == "post" and m.get("winner")]
seen, rows = set(), []
for m in matches:
    if m["id"] in seen:
        continue
    seen.add(m["id"])
    p1 = LG.tennis_pregame(m, picks)
    if p1 is None or len(m["sets1"]) < 2:
        continue
    y = 1.0 if m["winner"] == 1 else 0.0
    rows.append(("pre-match", p1, y))
    for k in range(1, len(m["sets1"])):
        a, b = m["sets1"][:k], m["sets2"][:k]
        rd = LM.tennis(p1, m["tour"], m["best_of"], a, b)
        if 0 < rd["win_a"] < 1:
            rows.append((f"after set {k}", rd["win_a"], y))
print("TB matches", len(seen), "with a pre-match chance", sum(1 for r in rows if r[0] == "pre-match"))
by = defaultdict(list)
for cp, p, y in rows:
    by[cp].append((p, y))
for cp, xs in by.items():
    br = sum((p - y) ** 2 for p, y in xs) / len(xs)
    print(f"TB {cp}: n={len(xs)} brier {br:.4f}")
cal = defaultdict(lambda: [0, 0.0, 0.0])
for cp, p, y in rows:
    if cp != "pre-match":
        b = min(int(p * 10), 9)
        cal[b][0] += 1
        cal[b][1] += p
        cal[b][2] += y
for b in sorted(cal):
    n, s, y = cal[b]
    if n >= 8:
        print(f"TB live {b * 10}-{b * 10 + 10}%: n={n} said {s / n:.0%} happened {y / n:.0%}")
