"""Live check of soft_spots.py on today's NBA slate (public data only)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
import pytz
import position_data as PD, position_matchups as PM, soft_spots as SS
day = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
games = PD.list_games("NBA", day)
print("games", len(games), games[:1])
b = PD.load_bundle("NBA", day, games[0], False)
summ = PM.summarize(b.get("allowed") or {}, "NBA")
k = list(summ)[:3]
print("summary keys sample", k, [type(x).__name__ for x in k], "n", len(summ))
print("slot sample", {s: summ[k[0]][s] for s in summ[k[0]]})
pg = (b.get("props") or {}).get("pgames") or []
print("pgames", len(pg), pg[:1])
tonight = []
for g in games:
    tonight += [(g["home_id"], g["away_id"], f"{g.get('away')} @ {g.get('home')}", g.get("label")),
                (g["away_id"], g["home_id"], f"{g.get('away')} @ {g.get('home')}", g.get("label"))]
print("tonight id types", type(games[0]["home_id"]).__name__)
rows = SS.spots(summ, tonight, lambda t: PM.usage_depth(pg, t, "NBA", last_n=10), b.get("all_names") or {})
print("spots", len(rows))
for s in rows[:8]:
    print(" ", SS.headline(s), "|", s["offense"], [p.get("name") for p in s["players"]])
