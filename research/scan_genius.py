"""research/scan_genius.py — which competitions FIBA LiveStats (Genius Sports) carries this season (Nov 5).
Scans competition ids, keeps those with games between Sept 2026 and Jan 2027, and prints each with sample team names
so the league can be identified. Read-only."""
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import requests

URL = "https://fibalivestats.dcd.shared.geniussports.com/data/competition/{}.json"
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0"


def one(cid):
    try:
        r = S.get(URL.format(cid), timeout=20)
        if not r.ok or len(r.content) < 50:
            return None
        js = r.json()
    except Exception:                                           # noqa: BLE001
        return None
    if not isinstance(js, list) or not js:
        return None
    times = sorted(str(m.get("matchTime") or "") for m in js)
    if not times or times[-1] < "2026-09-01" or times[0] > "2027-01-31":
        return None
    teams = Counter()
    for m in js:
        teams[m.get("homename") or ""] += 1
    done = sum(1 for m in js if str(m.get("matchStatus")).upper() == "COMPLETE")
    return {"cid": cid, "league": js[0].get("leagueId"), "n": len(js), "done": done, "first": times[0][:10],
            "last": times[-1][:10], "teams": [t for t, _ in teams.most_common(8)]}


def main() -> int:
    lo, hi = int(os.environ.get("LO", "41000")), int(os.environ.get("HI", "46000"))
    with ThreadPoolExecutor(max_workers=32) as ex:
        found = [x for x in ex.map(one, range(lo, hi)) if x]
    for f in sorted(found, key=lambda x: (x["league"] or 0, x["cid"])):
        print(json.dumps(f, ensure_ascii=False))
    print(f"{len(found)} competitions with games Sep 2026 - Jan 2027 in ids {lo}-{hi}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
