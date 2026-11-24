import sys, os, json; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
U = {"NBA": "basketball/nba", "NHL": "hockey/nhl", "NFL": "football/nfl", "NCAAMB": "basketball/mens-college-basketball"}
for lg, path in U.items():
    params = {"dates": "20261123", "limit": 300}
    if lg == "NCAAMB": params["groups"] = "50"
    j = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard", params=params, timeout=30).json()
    for e in j.get("events", []):
        c = e["competitions"][0]; st = c["status"]["type"]
        h = next(t for t in c["competitors"] if t["homeAway"] == "home"); a = next(t for t in c["competitors"] if t["homeAway"] == "away")
        print("S", lg, e["id"], a["team"]["displayName"], "@", h["team"]["displayName"], a.get("score"), h.get("score"), st.get("state"), st.get("shortDetail"))
# NBA props players
want = {"Tyrese Maxey": ("PTS+AST", 30.5, "Under"), "Collin Murray-Boyles": ("PTS+REB+AST", 20.5, "Under"),
        "Saddiq Bey": ("AST", 2.5, "Over"), "Quentin Grimes": ("AST", 3.5, "Over")}
j = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard", params={"dates": "20261123"}, timeout=30).json()
for e in j.get("events", []):
    s = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary", params={"event": e["id"]}, timeout=30).json()
    for team in (s.get("boxscore") or {}).get("players", []):
        for grp in team.get("statistics", []):
            keys = grp.get("keys") or grp.get("names") or []
            for ath in grp.get("athletes", []):
                nm = ath["athlete"]["displayName"]
                if nm in want:
                    print("P", nm, e["competitions"][0]["status"]["type"].get("shortDetail"), json.dumps(dict(zip(keys, ath.get("stats", [])))))
