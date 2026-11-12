"""Nov 12: what ESPN's tennis scoreboard gives for a match in progress (sets, current game points, server)."""
import json
import os
import sys
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tennis_model as T     # noqa: E402

for tour in ("atp", "wta"):
    data = T._http(T.ESPN.format(tour=tour), {"dates": date.today().strftime("%Y%m%d")}) or {}
    shown = 0
    for ev in data.get("events") or []:
        for g in ev.get("groupings") or []:
            for c in g.get("competitions") or []:
                st = ((c.get("status") or {}).get("type") or {})
                if shown < 2 and st.get("state") in ("in", "post"):
                    shown += 1
                    print("TP", tour, ev.get("name"), (g.get("grouping") or {}).get("displayName"), "state", st.get("state"))
                    print("TP status", json.dumps(c.get("status"), default=str)[:600])
                    print("TP comp keys", list(c.keys()))
                    for cp in c.get("competitors") or []:
                        print("TP competitor", json.dumps({k: v for k, v in cp.items() if k != "athlete"}, default=str)[:900])
                    print("TP situation", json.dumps(c.get("situation"), default=str)[:600])
    print("TP", tour, "events", len(data.get("events") or []))
