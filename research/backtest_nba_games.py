"""research/backtest_nba_games.py — can an opponent-adjusted ratings model beat NBA spreads / totals?

ESPN scoreboards (one request per date) give each game's final score and the line ESPN carried (spread +
over/under). For every game, offense / defense ratings + home court are fitted (ridge, recency-weighted) on the
season's games BEFORE that date (last season's games count at reduced weight early on), then compared with the line.
Prints ATS / O-U hit rates when the model is 2+, 4+, 6+ points off (52.4% breaks even at -110) and MAE vs the line."""
import math
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import postgame as PG  # noqa: E402

URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"


def num(x):
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def games_between(a: date, b: date):
    out = []
    d = a
    while d <= b:
        data = PG._http(URL, {"dates": d.strftime("%Y%m%d"), "limit": 50}) or {}
        for ev in data.get("events") or []:
            for c in ev.get("competitions") or []:
                if not ((c.get("status") or {}).get("type") or {}).get("completed"):
                    continue
                if (ev.get("season") or {}).get("type") not in (2, None):
                    continue                      # regular season only
                side = {t.get("homeAway"): t for t in c.get("competitors") or []}
                if "home" not in side or "away" not in side:
                    continue
                out.append({"id": ev.get("id"), "date": d, "home": side["home"]["team"]["abbreviation"], "away": side["away"]["team"]["abbreviation"],
                            "hp": num(side["home"].get("score")), "ap": num(side["away"].get("score")),
                            "line": None, "total": None, "neutral": bool(c.get("neutralSite"))})
        d += timedelta(days=1)
    from concurrent.futures import ThreadPoolExecutor

    def add_line(g):
        data = PG._http(SUMMARY, {"event": g["id"]}) or {}
        pc = data.get("pickcenter") or []
        if pc:
            sp, ou = num(pc[0].get("spread")), num(pc[0].get("overUnder"))
            g["line"] = None if sp is None else -sp          # ESPN's spread is the home team's (negative = favored)
            g["total"] = ou
        return g
    with ThreadPoolExecutor(max_workers=8) as ex:
        out = list(ex.map(add_line, out))
    return out


def ratings(games, today, lam, half_life):
    teams = sorted({g["home"] for g in games} | {g["away"] for g in games})
    ix = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    X, y, W = [], [], []
    for g in games:
        w = 0.5 ** ((today - g["date"]).days / half_life) * g.get("w", 1.0)
        h = 0.0 if g["neutral"] else 1.0
        for t, o, pts, hh in ((g["home"], g["away"], g["hp"], h), (g["away"], g["home"], g["ap"], -h)):
            x = np.zeros(2 * n + 1)
            x[ix[t]], x[n + ix[o]], x[2 * n] = 1, -1, 0.5 * hh
            X.append(x); y.append(pts); W.append(w)
    X, y, W = np.array(X), np.array(y, float), np.array(W)
    mu = np.average(y, weights=W)
    reg = np.eye(2 * n + 1) * lam
    reg[2 * n, 2 * n] = 0
    beta = np.linalg.solve((X * W[:, None]).T @ X + reg, (X * W[:, None]).T @ (y - mu))
    return mu, {t: beta[ix[t]] for t in teams}, {t: beta[n + ix[t]] for t in teams}, beta[2 * n]


last = games_between(date(2025, 10, 21), date(2026, 4, 12))
cur = games_between(date(2026, 10, 20), date.today() - timedelta(days=1))
print(f"games: 2025-26 {len(last)} (with a line: {sum(1 for g in last if g['line'] is not None)}), 2026-27 {len(cur)}")
res = defaultdict(list)
for season, prev in ((last, []), (cur, last)):
    dates = sorted({g["date"] for g in season})
    for d in dates:
        before = [g for g in season if g["date"] < d]
        if len(before) < 60 and not prev:
            continue
        pool = before + [dict(g, w=0.3) for g in prev[-300:]] if len(before) < 300 else before
        for lam in (3.0,):
            for hl in (30.0, 90.0):
                mu, off, de, hfa = ratings(pool, d, lam, hl)
                for g in (x for x in season if x["date"] == d):
                    if g["home"] not in off or g["away"] not in off or g["line"] is None:
                        continue
                    h = 0 if g["neutral"] else 0.5 * hfa
                    hp_, ap_ = mu + off[g["home"]] - de[g["away"]] + h, mu + off[g["away"]] - de[g["home"]] - h
                    res[f"ratings half-life {hl:g}d"].append((hp_ - ap_, hp_ + ap_, g["hp"] - g["ap"], g["hp"] + g["ap"],
                                                             g["line"], g["total"]))
for name, rs in res.items():
    out = [f"{name:24s} n{len(rs)} margin MAE {sum(abs(m - pm) for pm, _, m, _, _, _ in rs) / len(rs):.2f} "
           f"(line {sum(abs(m - lm) for _, _, m, _, lm, _ in rs) / len(rs):.2f})"]
    tt = [(pt, t, lt) for _, pt, _, t, _, lt in rs if lt]
    if tt:
        out.append(f"total MAE {sum(abs(t - pt) for pt, t, _ in tt) / len(tt):.2f} (line {sum(abs(t - lt) for _, t, lt in tt) / len(tt):.2f})")
    for thr in (2, 4, 6):
        a = [(1 if (m - lm) * (pm - lm) > 0 else 0) for pm, _, m, _, lm, _ in rs if abs(pm - lm) >= thr and m != lm]
        o = [(1 if (t - lt) * (pt - lt) > 0 else 0) for pt, t, lt in tt if abs(pt - lt) >= thr and t != lt]
        out.append(f"{thr}+: ATS {sum(a) / max(len(a), 1):.1%} n{len(a)} O/U {sum(o) / max(len(o), 1):.1%} n{len(o)}")
    print(" | ".join(out))
