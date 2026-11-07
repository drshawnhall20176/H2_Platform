"""
research/script_study.py — game-script effects for every sport with player props (Nov 7).

Extends blowout_study.py (NBA, points only) to NBA, WNBA, NCAAMB, NFL, NCAAF and NHL, market by market:
  SHARES   how games finish (favorite blows it open / close / underdog blows it open) by pre-game strength
           (absolute spread; NHL: the favorite's no-vig moneyline chance)
  EFFECT   how often a player beats his own recent average, by group (role x stat) and how his team's game went,
           minus that group's overall rate; shrunk toward 0 by n/(n+K)
  HELD-OUT fit on one season, apply to the other: bucket player-games by the PRE-GAME predicted shift (shares x
           effects, centred) and report the actual beat rate -- the only test that matters for a bet.
Prints one JSON line per sport ("SCRIPTJSON {...}") for script_effects.py.
Run one sport by setting SPORT (wrappers script_study_<sport>.py).
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import requests

H = {"User-Agent": "Mozilla/5.0"}
Y = date.today() - timedelta(days=1)
K_SHRINK = 100

CFG = {
    "NBA": dict(path="basketball/nba", kind="hoops", seasons=((date(2025, 10, 21), date(2026, 4, 12)), (date(2026, 10, 20), Y)),
                close=6, blow=15, buckets=(0, 3.5, 6.5, 9.5, 12.5, 99), starter=26, bench=12, min_games=10),
    "WNBA": dict(path="basketball/wnba", kind="hoops", seasons=((date(2025, 5, 16), date(2025, 9, 12)), (date(2026, 5, 8), date(2026, 9, 15))),
                 close=6, blow=13, buckets=(0, 3.5, 6.5, 9.5, 99), starter=24, bench=10, min_games=8),
    "NCAAMB": dict(path="basketball/mens-college-basketball", kind="hoops", extra={"groups": "50", "limit": "400"},
                   seasons=((date(2025, 11, 3), date(2026, 3, 15)), (date(2026, 11, 2), Y)),
                   close=6, blow=15, buckets=(0, 4.5, 9.5, 14.5, 20.5, 99), starter=24, bench=10, min_games=5),
    "NFL": dict(path="football/nfl", kind="football", seasons=((date(2025, 9, 4), date(2026, 1, 4)), (date(2026, 9, 10), Y)),
                close=7, blow=17, buckets=(0, 3.5, 7.5, 10.5, 99), min_games=4),
    "NCAAF": dict(path="football/college-football", kind="football", extra={"groups": "80"},
                  seasons=((date(2025, 8, 23), date(2025, 12, 13)), (date(2026, 8, 29), Y)),
                  close=8, blow=21, buckets=(0, 7.5, 14.5, 21.5, 99), min_games=4),
    "NHL": dict(path="hockey/nhl", kind="hockey", seasons=((date(2025, 10, 7), date(2026, 4, 16)), (date(2026, 10, 7), Y)),
                close=1, blow=3, buckets=(0.5, 0.56, 0.62, 0.68, 1.01), min_games=10),
}


def _get(url, params):
    for _ in range(3):
        try:
            r = requests.get(url, params=params, headers=H, timeout=25)
            if r.status_code == 200:
                return r.json()
        except Exception:                                       # noqa: BLE001
            pass
    return None


def _f(v):
    try:
        if isinstance(v, str) and ":" in v:
            m, s = v.split(":")
            return float(m) + float(s) / 60
        if isinstance(v, str) and ("-" in v[1:] or "/" in v):
            return float(v.replace("/", "-").split("-")[0])
        return float(v)
    except (TypeError, ValueError):
        return None


def _ml_p(ml):
    ml = _f(ml)
    if ml is None:
        return None
    return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)


def event_ids(c):
    base = f"https://site.api.espn.com/apis/site/v2/sports/{c['path']}"
    days = []
    for a, b in c["seasons"]:
        d = a
        while d <= b:
            days.append(d)
            d += timedelta(days=1)
    out = {}

    def one(d):
        sb = _get(f"{base}/scoreboard", {"dates": d.strftime("%Y%m%d"), **c.get("extra", {})}) or {}
        return [(e["id"], (e.get("date") or "")[:10]) for e in sb.get("events") or []
                if ((e.get("status") or {}).get("type") or {}).get("completed")]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for lst in ex.map(one, days):
            for i, d in lst:
                out[i] = d
    return sorted(out.items(), key=lambda t: t[1])


def package(c, gid):
    base = f"https://site.api.espn.com/apis/site/v2/sports/{c['path']}"
    s = _get(f"{base}/summary", {"event": gid}) or {}
    comp = ((s.get("header") or {}).get("competitions") or [{}])[0]
    teams = {}
    for t in comp.get("competitors") or []:
        teams[str(t.get("id"))] = {"home": t.get("homeAway") == "home", "score": _f(t.get("score"))}
    if len(teams) != 2 or any(v["score"] is None for v in teams.values()):
        return None
    home = next((t for t, v in teams.items() if v["home"]), None)
    away = next((t for t in teams if t != home), None)
    fav, strength = None, None
    for pc in s.get("pickcenter") or []:
        ho, ao = pc.get("homeTeamOdds") or {}, pc.get("awayTeamOdds") or {}
        if c["kind"] == "hockey":
            ph, pa = _ml_p(ho.get("moneyLine")), _ml_p(ao.get("moneyLine"))
            if ph and pa:
                ph, pa = ph / (ph + pa), pa / (ph + pa)
                fav, strength = (home, ph) if ph >= pa else (away, pa)
                break
        elif pc.get("spread") is not None and _f(pc["spread"]) not in (None, 0.0):
            sp = _f(pc["spread"])                               # the home team's line
            fav = home if sp < 0 else away
            if ho.get("favorite") is True:
                fav = home
            elif ao.get("favorite") is True:
                fav = away
            strength = abs(sp)
            break
    players = defaultdict(dict)                                 # pid -> {team, stats...}
    for grp in (s.get("boxscore") or {}).get("players") or []:
        tid = str((grp.get("team") or {}).get("id"))
        for sg in grp.get("statistics") or []:
            keys = sg.get("keys") or []
            cat = sg.get("name") or "box"
            for a in sg.get("athletes") or []:
                if a.get("didNotPlay") or not a.get("stats"):
                    continue
                pid = (a.get("athlete") or {}).get("id")
                if not pid:
                    continue
                row = dict(zip(keys, a["stats"]))
                p = players[pid]
                p["team"] = tid
                p["pos"] = ((a.get("athlete") or {}).get("position") or {}).get("abbreviation")
                for k, v in row.items():
                    if k == "completions/passingAttempts" and isinstance(v, str) and "/" in v:
                        p["passingAttempts"] = _f(v.split("/")[1])
                    elif k in ("threePointFieldGoalsMade-threePointFieldGoalsAttempted",):
                        p["threes"] = _f(v)
                    else:
                        p[f"{cat}.{k}" if k in ("interceptions", "sacks") else k] = _f(v)
    if not players:
        return None
    return {"teams": teams, "fav": fav, "strength": strength, "players": dict(players)}


# ---------------------------------------------------------------- groups: (name, eligible(baseline, raw history), value(stats))
def groups(c):
    if c["kind"] == "hoops":
        out = []
        for role, lo, hi in (("starter", c["starter"], 99), ("bench", c["bench"], c["starter"])):
            for stat, key in (("points", "points"), ("rebounds", "rebounds"), ("assists", "assists"), ("threes", "threes")):
                out.append((f"{role}:{stat}", (lambda lo, hi: lambda b: lo <= (b.get("minutes") or 0) < hi)(lo, hi), key))
        return out
    if c["kind"] == "football":
        return [("pass_yds", lambda b: (b.get("passingAttempts") or 0) >= 15, "passingYards"),
                ("pass_att", lambda b: (b.get("passingAttempts") or 0) >= 15, "passingAttempts"),
                ("rush_yds", lambda b: (b.get("rushingAttempts") or 0) >= 8 and (b.get("passingAttempts") or 0) < 5, "rushingYards"),
                ("rec_yds", lambda b: (b.get("receptions") or 0) >= 2.5, "receivingYards"),
                ("receptions", lambda b: (b.get("receptions") or 0) >= 2.5, "receptions"),
                ("tackles", lambda b: (b.get("totalTackles") or 0) >= 4, "totalTackles")]
    return [("shots", lambda b: (b.get("timeOnIce") or 0) >= 12 and b.get("_g") is None, "shotsTotal"),
            ("points", lambda b: (b.get("timeOnIce") or 0) >= 12 and b.get("_g") is None, "_pts"),
            ("blocks", lambda b: (b.get("timeOnIce") or 0) >= 12 and b.get("_g") is None, "blockedShots"),
            ("saves", lambda b: b.get("_g") is not None and (b.get("timeOnIce") or 0) >= 40, "saves")]


def state(margin_for_team, c):
    m = abs(margin_for_team)
    if m <= c["close"]:
        return "close"
    if m < c["blow"]:
        return "mid"
    return "blow_win" if margin_for_team > 0 else "blow_lose"


def bucket(c, strength):
    b = c["buckets"]
    for lo, hi in zip(b[:-1], b[1:]):
        if lo <= strength < hi:
            return (lo, hi)
    return (b[-2], b[-1])


def build_rows(c, games):
    hist = defaultdict(list)
    gs = groups(c)
    rows = []
    for gi, (d, p) in enumerate(games):
        sc = {t: v["score"] for t, v in p["teams"].items()}
        for pid, st in p["players"].items():
            if c["kind"] == "hockey":
                if st.get("saves") is not None or st.get("pos") == "G":
                    st["_g"] = 1
                st["_pts"] = (st.get("goals") or 0) + (st.get("assists") or 0)
            if c["kind"] == "football":
                for k in ("passingYards", "passingAttempts", "rushingYards", "rushingAttempts", "receivingYards", "receptions", "totalTackles"):
                    st.setdefault(k, 0.0)
            h = hist[pid]
            if len(h) >= c["min_games"]:
                recent = h[-15:]
                base = {}
                for k in set().union(*[set(x) for x in recent]):
                    vals = [x.get(k) for x in recent if isinstance(x.get(k), (int, float))]
                    if vals:
                        base[k] = statistics.mean(vals)
                base["_g"] = 1 if any(x.get("_g") for x in recent) else None
                tm = st.get("team")
                opp = next((t for t in sc if t != tm), None)
                if opp is not None:
                    mg = sc[tm] - sc[opp]
                    for name, ok, key in gs:
                        if ok(base) and base.get(key) is not None and st.get(key) is not None:
                            rows.append({"g": name, "state": state(mg, c), "beat": st[key] > base[key], "season": d[:4] if d[5:7] >= "07" else str(int(d[:4]) - 1),
                                         "is_fav": None if p["fav"] is None else tm == p["fav"], "strength": p["strength"], "gi": gi})
            h.append({k: v for k, v in st.items() if isinstance(v, (int, float))})
    return rows


def shares_of(c, games):
    out = {}
    for d, p in games:
        if p["fav"] is None or p["strength"] is None:
            continue
        fav = p["fav"]
        dog = next(t for t in p["teams"] if t != fav)
        fm = p["teams"][fav]["score"] - p["teams"][dog]["score"]
        out.setdefault(bucket(c, p["strength"]), []).append(fm)
    res = []
    for (lo, hi), ms in sorted(out.items()):
        n = len(ms)
        res.append([lo, hi, round(sum(m >= c["blow"] for m in ms) / n, 3), round(sum(abs(m) <= c["close"] for m in ms) / n, 3),
                    round(sum(m <= -c["blow"] for m in ms) / n, 3), n])
    return res


def effects_of(rows):
    by = defaultdict(list)
    for r in rows:
        by[r["g"]].append(r)
    eff, base, ns = {}, {}, {}
    for g, rs in by.items():
        b = sum(r["beat"] for r in rs) / len(rs)
        base[g] = round(b, 3)
        ns[g] = len(rs)
        eff[g] = {}
        for s in ("close", "mid", "blow_win", "blow_lose"):
            ss = [r for r in rs if r["state"] == s]
            if ss:
                raw = sum(r["beat"] for r in ss) / len(ss) - b
                eff[g][s] = round(raw * len(ss) / (len(ss) + K_SHRINK), 4)
            else:
                eff[g][s] = 0.0
    return eff, base, ns


def predicted_shift(eff_g, sh, is_fav):
    """centred pre-game shift for one player: sum over scripts P(script) x effect, minus the same for an average player."""
    fav15, close, dog15 = sh
    mid = max(0.0, 1 - fav15 - close - dog15)
    win, lose = (fav15, dog15) if is_fav else (dog15, fav15)
    e = win * eff_g["blow_win"] + lose * eff_g["blow_lose"] + close * eff_g["close"] + mid * eff_g["mid"]
    return e


def heldout(c, games, rows):
    seasons = sorted({r["season"] for r in rows})
    print(f"## held-out (seasons {seasons})")
    if len(seasons) < 2:
        print("  one season only: no held-out test")
        return {}
    gi_season = {}
    for r in rows:
        gi_season[r["gi"]] = r["season"]
    total = defaultdict(lambda: [0, 0])
    for test in seasons:
        train_rows = [r for r in rows if r["season"] != test]
        train_games = [g for i, g in enumerate(games) if gi_season.get(i, "") != test]
        eff, base, _ = effects_of(train_rows)
        shares = shares_of(c, train_games)
        shmap = {(lo, hi): (f, cl, dg) for lo, hi, f, cl, dg, n in shares}
        # average effect over fav/dog so a pure 'any game' shift cancels
        for r in rows:
            if r["season"] != test or r["is_fav"] is None or r["strength"] is None or r["g"] not in eff:
                continue
            sh = shmap.get(bucket(c, r["strength"]))
            if not sh:
                continue
            e = predicted_shift(eff[r["g"]], sh, r["is_fav"])
            centre = 0.5 * (predicted_shift(eff[r["g"]], sh, True) + predicted_shift(eff[r["g"]], sh, False))
            shift = e - centre
            pred = base[r["g"]] + shift
            lab = "up 2%+" if shift >= 0.02 else "down 2%+" if shift <= -0.02 else "up 1-2%" if shift >= 0.01 else "down 1-2%" if shift <= -0.01 else "flat"
            total[lab][0] += 1
            total[lab][1] += r["beat"]
            total[(lab, "pred")] = total.get((lab, "pred"), 0) + pred
            total[(lab, "base")] = total.get((lab, "base"), 0) + base[r["g"]]
    out = {}
    for lab in ("up 2%+", "up 1-2%", "flat", "down 1-2%", "down 2%+"):
        n, w = total[lab]
        if n:
            pr, bs = total[(lab, "pred")] / n, total[(lab, "base")] / n
            print(f"  predicted {lab:9s} n={n:6d} actual beat {w / n:.3f}  predicted {pr:.3f}  group base {bs:.3f}  lift {w / n - bs:+.3f}")
            out[lab] = {"n": n, "actual": round(w / n, 3), "pred": round(pr, 3), "base": round(bs, 3)}
    return out


def run(sport):
    c = CFG[sport]
    ids = event_ids(c)
    print(f"===== {sport}: {len(ids)} completed games")
    with ThreadPoolExecutor(max_workers=8) as ex:
        packs = list(ex.map(lambda t: (t[1], package(c, t[0])), ids))
    games = [(d, p) for d, p in packs if p]
    print(f"{len(games)} with box scores; pre-game line on {sum(1 for _, p in games if p['strength'] is not None)}")
    rows = build_rows(c, games)
    print(f"{len(rows)} player-games with a baseline")
    shares = shares_of(c, games)
    for s in shares:
        print("SHARE", s)
    eff, base, ns = effects_of(rows)
    for g in sorted(eff):
        print(f"EFF {g:18s} n={ns[g]:6d} base={base[g]:.3f} " + " ".join(f"{s}={v:+.3f}" for s, v in eff[g].items()))
    ho = heldout(c, games, rows)
    print("SCRIPTJSON " + json.dumps({"sport": sport, "close": c["close"], "blow": c["blow"], "shares": shares,
                                      "effects": eff, "base": base, "n": ns, "heldout": ho,
                                      "games": len(games), "lined": sum(1 for _, p in games if p["strength"] is not None)}))


if __name__ == "__main__":
    for sp in (os.environ.get("SPORT") or "NBA,WNBA,NCAAMB,NFL,NCAAF,NHL").split(","):
        try:
            run(sp)
        except Exception as exc:                                # noqa: BLE001
            print(f"{sp} failed: {type(exc).__name__}: {exc}")
    sys.exit(0)
