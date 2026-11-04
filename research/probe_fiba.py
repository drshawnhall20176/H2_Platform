"""research/probe_fiba.py — does fiba.basketball carry usable game data for BCL / FIBA Europe Cup / EuroCup Women? (Nov 4)"""
import json
import re
import sys

import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}


def main() -> int:
    for u in ("https://www.fiba.basketball/en/api/v1/games?date=2026-11-04", "https://www.fiba.basketball/en/games",
              "https://www.fiba.basketball/en/events/basketball-champions-league-25-26/games",
              "https://www.fiba.basketball/en/events/fiba-europe-cup-25-26/games",
              "https://www.championsleague.basketball/en/games", "https://www.fibaeuropecup.com/games",
              "https://fibalivestats.dcd.shared.geniussports.com/data/competition/42271.json"):
        try:
            r = requests.get(u, headers=H, timeout=30)
        except Exception as exc:                                   # noqa: BLE001
            print("ERR", u, type(exc).__name__); continue
        t = r.text
        print(f"\n== {r.status_code} {len(t)} {u}")
        print("  title:", (re.search(r"<title>(.*?)</title>", t, re.S) or [None, ""])[1][:120])
        for kw in ("Champions League", "Europe Cup", "EuroCup Women", "Unicaja", "Tenerife", "homeTeam", "teamA", "scoreA", "gameDateTime"):
            print(f"  {kw!r}: {t.count(kw)}")
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', t, re.S)
        if m:
            print("  NEXT_DATA keys:", list(json.loads(m.group(1)).get("props", {}).get("pageProps", {}).keys())[:20])
        i = t.find("teamA")
        if i < 0:
            i = t.find("homeTeam")
        if i >= 0:
            print("  sample:", t[max(0, i - 300):i + 500].replace("\n", " "))
        if u.endswith(".json"):
            print("  body:", t[:500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
