"""Nov 12: point score for a live tennis match -- core API linescores / competitor, and the site summary."""
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
            if "singles" not in ((g.get("grouping") or {}).get("displayName") or "").lower():
                continue
            for c in g.get("competitions") or []:
                if ((c.get("status") or {}).get("type") or {}).get("state") != "in" or n >= 1:
                    continue
                n += 1
                base = f"https://sports.core.api.espn.com/v2/sports/tennis/leagues/{tour}/events/{ev.get('id')}/competitions/{c.get('id')}"
                for cp in c.get("competitors") or []:
                    for suf in (f"/competitors/{cp['id']}", f"/competitors/{cp['id']}/linescores",
                                f"/competitors/{cp['id']}/score", f"/competitors/{cp['id']}/statistics"):
                        print("PQ", suf, json.dumps(T._http(base + suf), default=str)[:1200])
                    break
                for u, p in ((f"https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/summary", {"event": c.get("id")}),
                             (f"https://site.web.api.espn.com/apis/site/v2/sports/tennis/{tour}/summary", {"event": c.get("id")}),
                             (base + "/plays", None), (base + "/details", None)):
                    print("PQ", u.split("/v2/")[-1][:60], json.dumps(T._http(u, p), default=str)[:1500])
print("PQ seen", n)
