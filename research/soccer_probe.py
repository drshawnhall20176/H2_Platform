"""Nov 13: ESPN soccer request formats + a match summary's player stats."""
import json, urllib.request
def get(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read())
for url in ["https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard",
            "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard?dates=20251101",
            "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard?dates=20251101-20251110",
            "https://site.web.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard?dates=20251101-20251110"]:
    try:
        d = get(url); evs = d.get("events", [])
        print("OK", url[-60:], len(evs))
    except Exception as e:
        print("ERR", url[-60:], e)
ev = None
for s in ["eng.1", "eng.2", "esp.1", "ita.1", "ger.1", "fra.1", "usa.1", "mex.1", "uefa.champions", "uefa.europa"]:
    try:
        d = get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{s}/scoreboard?dates=20251108")
        evs = d.get("events", [])
        print(s, len(evs), [e["status"]["type"]["name"] for e in evs][:3])
        if s == "eng.1" and evs:
            ev = evs[0]["id"]
    except Exception as e:
        print(s, "ERR", e)
if ev:
    sm = get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/summary?event={ev}")
    print("summary keys", list(sm.keys()))
    for r0 in (sm.get("rosters") or [])[:1]:
        print("team", r0.get("team", {}).get("displayName"), "n", len(r0.get("roster", [])))
        for p in r0.get("roster", [])[:4]:
            print("  ", p.get("athlete", {}).get("displayName"), "starter", p.get("starter"), "subIn", p.get("subbedIn"),
                  [(s.get("name"), s.get("displayValue")) for s in p.get("stats", [])])
