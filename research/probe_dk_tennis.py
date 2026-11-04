"""research/probe_dk_tennis.py — how DraftKings names today's tennis events vs what the Tennis Lab shows (Nov 4).
Read-only: tries DK's public navigation feeds, then prints the platform's TENNIS records for comparison."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
URLS = [
    "https://sportsbook-nash.draftkings.com/api/sportscontent/navigation/dkusnj/v2/nav/sports/6?format=json",
    "https://sportsbook-nash.draftkings.com/api/sportscontent/navigation/dkusnj/v1/nav/sports/6?format=json",
    "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusnj/v1/sports/6/leagues",
    "https://sportsbook-nash.draftkings.com/api/sportscontent/navigation/dkusnj/v2/nav/sports?format=json",
]


def walk(o, out):
    if isinstance(o, dict):
        n = o.get("name") or o.get("displayName")
        if n and ("leagueId" in o or "id" in o):
            out.append(str(n))
        for v in o.values():
            walk(v, out)
    elif isinstance(o, list):
        for v in o:
            walk(v, out)


def main() -> int:
    for u in URLS:
        try:
            r = requests.get(u, headers=H, timeout=30)
            print(f"\n== {u} -> {r.status_code} {len(r.content)} bytes")
            if r.ok:
                names = []
                walk(r.json(), names)
                ten = [n for n in names if any(k in n.lower() for k in ("atp", "wta", "challenger", "itf", "utr", "tennis"))]
                print(json.dumps(sorted(set(ten or names))[:400], indent=0))
        except Exception as exc:                                # noqa: BLE001
            print(f"== {u} -> {type(exc).__name__}: {exc}")
    import model_store as MS
    lo = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    print("\n== Tennis Lab records (upcoming)")
    for p in sorted(MS.load_game_picks("TENNIS"), key=lambda x: str(x.get("kickoff"))):
        if str(p.get("kickoff")) < lo:
            continue
        print(f"{str(p.get('kickoff'))[:16]} {str(p.get('tour')).upper():3s} {'espn' if p.get('source') == 'espn' else 'odds':4s} "
              f"{p.get('tournament')!r:40s} {p.get('round')!s:14s} {p['home']} vs {p['away']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
