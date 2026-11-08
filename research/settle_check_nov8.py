"""Nov 8: what's still open after the rerun; settle Clowney (bet 429) from ESPN's box score."""
import os, sys, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B

bets = B.list_bets()
for b in bets:
    if b.get("is_real_bet") and b.get("slate_date") == "2026-11-07" and b.get("sport") == "NCAAF":
        print("SC NCAAF", b["id"], b.get("market"), b.get("side"), b.get("line"), b.get("game"), b.get("ticket"), "->", b.get("result"))
for b in bets:
    if b.get("is_real_bet") and not b.get("result"):
        print("SC OPEN", b["id"], b.get("sport"), b.get("slate_date"), b.get("player"), b.get("market"), b.get("side"), b.get("line"), b.get("game"))
b429 = next((b for b in bets if b["id"] == 429), None)
print("SC 429", {k: b429.get(k) for k in ("player", "market", "side", "line", "game", "slate_date", "result")} if b429 else None)
if b429 and not b429.get("result"):
    u = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261102"
    ev = json.load(urllib.request.urlopen(u, timeout=30))["events"]
    gid = next((e["id"] for e in ev if "Knicks" in e["name"] and "Nets" in e["name"]), None)
    print("SC game", gid)
    if gid:
        s = json.load(urllib.request.urlopen(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={gid}", timeout=30))
        for team in s["boxscore"]["players"]:
            st = team["statistics"][0]
            keys = st["keys"]
            for a in st["athletes"]:
                if "Clowney" in a["athlete"]["displayName"]:
                    row = dict(zip(keys, a.get("stats") or []))
                    print("SC Clowney", a.get("didNotPlay"), row)
                    tp = row.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted")
                    if a.get("didNotPlay") or not a.get("stats"):
                        B.update_bet(429, result="void"); print("SC 429 -> void (DNP)")
                    elif tp:
                        made = int(tp.split("-")[0]); line = float(b429["line"])
                        res = "win" if (made < line) == (str(b429["side"]).lower() == "under") else "loss"
                        B.update_bet(429, result=res); print("SC 429 ->", res, "made", made)
