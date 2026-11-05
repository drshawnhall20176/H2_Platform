"""research/probe_leagues2.py — full team lists of the FIBA LiveStats competitions this season for the leagues DK lists
(Lithuania NKL, Estonia, Iceland, Bahrain, Qatar, ...), to tell the top men's division apart from youth / women's (Nov 5)."""
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

G = "https://fibalivestats.dcd.shared.geniussports.com/data/competition/{}.json"
WANT = {640, 202, 183, 114, 43, 161, 128, 609}


def one(cid):
    try:
        js = requests.get(G.format(cid), timeout=20).json()
    except Exception:                                           # noqa: BLE001
        return None
    if not isinstance(js, list) or not js or js[0].get("leagueId") not in WANT:
        return None
    if max(str(m.get("matchTime")) for m in js) < "2026-09-01":
        return None
    teams = sorted({m.get("homename") or "" for m in js} | {m.get("awayname") or "" for m in js})
    return (js[0]["leagueId"], cid, len(js), min(str(m.get("matchTime"))[:10] for m in js),
            max(str(m.get("matchTime"))[:10] for m in js), teams)


def main() -> int:
    with ThreadPoolExecutor(max_workers=32) as ex:
        found = sorted(x for x in ex.map(one, range(47000, 51000)) if x)
    for lg, cid, n, a, b, teams in found:
        print(f"G lg={lg} cid={cid} n={n} {a}..{b} | {' / '.join(t for t in teams if t)[:400]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
