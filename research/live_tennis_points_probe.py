"""Nov 12: does ESPN carry the live point score / server for a tennis match in progress? Prints the whole competition
JSON for live matches (scoreboard) and tries ESPN's core API competition / situation / status endpoints."""
import json
import os
import sys
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tennis_model as T     # noqa: E402

n = 0
for tour in ("atp", "wta"):
    data = T._http(T.ESPN.format(tour=tour), {"dates": date.today().strftime("%Y%m%d")}) or {}
    for ev in data.get("events") or []:
        for g in ev.get("groupings") or []:
            for c in g.get("competitions") or []:
                if ((c.get("status") or {}).get("type") or {}).get("state") != "in" or n >= 2:
                    continue
                n += 1
                cc = {k: v for k, v in c.items() if k not in ("broadcasts", "geoBroadcasts", "venue", "notes")}
                for cp in cc.get("competitors") or []:
                    cp.pop("athlete", None)
                print("PP comp", tour, ev.get("name"), json.dumps(cc, default=str)[:3000])
                lg = "atp" if tour == "atp" else "wta"
                base = f"https://sports.core.api.espn.com/v2/sports/tennis/leagues/{lg}/events/{ev.get('id')}/competitions/{c.get('id')}"
                for suf in ("", "/situation", "/status", "/competitors"):
                    js = T._http(base + suf)
                    print("PP core", suf or "/", json.dumps(js, default=str)[:1500])
print("PP live matches seen", n)
