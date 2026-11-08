"""Nov 8: wind and cold vs NFL player props. nflverse schedules (roof, wind mph, temp F) + weekly player stats,
2016-2025 regular seasons. Each player-game vs his own previous-5-game recency-weighted average; ratio by weather
bucket (outdoor games only; domes and closed roofs are the control). Held out: even vs odd seasons."""
import sys
from collections import defaultdict
import nflreadpy as nfl
import pandas as pd

seasons = list(range(2016, 2026))
sch = nfl.load_schedules(seasons).to_pandas()
sch = sch[sch["game_type"] == "REG"]
print("NW sched cols", [c for c in sch.columns if c in ("roof", "wind", "temp", "surface", "spread_line", "total_line")])
w = {}
for r in sch.to_dict("records"):
    for team in (r["home_team"], r["away_team"]):
        w[(int(r["season"]), int(r["week"]), team)] = (r.get("roof"), r.get("wind"), r.get("temp"))
ps = nfl.load_player_stats(seasons).to_pandas()
ps = ps[ps["season_type"] == "REG"]
STATS = {"pass_yds": ("passing_yards", lambda b: b["attempts"] >= 15), "pass_att": ("attempts", lambda b: b["attempts"] >= 15),
         "pass_td": ("passing_tds", lambda b: b["attempts"] >= 15),
         "rec_yds": ("receiving_yards", lambda b: b["receptions"] >= 2.5), "receptions": ("receptions", lambda b: b["receptions"] >= 2.5),
         "rush_yds": ("rushing_yards", lambda b: b["carries"] >= 8), "rush_att": ("carries", lambda b: b["carries"] >= 8),
         "fg_made": ("fg_made", lambda b: b["fg_att"] >= 1), "pat_made": ("pat_made", lambda b: b["pat_att"] >= 1)}
need = {"attempts", "receptions", "carries", "fg_att", "pat_att"} | {v[0] for v in STATS.values()}
cols = [c for c in need if c in ps.columns]
missing = need - set(cols)
print("NW missing cols", missing)
for c in missing:
    ps[c] = 0.0
ps = ps.sort_values(["player_id", "season", "week"])
W = [0.30, 0.25, 0.20, 0.15, 0.10]
def wmean(xs):
    xs = xs[::-1][:5]; ww = W[:len(xs)]
    return sum(a * b for a, b in zip(xs, ww)) / sum(ww)
def wbucket(roof, wind, temp):
    if roof in ("dome", "closed"):
        return "dome", "dome"
    wb = None if pd.isna(wind) else ("wind 0-9" if wind < 10 else "wind 10-14" if wind < 15 else "wind 15-19" if wind < 20 else "wind 20+")
    tb = None if pd.isna(temp) else ("temp <=25" if temp <= 25 else "temp 26-40" if temp <= 40 else "temp 41+")
    return wb, tb
cell = defaultdict(lambda: [0, 0.0, 0.0])
rows = []
for pid, g in ps.groupby("player_id"):
    recs = g[["season", "week", "team"] + list(need)].fillna(0).to_dict("records")
    for i in range(3, len(recs)):
        hist, cur = recs[max(0, i - 5):i], recs[i]
        wx = w.get((int(cur["season"]), int(cur["week"]), cur["team"]))
        if not wx:
            continue
        wb, tb = wbucket(*wx)
        base = {k: wmean([h[k] for h in hist]) for k in need}
        for s, (key, ok) in STATS.items():
            if ok(base) and base[key] > 0:
                for b in {wb, tb} - {None}:
                    for k in ((s, b), (s, b, int(cur["season"]) % 2)):
                        x = cell[k]; x[0] += 1; x[1] += cur[key]; x[2] += base[key]
for s in STATS:
    ctrl = cell[(s, "wind 0-9")]
    cr = ctrl[1] / ctrl[2] if ctrl[2] else 1
    for b in ("dome", "wind 0-9", "wind 10-14", "wind 15-19", "wind 20+", "temp 41+", "temp 26-40", "temp <=25"):
        n, y, bs = cell[(s, b)]
        if n:
            halves = [cell[(s, b, h)][1] / cell[(s, b, h)][2] / (cell[(s, "wind 0-9", h)][1] / cell[(s, "wind 0-9", h)][2])
                      for h in (0, 1) if cell[(s, b, h)][2] and cell[(s, "wind 0-9", h)][2]]
            print("NW", f"{s:10s} {b:11s} n={n:6d} actual/own-avg {y/bs:.3f}  vs calm outdoor {y/bs/cr:+.3f}".replace("+", "x")
                  + "  | even/odd seasons " + " ".join(f"{h:.3f}" for h in halves))
