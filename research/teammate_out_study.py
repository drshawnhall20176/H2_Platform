"""Nov 7: when a rotation teammate sits (15+ min a game), how often does a player beat his own recent average?
The props model builds from recent games, so this is what it misses on a night like tonight (Capela/Adams out:
Amen Thompson's rebounds; Davis out: Ayton). By stat and by whether the missing teammate is a big (C / F)."""
import os
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import script_data as D          # noqa: E402

c = D.CFG[os.environ.get("SPORT", "NBA")]
ids = D.event_ids(c)
with ThreadPoolExecutor(max_workers=8) as ex:
    packs = list(ex.map(lambda t: (t[1], D.package(c, t[0])), ids))
games = sorted([(d, p) for d, p in packs if p], key=lambda t: t[0])
print("TO games", len(games))
hist = defaultdict(list)            # pid -> [(date, stats)]
team_of = {}
pos_of = {}
STATS = {"points": "points", "rebounds": "rebounds", "assists": "assists", "threes": "threes"}
cell = defaultdict(lambda: [0, 0])
for d, p in games:
    by_team = defaultdict(set)
    for pid, st in p["players"].items():
        by_team[st.get("team")].add(pid)
        if st.get("pos"):
            pos_of[pid] = st["pos"]
    for tm in by_team:
        # rotation players of this team (by their own last 10 games) who are NOT in tonight's box
        recent_rot = {pid for pid, t in team_of.items() if t == tm and len(hist[pid]) >= 5
                      and statistics.mean(s.get("minutes") or 0 for _, s in hist[pid][-10:]) >= 15
                      and hist[pid][-1][0] >= (d[:8] + "01" if False else "0")}
        # only those who played for this team within their last 3 team games (not long-term absences)
        last_dates = sorted({dd for pid in by_team[tm] for dd, _ in hist[pid][-3:]})[-3:]
        missing = [pid for pid in recent_rot if pid not in by_team[tm] and hist[pid] and hist[pid][-1][0] in last_dates]
        miss_min = sum(statistics.mean(s.get("minutes") or 0 for _, s in hist[pid][-10:]) for pid in missing)
        big_out = any((pos_of.get(pid) or "") in ("C", "F", "PF", "FC") for pid in missing)
        for pid in by_team[tm]:
            st = p["players"][pid]
            h = hist[pid]
            if len(h) < 8:
                continue
            base_min = statistics.mean(s.get("minutes") or 0 for _, s in h[-15:])
            if base_min < 12:
                continue
            role = "starter" if base_min >= 26 else "bench"
            for stat, k in STATS.items():
                vals = [s.get(k) for _, s in h[-15:] if s.get(k) is not None]
                if not vals or st.get(k) is None:
                    continue
                beat = st[k] > statistics.mean(vals)
                grp = "none out" if not missing else ("big out" if big_out else "guard/wing out")
                for key in ((stat, role, grp), (stat, "all", grp), (stat, "all", "any out" if missing else "none out")):
                    cc = cell[key]
                    cc[0] += beat
                    cc[1] += 1
                if missing:
                    band = "15-25 min missing" if miss_min < 25 else ("25-45" if miss_min < 45 else "45+")
                    cc = cell[(stat, "all", band)]
                    cc[0] += beat
                    cc[1] += 1
    for pid, st in p["players"].items():
        hist[pid].append((d, st))
        team_of[pid] = st.get("team")
for stat in STATS:
    base = cell[(stat, "all", "none out")]
    print(f"TO {stat:9s} none out {base[0] / max(base[1], 1):.1%} (n={base[1]})")
    for grp in ("any out", "big out", "guard/wing out", "15-25 min missing", "25-45", "45+"):
        for role in ("all", "starter", "bench"):
            cc = cell[(stat, role, grp)]
            if cc[1] >= 100:
                print(f"TO   {grp:18s} {role:7s} beat avg {cc[0] / cc[1]:.1%} (n={cc[1]})  vs none-out {base[0] / max(base[1], 1):.1%}"
                      f"  lift {cc[0] / cc[1] - base[0] / max(base[1], 1):+.1%}")
