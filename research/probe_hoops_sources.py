"""research/probe_hoops_sources.py — results/schedule sources for the leagues DK lists live (Nov 4): Slovenia 1. SKL,
Finland Korisliiga, Basketball Champions League, EuroCup Women, Bahrain, Czech NBL, Bulgaria NBL, FIBA Europe Cup,
Lebanon FLB. Read-only."""
import json
import sys
from collections import Counter

import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
     "Accept": "application/json"}


def get(u, params=None):
    try:
        r = requests.get(u, params=params or {}, timeout=30, headers=H)
        print(r.status_code, len(r.content), u)
        return r.json() if r.ok else None
    except Exception as exc:                                       # noqa: BLE001
        print("ERR", type(exc).__name__, u)


def main() -> int:
    j = get("https://api.sofascore.com/api/v1/sport/basketball/scheduled-events/2026-11-04")
    if j:
        c = Counter(f"{(e.get('tournament') or {}).get('category', {}).get('name')} | {(e.get('tournament') or {}).get('name')}"
                    f" | ut={(e.get('tournament') or {}).get('uniqueTournament', {}).get('id')}" for e in j.get("events", []))
        for k, v in sorted(c.items()):
            print("  SOFA", v, k)
    j = get("https://www.sofascore.com/api/v1/sport/basketball/scheduled-events/2026-11-04")
    print("  www sofascore events:", len((j or {}).get("events", [])))
    j = get("https://www.thesportsdb.com/api/v1/json/3/eventsday.php", {"d": "2026-11-04", "s": "Basketball"})
    if j:
        c = Counter(e.get("strLeague") for e in (j.get("events") or []))
        print("  TSDB", json.dumps(c.most_common(60)))
    get("https://v1.basketball.api-sports.io/status")
    j = get("https://www.fiba.basketball/en/api/v1/games", {"date": "2026-11-04"})
    get("https://fibalivestats.dcd.shared.geniussports.com/data/competition/42271.json")
    j = get("https://site.api.espn.com/apis/site/v2/sports/basketball/fiba/scoreboard", {"dates": "20261104"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
