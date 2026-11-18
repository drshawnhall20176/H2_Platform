import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json, urllib.request
import model_store as MS, betlog as B
# 1) Did Grayson Allen play? (Hornets @ Lakers, Nov 17)
u = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261117"
sb = json.load(urllib.request.urlopen(u, timeout=30))
for e in sb.get("events", []):
    if "Lakers" in e["name"] or "Hornets" in e["name"]:
        print("GAME", e["id"], e["name"], e["status"]["type"]["description"])
        s = json.load(urllib.request.urlopen(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={e['id']}", timeout=30))
        for t in s.get("boxscore", {}).get("players", []):
            for st in t.get("statistics", []):
                for a in st.get("athletes", []):
                    n = a["athlete"]["displayName"]
                    if "Allen" in n:
                        print("ALLEN", t["team"]["displayName"], n, a.get("didNotPlay"), a.get("reason"), a.get("stats"))
        for t in s.get("injuries", []) or []:
            for i in t.get("injuries", []):
                if "Allen" in i.get("athlete", {}).get("displayName", ""):
                    print("INJ", i["athlete"]["displayName"], i.get("status"))
b = [x for x in B.list_bets(settled=False) if x.get("id") == 759]
print("BET", b and {k: b[0].get(k) for k in ("id", "description", "stake", "entry_odds", "result")})
