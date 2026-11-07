"""
research/blowout_study.py — do NBA blowouts move player output the way bettors think? (Nov 7)

Nov 6: a ticket built on a blowout script (San Antonio by 15: Kings starter Unders, Spurs bench Overs) won while every
leg on its own was a coin flip. Questions:
  1. In games decided by 15+, how far do bench players beat, and starters fall short of, their own recent average
     (points and minutes)? Winners vs losers.
  2. Can a blowout be seen coming -- how often does a game finish 15+ apart, by the pre-game spread?
  3. So: in games with a big pre-game spread, do bench players beat their average more often than in close-spread
     games? (That is the bet: it has to work from what's known before tip, not from the final score.)
Data: ESPN game packages (box score with starter flags, final score, pre-game spread), 2025-26 season and 2026-27 to
date, regular season. Baseline = the player's average over his previous 10+ games this season.
"""
from __future__ import annotations

import os
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import nba_engine as N  # noqa: E402

SEASONS = ((date(2025, 10, 21), date(2026, 4, 12)), (date(2026, 10, 20), date.today() - timedelta(days=1)))


def game_ids():
    ids = []
    for a, b in SEASONS:
        d = a
        while d <= b:
            try:
                for g in N.get_schedule(d.isoformat()):
                    gid = g.get("gameId") or g.get("game_id") or g.get("id")
                    if gid:
                        ids.append((str(gid), d.isoformat()))
            except Exception:
                pass
            d += timedelta(days=1)
    return ids


def _f(v):
    try:
        if isinstance(v, str) and ":" in v:
            m, s = v.split(":")
            return float(m) + float(s) / 60
        return float(v)
    except (TypeError, ValueError):
        return None


def package(gid):
    data = N._get_json_cached(N.CDN_API, params={"xhr": "1", "gameId": gid}) or {}
    gp = data.get("gamepackageJSON") or {}
    comp = ((gp.get("header") or {}).get("competitions") or [{}])[0]
    if not (comp.get("status") or {}).get("type", {}).get("completed"):
        return None
    teams = {}
    for c in comp.get("competitors") or []:
        teams[str(c.get("id"))] = {"home": c.get("homeAway") == "home", "score": _f(c.get("score"))}
    spread = None
    for pc in gp.get("pickcenter") or []:
        if pc.get("spread") is not None:
            spread = _f(pc["spread"])               # home team's spread (negative = home favored)
            break
    players = []
    for grp in (gp.get("boxscore") or {}).get("players") or []:
        tid = str((grp.get("team") or {}).get("id"))
        for sg in grp.get("statistics") or []:
            names = sg.get("names") or []
            for a in sg.get("athletes") or []:
                if a.get("didNotPlay") or not a.get("stats"):
                    continue
                row = dict(zip(names, a["stats"]))
                mn, pts = _f(row.get("MIN")), _f(row.get("PTS"))
                if mn is None or pts is None or mn <= 0:
                    continue
                players.append({"pid": (a.get("athlete") or {}).get("id"), "team": tid, "starter": bool(a.get("starter")),
                                "min": mn, "pts": pts})
    if len(teams) != 2 or not players:
        return None
    return {"teams": teams, "spread": spread, "players": players}


