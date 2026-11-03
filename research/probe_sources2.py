"""research/probe_sources2.py — second probe: tennis history, ESPN tennis by date, NBL results, historical odds (Nov 3)."""
from __future__ import annotations

import json
import os
import sys

import requests

H = {"User-Agent": "Mozilla/5.0"}


def get(u, **kw):
    try:
        r = requests.get(u, timeout=30, headers=H, **kw)
        return r
    except Exception as exc:                                       # noqa: BLE001
        print(f"ERR {type(exc).__name__} {u}")
        return None


def main() -> int:
    for u in ["https://api.github.com/repos/JeffSackmann/tennis_atp",
              "https://api.github.com/repos/JeffSackmann/tennis_atp/contents/",
              "https://github.com/JeffSackmann/tennis_atp"]:
        r = get(u)
        if r is not None:
            print(r.status_code, u, r.text[:300].replace("\n", " "))
    # ESPN tennis on a past date
    r = get("https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard", params={"dates": "20251015"})
    if r is not None and r.ok:
        j = r.json()
        evs = j.get("events") or []
        print("ESPN atp 20251015 events:", len(evs))
        for ev in evs[:3]:
            print("  ", ev.get("name"), "| venue:", (ev.get("venue") or {}).get("fullName"),
                  "| groupings:", len(ev.get("groupings") or []))
            for g in (ev.get("groupings") or [])[:1]:
                print("    grouping:", (g.get("grouping") or {}).get("displayName"), "comps:", len(g.get("competitions") or []))
                for c in (g.get("competitions") or [])[:2]:
                    print("     ", json.dumps({k: c.get(k) for k in ("date", "status", "round", "venue")}, default=str)[:300])
                    for cp in c.get("competitors") or []:
                        print("        ", (cp.get("athlete") or {}).get("displayName"), cp.get("winner"),
                              [ls.get("value") for ls in cp.get("linescores") or []])
    for u in ["https://site.api.espn.com/apis/site/v2/sports/basketball/nbl/scoreboard",
              "https://site.api.espn.com/apis/site/v2/sports/basketball/australian-nbl/scoreboard",
              "https://apicdn.nbl.com.au/nbl/custom/api/v1/games",
              "https://api-live.euroleague.net/v2/competitions/E/seasons/E2022/games"]:
        r = get(u)
        if r is not None:
            print(r.status_code, len(r.content), u, r.text[:200].replace("\n", " "))
    key = os.environ.get("ODDS_API_KEY")
    if key:
        r = get("https://api.the-odds-api.com/v4/historical/sports/basketball_euroleague/odds",
                params={"apiKey": key, "regions": "us,eu", "markets": "h2h,spreads,totals", "date": "2025-10-15T12:00:00Z"})
        if r is not None:
            print("historical euroleague:", r.status_code, r.text[:400].replace("\n", " "),
                  "| remaining:", r.headers.get("x-requests-remaining"), "used:", r.headers.get("x-requests-last"))
        r = get("https://api.the-odds-api.com/v4/sports/tennis_atp_paris_masters/odds",
                params={"apiKey": key, "regions": "us", "markets": "h2h,spreads,totals"})
        if r is not None and r.ok:
            evs = r.json()
            print("paris masters events:", len(evs))
            for ev in evs[:2]:
                print("  ", ev["home_team"], "v", ev["away_team"],
                      [(b["key"], [m["key"] for m in b["markets"]]) for b in ev.get("bookmakers", [])][:4])
        r = get("https://api.the-odds-api.com/v4/sports/basketball_euroleague/events/", params={"apiKey": key})
        if r is not None and r.ok and r.json():
            eid = r.json()[0]["id"]
            r2 = get(f"https://api.the-odds-api.com/v4/sports/basketball_euroleague/events/{eid}/markets",
                     params={"apiKey": key, "regions": "us"})
            print("euroleague markets:", r2.status_code if r2 is not None else None, (r2.text[:400] if r2 is not None else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
