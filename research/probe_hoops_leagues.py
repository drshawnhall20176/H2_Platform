"""research/probe_hoops_leagues.py — sources for EuroCup, Basketball Champions League and FIBA (Nov 4). Read-only."""
import os
import sys

import requests

H = {"User-Agent": "Mozilla/5.0"}


def show(u, params=None, n=220):
    try:
        r = requests.get(u, params=params or {}, timeout=30, headers=H)
        print(r.status_code, len(r.content), u, r.text[:n].replace("\n", " "))
        return r
    except Exception as exc:                                       # noqa: BLE001
        print("ERR", type(exc).__name__, u)


def main() -> int:
    show("https://api-live.euroleague.net/v2/competitions/U/seasons/U2025/games")
    show("https://feeds.incrowdsports.com/provider/euroleague-feeds/v2/competitions/U/seasons/U2025/games")
    for slug in ("fiba", "fiba-champions-league", "champions-league", "eurocup", "fiba-world-cup-qualifiers",
                 "fiba-americup", "fiba-eurobasket", "bcl", "basketball-champions-league", "liga-acb", "lega-basket",
                 "bbl", "lnb", "turkish-bsl", "vtb", "aba", "gbl", "nbl-nz", "cba", "kbl", "pba", "bsn"):
        show(f"https://site.api.espn.com/apis/site/v2/sports/basketball/{slug}/scoreboard", n=120)
    for u in ("https://www.championsleague.basketball/api/games", "https://api.championsleague.basketball/v1/games",
              "https://www.fiba.basketball/en/api/games", "https://digital-api.fiba.basketball/hapi/getgdapgamesoverview"):
        show(u, n=120)
    key = os.environ.get("ODDS_API_KEY")
    if key:
        r = requests.get("https://api.the-odds-api.com/v4/sports", params={"apiKey": key, "all": "true"}, timeout=30)
        print("odds-api basketball keys:", sorted(s["key"] for s in r.json() if s.get("group") == "Basketball"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
