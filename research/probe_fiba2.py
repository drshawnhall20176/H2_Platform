"""research/probe_fiba2.py — the shape of one game record on FIBA's competition pages, and which seasons exist (Nov 4)."""
import re
import sys

import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
URLS = ["https://www.championsleague.basketball/en/games",
        "https://www.fiba.basketball/en/events/fiba-europe-cup-25-26/games",
        "https://www.fiba.basketball/en/events/fiba-europe-cup-24-25/games",
        "https://www.fiba.basketball/en/events/basketball-champions-league-24-25/games",
        "https://www.fiba.basketball/en/events/eurocup-women-25-26/games",
        "https://www.fiba.basketball/en/events/euroleague-women-25-26/games",
        "https://www.championsleague.basketball/en/24-25/games"]


def main() -> int:
    for u in URLS:
        r = requests.get(u, headers=H, timeout=40)
        t = r.text.replace('\\"', '"')
        n = t.count('"gameDateTime"')
        print(f"\n== {r.status_code} {len(t)} games~{n} {u}")
        i = t.find('"gameDateTime"')
        if i >= 0 and u == URLS[0]:
            j = t.rfind("{", 0, i - 400)
            print("SAMPLE:", t[max(0, i - 1500):i + 1500])
        if i >= 0:
            dates = sorted(set(re.findall(r'"gameDateTime":"(\d{4}-\d\d-\d\d)', t)))
            print("  dates:", dates[:3], "...", dates[-3:], len(dates))
            print("  status counts:", {k: t.count(f'"statusCode":"{k}"') for k in ("VALID", "FINAL", "LIVE", "SCHEDULED")},
                  "scores:", len(re.findall(r'"teamAScore":\d+', t)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