def main() -> int:
    ids = game_ids()
    print(f"{len(ids)} games scheduled")
    with ThreadPoolExecutor(max_workers=8) as ex:
        packs = list(ex.map(lambda t: (t[1], package(t[0])), ids))
    games = sorted([(d, p) for d, p in packs if p], key=lambda x: x[0])
    print(f"{len(games)} completed games with box scores; spreads on {sum(1 for _, p in games if p['spread'] is not None)}")
    hist = defaultdict(list)                       # pid -> [(min, pts)] earlier games
    rows = []
    for d, p in games:
        sc = {t: v["score"] for t, v in p["teams"].items()}
        (t1, s1), (t2, s2) = list(sc.items())
        margin = abs((s1 or 0) - (s2 or 0))
        winner = t1 if (s1 or 0) > (s2 or 0) else t2
        home = next(t for t, v in p["teams"].items() if v["home"])
        sp = p["spread"]
        fav = None if sp is None or sp == 0 else (home if sp < 0 else next(t for t in sc if t != home))
        for pl in p["players"]:
            h = hist[pl["pid"]]
            if len(h) >= 10:
                bm = statistics.mean(x[0] for x in h[-15:])
                bp = statistics.mean(x[1] for x in h[-15:])
                rows.append({"margin": margin, "won": pl["team"] == winner, "starter": pl["starter"], "dmin": pl["min"] - bm,
                             "dpts": pl["pts"] - bp, "beat": pl["pts"] > bp, "base_min": bm, "abs_spread": None if sp is None else abs(sp),
                             "fav": None if fav is None else pl["team"] == fav, "season": d[:4] if d[5:7] >= "10" else str(int(d[:4]) - 1)})
            h.append((pl["min"], pl["pts"]))
    print(f"{len(rows)} player-games with a 10-game baseline")
    print("```")
    print("## 1. By final margin (what happened)")
    for lo, hi in ((0, 6), (6, 11), (11, 15), (15, 21), (21, 99)):
        g = [r for r in rows if lo <= r["margin"] < hi]
        for role, f in (("starters", lambda r: r["starter"]), ("bench", lambda r: not r["starter"] and r["base_min"] >= 12)):
            gg = [r for r in g if f(r)]
            if gg:
                print(f"margin {lo:>2}-{hi:<2} {role:8s} n={len(gg):5d} minutes {statistics.mean(r['dmin'] for r in gg):+5.1f}"
                      f"  points {statistics.mean(r['dpts'] for r in gg):+5.1f}  beat own avg {sum(r['beat'] for r in gg) / len(gg):.1%}")
    print("-- 15+ margins, winners vs losers --")
    g = [r for r in rows if r["margin"] >= 15]
    for won in (True, False):
        for role, f in (("starters", lambda r: r["starter"]), ("bench", lambda r: not r["starter"] and r["base_min"] >= 12)):
            gg = [r for r in g if r["won"] == won and f(r)]
            if gg:
                print(f"  {'winner' if won else 'loser '} {role:8s} n={len(gg):5d} minutes {statistics.mean(r['dmin'] for r in gg):+5.1f}"
                      f"  points {statistics.mean(r['dpts'] for r in gg):+5.1f}  beat avg {sum(r['beat'] for r in gg) / len(gg):.1%}")
    print("## 2. Seeing it coming: how often a game ends 15+ apart, by pre-game spread")
    gm = []
    for d, p in games:
        sc = [v["score"] or 0 for v in p["teams"].values()]
        if p["spread"] is not None:
            gm.append((abs(p["spread"]), abs(sc[0] - sc[1])))
    for lo, hi in ((0, 3.5), (3.5, 6.5), (6.5, 9.5), (9.5, 12.5), (12.5, 99)):
        g = [m for s, m in gm if lo <= s < hi]
        if g:
            print(f"spread {lo:>4}-{hi:<4}: games {len(g):4d}  ended 15+ apart {sum(1 for m in g if m >= 15) / len(g):.1%}"
                  f"  20+ {sum(1 for m in g if m >= 20) / len(g):.1%}")
    print("## 3. The bet: by PRE-GAME spread (known before tip)")
    for lo, hi in ((0, 6.5), (6.5, 9.5), (9.5, 12.5), (12.5, 99)):
        g = [r for r in rows if r["abs_spread"] is not None and lo <= r["abs_spread"] < hi]
        for role, f in (("fav bench", lambda r: r["fav"] and not r["starter"] and r["base_min"] >= 12),
                        ("dog starters", lambda r: r["fav"] is False and r["starter"]),
                        ("fav starters", lambda r: r["fav"] and r["starter"]),
                        ("dog bench", lambda r: r["fav"] is False and not r["starter"] and r["base_min"] >= 12)):
            gg = [r for r in g if f(r)]
            if gg:
                print(f"spread {lo:>4}-{hi:<4} {role:12s} n={len(gg):5d} minutes {statistics.mean(r['dmin'] for r in gg):+5.1f}"
                      f"  points {statistics.mean(r['dpts'] for r in gg):+5.1f}  beat own avg {sum(r['beat'] for r in gg) / len(gg):.1%}")
    print("-- spread 9.5+, by season --")
    for s in sorted({r["season"] for r in rows}):
        g = [r for r in rows if r["season"] == s and r["abs_spread"] is not None and r["abs_spread"] >= 9.5]
        for role, f in (("fav bench", lambda r: r["fav"] and not r["starter"] and r["base_min"] >= 12),
                        ("dog starters", lambda r: r["fav"] is False and r["starter"])):
            gg = [r for r in g if f(r)]
            if gg:
                print(f"  {s} {role:12s} n={len(gg):4d} points {statistics.mean(r['dpts'] for r in gg):+5.1f}  beat avg {sum(r['beat'] for r in gg) / len(gg):.1%}")
    print("```")
    return 0


if __name__ == "__main__":
    sys.exit(main())
