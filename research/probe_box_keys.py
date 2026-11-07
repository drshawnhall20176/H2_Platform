"""Probe ESPN summary box-score layouts for NFL / NHL / NCAAF / NCAAMB (Nov 7, Game Script expansion)."""
import json
import requests

H = {"User-Agent": "Mozilla/5.0"}
for path, day, extra in (("football/nfl", "20261102", {}), ("hockey/nhl", "20261105", {}),
                         ("football/college-football", "20261031", {"groups": "80"}),
                         ("basketball/mens-college-basketball", "20261105", {"groups": "50", "limit": "400"})):
    base = f"https://site.api.espn.com/apis/site/v2/sports/{path}"
    sb = requests.get(f"{base}/scoreboard", params={"dates": day, **extra}, headers=H, timeout=20).json()
    evs = sb.get("events") or []
    print("=====", path, "events", len(evs))
    if not evs:
        continue
    s = requests.get(f"{base}/summary", params={"event": evs[0]["id"]}, headers=H, timeout=20).json()
    pc = s.get("pickcenter") or []
    print("pickcenter", json.dumps(pc[:1])[:600])
    comp = (s.get("header") or {}).get("competitions", [{}])[0]
    print("competitors", [(c.get("homeAway"), c.get("score"), c.get("id")) for c in comp.get("competitors", [])])
    for grp in (s.get("boxscore") or {}).get("players") or []:
        for sg in grp.get("statistics") or []:
            a = (sg.get("athletes") or [{}])[0]
            print(" ", sg.get("name"), "keys=", sg.get("keys"), "labels=", sg.get("labels") or sg.get("names"),
                  "ex=", a.get("stats"), "starter=", a.get("starter"), "pos=", ((a.get("athlete") or {}).get("position") or {}).get("abbreviation"))
        break
