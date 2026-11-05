"""research/probe_kbl_lnb.py — season history for Korea's KBL and France's LNB Elite? (Nov 5)"""
import json
import re
import sys

import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
     "Accept": "application/json, text/html"}


def main() -> int:
    for params in ({"fromDate": "20261001", "toDate": "20261105", "seasonGrade": "1"},
                   {"fromDate": "20251001", "toDate": "20260430", "seasonGrade": "1"}):
        try:
            r = requests.get("https://api.kbl.or.kr/match/list", params=params, headers=H, timeout=30)
            print("KBL", r.status_code, len(r.content), r.text[:600].replace("\n", " "))
        except Exception as e:                                     # noqa: BLE001
            print("KBL ERR", type(e).__name__, e)
    for u in ("https://www.lnb.fr/elite/calendrier", "https://www.lnb.fr/elite/resultats", "https://www.lnb.fr/elite",
              "https://api-prod.lnb.fr/match/getCalendar", "https://www.lnb.fr/api/calendar"):
        try:
            r = requests.get(u, headers=H, timeout=30)
            t = r.text
            print("LNB", r.status_code, len(t), u, "| next_data:", "__NEXT_DATA__" in t, "| api urls:",
                  sorted(set(re.findall(r"https://api[a-z\-\.]*lnb\.fr[^\"' ]{0,80}", t)))[:8],
                  "| scores:", len(re.findall(r"\b\d{2,3}\s*-\s*\d{2,3}\b", t)))
        except Exception as e:                                     # noqa: BLE001
            print("LNB ERR", type(e).__name__, u)
    return 0


if __name__ == "__main__":
    sys.exit(main())
