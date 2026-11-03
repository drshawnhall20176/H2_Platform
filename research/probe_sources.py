"""research/probe_sources.py — which tennis / international basketball data sources answer from GitHub Actions (Nov 3)."""
from __future__ import annotations

import os
import sys

import requests

URLS = [
    "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/atp_matches_2024.csv",
    "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/atp_matches_2025.csv",
    "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master/wta_matches_2025.csv",
    "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/atp_matches_qual_chall_2025.csv",
    "http://www.tennis-data.co.uk/2025/2025.xlsx",
    "http://www.tennis-data.co.uk/2026/2026.xlsx",
    "http://www.tennis-data.co.uk/2025w/2025.xlsx",
    "http://www.tennis-data.co.uk/2026w/2026.xlsx",
    "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
    "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard",
    "https://api-live.euroleague.net/v1/results?seasonCode=E2025",
    "https://api-live.euroleague.net/v2/competitions/E/seasons/E2025/games",
    "https://feeds.incrowdsports.com/provider/euroleague-feeds/v2/competitions/E/seasons/E2025/games",
    "https://site.api.espn.com/apis/site/v2/sports/basketball/fiba/scoreboard",
    "https://www.football-data.co.uk/",
]


def main() -> int:
    for u in URLS:
        try:
            r = requests.get(u, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
            head = r.content[:160].replace(b"\n", b" ")
            print(f"{r.status_code} {len(r.content):>9} {u}\n      {head!r}")
        except Exception as exc:                                   # noqa: BLE001
            print(f"ERR {type(exc).__name__}: {exc} {u}")
    key = os.environ.get("ODDS_API_KEY")
    if key:
        r = requests.get("https://api.the-odds-api.com/v4/sports", params={"apiKey": key, "all": "true"}, timeout=25)
        for s in r.json():
            if s.get("group") in ("Tennis", "Basketball"):
                print(f"odds-api {s['key']:45s} active={s.get('active')} {s.get('title')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
