"""Nov 12: ESPN football summary -- pickcenter (pre-game spread/total), situation (possession, yard line), and the
play-by-play shape (drives -> plays with clock/score/yard line) for a finished NFL and college game; plus the live
box score shape for a basketball game (player stats so far) for live props."""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import intl_hoops as I     # noqa: E402

def show(t, x, n=1200):
    print("FP", t, json.dumps(x, default=str)[:n])

for path, d in (("football/nfl", "20261109"), ("football/college-football", "20261108")):
    sb = I._http(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard", {"dates": d, "limit": 5}) or {}
    ev = (sb.get("events") or [{}])[0]
    c = (ev.get("competitions") or [{}])[0]
    show(path + " situation(scoreboard)", c.get("situation"))
    show(path + " odds(scoreboard)", c.get("odds"), 900)
    s = I._http(f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary", {"event": ev.get("id")}) or {}
    print("FP", path, "summary keys", list(s.keys()))
    show(path + " pickcenter", s.get("pickcenter"), 1500)
    dr = (s.get("drives") or {}).get("previous") or []
    print("FP", path, "drives", len(dr))
    if dr:
        show(path + " drive0 keys", list(dr[0].keys()))
        pl = dr[1].get("plays") or []
        if pl:
            show(path + " play", pl[0], 1500)
    show(path + " competitors", [{k: t.get(k) for k in ("id", "homeAway")} | {"name": (t.get("team") or {}).get("displayName")} for t in c.get("competitors") or []])
# basketball live box shape (yesterday's NBA game summary boxscore players)
sb = I._http(I.ESPN_LEAGUE_URL["NBA"], {"dates": "20261111"}) or {}
ev = (sb.get("events") or [{}])[0]
s = I._http("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary", {"event": ev.get("id")}) or {}
bx = s.get("boxscore") or {}
pls = bx.get("players") or []
if pls:
    st = (pls[0].get("statistics") or [{}])[0]
    show("NBA box labels", st.get("labels") or st.get("names"))
    show("NBA box athlete0", (st.get("athletes") or [{}])[0], 900)
show("NBA pickcenter", s.get("pickcenter"), 900)
