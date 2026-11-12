"""Nov 12: what the live feeds give for an in-progress game (period, clock, score) -- ESPN, EuroLeague, FIBA LiveStats
(Genius), and ESPN play-by-play for calibrating a live model on past games."""
import json
import os
import sys
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import intl_hoops as I     # noqa: E402

def show(tag, x, n=1500):
    print("LP", tag, json.dumps(x, default=str)[:n])

today = date.today()
# ESPN: status block of today's / yesterday's games
for lg, url in (("NBA", I.ESPN_LEAGUE_URL["NBA"]), ("NCAAMB", I.NCAAMB_URL), ("NBL", I.NBL_URL), ("NHL", I.ESPN_LEAGUE_URL["NHL"])):
    for d in (today, today - timedelta(days=1)):
        data = I._http(url, {"dates": d.strftime("%Y%m%d"), "limit": 3}) or {}
        evs = data.get("events") or []
        if evs:
            c = (evs[0].get("competitions") or [{}])[0]
            show(f"{lg} {d} status", c.get("status"))
            show(f"{lg} {d} competitor", {k: (c.get("competitors") or [{}])[0].get(k) for k in ("homeAway", "score", "linescores")})
            show(f"{lg} {d} event id/date", {"id": evs[0].get("id"), "date": evs[0].get("date"), "n": len(evs)})
            break
# ESPN play-by-play for one finished NBA game
data = I._http(I.ESPN_LEAGUE_URL["NBA"], {"dates": (today - timedelta(days=1)).strftime("%Y%m%d")}) or {}
eid = ((data.get("events") or [{}])[0]).get("id")
summ = I._http("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary", {"event": eid}) or {}
plays = summ.get("plays") or []
print("LP NBA summary keys", list(summ.keys())[:30], "plays", len(plays))
if plays:
    show("NBA play0", plays[0], 800)
    show("NBA play-last", plays[-1], 800)
# NCAAMB pbp
data = I._http(I.NCAAMB_URL, {"dates": (today - timedelta(days=1)).strftime("%Y%m%d"), "groups": 50, "limit": 5}) or {}
eid = ((data.get("events") or [{}])[0]).get("id")
summ = I._http("https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary", {"event": eid}) or {}
print("LP NCAAMB plays", len(summ.get("plays") or []))
# EuroLeague v2 game record + live header
code = "E" + I.season_of("EUROLEAGUE", today.isoformat())
g = I._http(I.EL_URL.format(comp="E", code=code)) or {}
games = g.get("data") or []
print("LP EL games", len(games))
if games:
    played = [x for x in games if x.get("played")]
    show("EL game keys", list(games[0].keys()), 800)
    if played:
        show("EL played game", {k: played[-1].get(k) for k in ("gameCode", "code", "identifier", "played", "local", "road", "utcDate", "round")}, 1200)
        gc = played[-1].get("gameCode") or played[-1].get("code")
        for u in (f"https://live.euroleague.net/api/Header?gamecode={gc}&seasoncode={code}",
                  f"https://api-live.euroleague.net/v2/competitions/E/seasons/{code}/games/{gc}",
                  f"https://live.euroleague.net/api/PlaybyPlay?gamecode={gc}&seasoncode={code}"):
            try:
                show("EL " + u.split("/api")[-1][:60], I._http(u), 1200)
            except Exception as e:
                print("LP EL err", u, e)
# Genius competition + match live data
for lg, cids in I.GENIUS_COMPS.items():
    ms = I.genius_games(lg)
    if ms:
        show(f"GS {lg} match", ms[0], 1200)
        mid = ms[0].get("matchId")
        live = I._http(f"https://fibalivestats.dcd.shared.geniussports.com/data/{mid}/data.json")
        if isinstance(live, dict):
            show(f"GS {lg} live keys", list(live.keys()), 800)
            show(f"GS {lg} live clock", {k: live.get(k) for k in ("period", "periodType", "clock", "inOT", "periodsMax", "periodLength", "periodLengthREGULAR", "periodLengthOVERTIME")}, 600)
            tm = live.get("tm") or {}
            show(f"GS {lg} live tm1", {k: (tm.get("1") or {}).get(k) for k in ("name", "score", "full_score")}, 300)
        break
