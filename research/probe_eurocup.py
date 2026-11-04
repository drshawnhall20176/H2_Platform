"""research/probe_eurocup.py — fields of an upcoming EuroCup game (Nov 4). Read-only."""
import json
import sys

import requests


def main() -> int:
    d = requests.get("https://api-live.euroleague.net/v2/competitions/U/seasons/U2026/games", timeout=30).json()["data"]
    up = [g for g in d if not g.get("played")]
    pl = [g for g in d if g.get("played")]
    print("played", len(pl), "upcoming", len(up))
    g = sorted(up, key=lambda x: str(x.get("utcDate") or x.get("date")))[0]
    keep = {k: g.get(k) for k in ("identifier", "date", "utcDate", "localDate", "played", "round", "group", "phaseType")}
    keep["local"] = {"club": (g.get("local") or {}).get("club", {}).get("name"), "score": (g.get("local") or {}).get("score")}
    keep["road"] = {"club": (g.get("road") or {}).get("club", {}).get("name")}
    print(json.dumps(keep, default=str)[:900])
    print("keys:", sorted(g.keys()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
