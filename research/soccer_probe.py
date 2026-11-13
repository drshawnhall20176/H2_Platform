"""Nov 13: what live soccer data is reachable -- ESPN slugs, a match summary's player stats, Odds API soccer keys/markets."""
import json, os, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read())

SLUGS = ["eng.1", "eng.2", "esp.1", "ita.1", "ger.1", "fra.1", "usa.1", "mex.1", "uefa.champions", "uefa.europa"]
ev_id = None
for s in SLUGS:
    try:
        d = get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{s}/scoreboard?dates=20251101-20251110&limit=200")
        evs = d.get("events", [])
        fin = [e for e in evs if e["status"]["type"].get("completed")]
        print(s, d.get("leagues", [{}])[0].get("name"), "events", len(evs), "final", len(fin))
        if s == "eng.1" and fin:
            ev_id = fin[0]["id"]
            c = fin[0]["competitions"][0]
            print("  sample", [(x["team"]["displayName"], x.get("score"), x.get("homeAway")) for x in c["competitors"]], fin[0]["date"])
    except Exception as e:
        print(s, "ERR", e)
if ev_id:
    sm = get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/summary?event={ev_id}")
    print("summary keys", list(sm.keys()))
    ro = sm.get("rosters") or []
    if ro:
        r0 = ro[0]
        print("roster team", r0.get("team", {}).get("displayName"), "players", len(r0.get("roster", [])))
        for p in r0.get("roster", [])[:3]:
            print("  ", p.get("athlete", {}).get("displayName"), p.get("starter"), p.get("subbedIn"), p.get("subbedOut"),
                  [(s.get("name"), s.get("value")) for s in p.get("stats", [])])
k = os.environ.get("ODDS_API_KEY")
if k:
    sp = get(f"https://api.the-odds-api.com/v4/sports?apiKey={k}")
    print("odds soccer keys:", [s["key"] for s in sp if s["key"].startswith("soccer_")][:60])
    evs = get(f"https://api.the-odds-api.com/v4/sports/soccer_epl/events?apiKey={k}")
    print("EPL events", len(evs))
    if evs:
        e = evs[0]
        url = (f"https://api.the-odds-api.com/v4/sports/soccer_epl/events/{e['id']}/odds?apiKey={k}&regions=us,eu"
               "&markets=h2h,totals,spreads,btts,player_goal_scorer_anytime,player_shots_on_target,player_shots&oddsFormat=american")
        try:
            o = get(url)
            for b in o.get("bookmakers", []):
                print("  ", b["key"], [m["key"] for m in b["markets"]])
        except Exception as ex:
            print("event odds ERR", ex)
else:
    print("no ODDS_API_KEY in research env")
