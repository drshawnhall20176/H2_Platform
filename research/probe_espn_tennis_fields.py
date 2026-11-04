"""research/probe_espn_tennis_fields.py — what ESPN says about each tennis event (city, level, venue), Nov 4 --
to label events the way sportsbooks do ("WTA Cali 125", "Challenger Lyon")."""
import json
import sys
from datetime import date

import requests


def main() -> int:
    for tour in ("atp", "wta"):
        j = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard",
                         params={"dates": date.today().strftime("%Y%m%d")}, timeout=30).json()
        for lg in j.get("leagues") or []:
            print("LEAGUE", tour, json.dumps({k: lg.get(k) for k in ("name", "abbreviation", "slug")}))
        for ev in j.get("events") or []:
            keep = {k: v for k, v in ev.items() if k not in ("groupings", "competitions", "links")}
            print(tour.upper(), json.dumps(keep, default=str)[:900])
            for g in (ev.get("groupings") or [])[:1]:
                for c in (g.get("competitions") or [])[:1]:
                    print("   COMP keys", sorted(c.keys()), json.dumps({k: c.get(k) for k in ("venue", "type", "round", "format", "notes")}, default=str)[:600])
    return 0


if __name__ == "__main__":
    sys.exit(main())
