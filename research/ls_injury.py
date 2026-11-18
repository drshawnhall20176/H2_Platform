"""Nov 18: RJ Barrett (ruled out) sat at the top of tonight's long shots -- what the feeds said and when."""
import os, sys, json
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests, long_shots_scan as LSS
date = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
s = LSS.load("NBA", date) or {}
print("LI scan at", s.get("at"), "rows", len(s.get("rows") or []), "top", [r.get("pick") for r in s.get("top") or []])
js = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries", timeout=20).json()
out = {}
for t in js.get("injuries", []):
    for i in t.get("injuries", []):
        out[(i.get("athlete") or {}).get("displayName")] = (i.get("status"), i.get("date"), i.get("shortComment"))
print("LI league-wide keys", list(js.keys())[:5], "players", len(out))
for r in (s.get("rows") or []):
    if r.get("Player") in out:
        print("LI listed", r.get("Player"), r.get("Bet"), out[r["Player"]])
print("LI barrett", out.get("RJ Barrett"))
