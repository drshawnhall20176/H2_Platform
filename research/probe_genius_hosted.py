"""research/probe_genius_hosted.py — full-season schedules/results on Genius Sports' hosted pages? (Nov 5)"""
import re
import sys

import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}


def show(u, n=300):
    try:
        r = requests.get(u, headers=H, timeout=30)
        t = r.text
        ids = sorted(set(re.findall(r"/match/(\d{6,8})", t)))
        dates = sorted(set(re.findall(r"20\d\d-\d\d-\d\d|\d\d/\d\d/20\d\d|\b\d{1,2} [A-Z][a-z]{2} 20\d\d", t)))
        print(f"{r.status_code} {len(t):>8} match-ids={len(ids)} dates={len(dates)} {dates[:2]}..{dates[-2:]} {u}")
        return r
    except Exception as e:                                         # noqa: BLE001
        print("ERR", type(e).__name__, u)


def main() -> int:
    for cid in (49833, 50172, 49981):     # NKL, Bahrain, Estonia (league ids 640, 202, 183)
        for code in ("FIBA", "NKL", "LKL", "EST", "BAH", "en"):
            show(f"https://hosted.dcd.shared.geniussports.com/{code}/en/competition/{cid}/schedule")
        show(f"https://fibalivestats.dcd.shared.geniussports.com/u/FIBA/{cid}/schedule.html")
        show(f"https://www.fibalivestats.com/u/FIBA/{cid}/schedule.html")
    r = requests.get("https://fibalivestats.dcd.shared.geniussports.com/data/competition/49833.json", headers=H, timeout=30)
    js = r.json()
    print("competition json keys:", sorted(js[0].keys()), "matches:", len(js))
    mid = js[0]["matchId"]
    r = requests.get(f"https://fibalivestats.dcd.shared.geniussports.com/data/{mid}/data.json", headers=H, timeout=30)
    print("match data.json", r.status_code, len(r.content), list((r.json() if r.ok else {}).keys())[:30])
    return 0


if __name__ == "__main__":
    sys.exit(main())
