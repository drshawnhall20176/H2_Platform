"""research/backtest_backup_goalie.py — do skaters score more against a BACKUP goalie? (Nov 5) Read-only.
NHL's open stats feed (api-web.nhle.com): every regular-season game 2024-25 and 2025-26 (+ this season so far). A team's
"usual" goalie = the one with the most starts over its previous 10 games. For each game, the attacking team's goals
and shots against the opponent's usual goalie vs a backup, relative to the attacking team's own recent average."""
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import requests

API = "https://api-web.nhle.com/v1"
S = requests.Session()


def get(u):
    try:
        r = S.get(u, timeout=30)
        return r.json() if r.ok else None
    except Exception:                                           # noqa: BLE001
        return None


def game_ids():
    ids = set()
    d = date(2024, 10, 4)
    days = []
    while d < date(2026, 11, 4):
        if d.month not in (7, 8, 9) or d >= date(2026, 10, 1):
            days.append(d)
        d += timedelta(days=7)
    with ThreadPoolExecutor(max_workers=16) as ex:
        for js in ex.map(lambda x: get(f"{API}/schedule/{x.isoformat()}"), days):
            for wk in (js or {}).get("gameWeek") or []:
                for g in wk.get("games") or []:
                    if g.get("gameType") == 2:
                        ids.add(g["id"])
    return sorted(ids)


def box(gid):
    js = get(f"{API}/gamecenter/{gid}/boxscore")
    if not js or js.get("gameState") not in ("OFF", "FINAL"):
        return None
    out = {"id": gid, "date": js.get("gameDate")}
    for side in ("homeTeam", "awayTeam"):
        t = js.get(side) or {}
        stats = ((js.get("playerByGameStats") or {}).get(side) or {})
        goalies = stats.get("goalies") or []
        start = next((g for g in goalies if g.get("starter")), goalies[0] if goalies else None)
        out[side] = {"team": t.get("abbrev"), "goals": t.get("score"), "sog": t.get("sog"),
                     "goalie": (start or {}).get("playerId")}
    return out


def main() -> int:
    ids = game_ids()
    print("games:", len(ids))
    rr = S.get(f"{API}/gamecenter/{ids[0]}/boxscore", timeout=30)
    print("DEBUG status:", rr.status_code, rr.url, rr.text[:200].replace("\n", " "))
    js = get(f"{API}/gamecenter/{ids[0]}/boxscore") or {}
    print("DEBUG keys:", sorted(js.keys())[:40], "state:", js.get("gameState"))
    pb = js.get("playerByGameStats") or {}
    print("DEBUG pbgs:", {k: sorted((v or {}).keys()) for k, v in pb.items()})
    gl = ((pb.get("homeTeam") or {}).get("goalies") or [{}])[0]
    print("DEBUG goalie:", sorted(gl.keys()), "| team:", {k: (js.get("homeTeam") or {}).get(k) for k in ("abbrev", "score", "sog")})
    with ThreadPoolExecutor(max_workers=16) as ex:
        games = [g for g in ex.map(box, ids) if g and g.get("homeTeam", {}).get("goalie")]
    games.sort(key=lambda g: (g["date"], g["id"]))
    starts = defaultdict(list)       # team -> [goalie ids in order]
    scored = defaultdict(list)       # team -> [(goals, sog)]
    res = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0])
    for g in games:
        for att, dfd in (("homeTeam", "awayTeam"), ("awayTeam", "homeTeam")):
            a, d = g[att], g[dfd]
            prev = starts[d["team"]][-10:]
            mine = scored[a["team"]][-10:]
            if len(prev) >= 6 and len(mine) >= 6 and a["goals"] is not None:
                usual = max(set(prev), key=prev.count)
                key = "vs usual goalie" if d["goalie"] == usual else "vs backup goalie"
                r = res[key]
                r[0] += a["goals"]
                r[1] += sum(x for x, _ in mine) / len(mine)
                r[2] += a["sog"] or 0
                r[3] += sum(y for _, y in mine) / len(mine)
                r[4] += 1
        for side in ("homeTeam", "awayTeam"):
            starts[g[side]["team"]].append(g[side]["goalie"])
            scored[g[side]["team"]].append((g[side]["goals"] or 0, g[side]["sog"] or 0))
    for k, (gl, gx, sg, sx, n) in res.items():
        print(f"{k:18s} n={n:5d}  goals vs own average {gl / gx - 1:+.1%}   shots {sg / sx - 1:+.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
