import json, requests
H = {"User-Agent": "Mozilla/5.0"}
sb = requests.get("https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates=20261107", headers=H, timeout=30).json()
eid = sb["events"][0]["id"]
s = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/summary?event={eid}", headers=H, timeout=30).json()
for t in s["boxscore"]["players"][:1]:
    for x in t["statistics"]:
        print("NP ESPN", x.get("name"), x.get("keys"))
print("NP ESPN gameInfo keys", list((s.get("gameInfo") or {}).keys()))
try:
    r = requests.get("https://api-web.nhle.com/v1/score/2026-11-07", headers=H, timeout=30).json()
    gid = r["games"][0]["id"]
    print("NP NHL game", gid)
    b = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{gid}/boxscore", headers=H, timeout=30).json()
    f = b["playerByGameStats"]["homeTeam"]["forwards"][0]
    print("NP NHL box fields", sorted(f.keys()))
    toi = requests.get("https://api.nhle.com/stats/rest/en/skater/timeonice", params={"isAggregate": "false", "isGame": "true",
                        "cayenneExp": f"gameId={gid}", "limit": 5}, headers=H, timeout=30).json()
    print("NP stats toi", json.dumps(toi.get("data", [])[:1])[:800])
    nxt = requests.get("https://api-web.nhle.com/v1/score/2026-11-08", headers=H, timeout=30).json()
    g2 = nxt["games"][0]["id"]
    land = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{g2}/landing", headers=H, timeout=30).json()
    print("NP landing keys", sorted(land.keys()))
    print("NP landing matchup", json.dumps(land.get("matchup", {}))[:1200])
except Exception as e:
    print("NP NHL err", type(e).__name__, e)
