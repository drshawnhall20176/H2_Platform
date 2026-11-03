"""research/probe_tennis_today.py — which tennis events and matches ESPN lists today (scheduled + live), Nov 3."""
import sys
from datetime import date

import requests


def main() -> int:
    for tour in ("atp", "wta"):
        j = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard",
                         params={"dates": date.today().strftime("%Y%m%d")}, timeout=30).json()
        for ev in j.get("events") or []:
            n = {"pre": 0, "in": 0, "post": 0}
            sample = []
            for g in ev.get("groupings") or []:
                if "singles" not in ((g.get("grouping") or {}).get("displayName") or "").lower():
                    continue
                for c in g.get("competitions") or []:
                    st = ((c.get("status") or {}).get("type") or {}).get("state")
                    n[st] = n.get(st, 0) + 1
                    if st in ("pre", "in") and len(sample) < 2:
                        sample.append(" vs ".join((cp.get("athlete") or {}).get("displayName", "?")
                                                  for cp in c.get("competitors") or []) + f" [{st} {c.get('date')}]")
            print(f"{tour.upper():3s} {ev.get('name')!r:45s} {n} {sample}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
