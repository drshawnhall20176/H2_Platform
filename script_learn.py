"""
script_learn.py — the Game Script feedback loop (Nov 7). Run nightly per sport by .github/workflows/script-learn.yml.

Each run:
  1. UPDATE   fetch games that finished since the last run (ESPN box scores + pre-game lines) into the cache
              (.script_cache/<sport>.json.gz, kept between runs by actions/cache) -- only new days are fetched.
  2. GRADE    every pre-game scenario call logged earlier whose game is now final: what was said, what happened.
  3. LEARN    refit from every game so far:
                - the scenario table (how games finish by the size of the line),
                - the pre-game scenario model (line + matchup: scenario_model.py), tested on games it wasn't fit on
                  against the table -- ADOPTED only while it beats the table there,
                - each market's script effects and their held-out trust (script_data.py).
  4. CALL     today's and tomorrow's games: the scenario chances before tip, with the reasons, logged so step 2 can
              grade them tomorrow.
Everything the page reads lives in settings: script_learn:<sport> (the fit), scenario_calls:<sport> (pending and
graded calls). The page falls back to the shipped numbers (script_effects_data.json) until the first run.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

import scenario_model as M
import script_data as D

CACHE_DIR = os.environ.get("SCRIPT_CACHE", ".script_cache")
RESCAN_DAYS = 3                 # recent days are re-scanned (late finishes, postponements)
KEEP_GRADED = 3000


def _cache_path(sport: str) -> str:
    return os.path.join(CACHE_DIR, f"{sport}.json.gz")


CACHE_VERSION = 2              # Nov 9: games now carry TDs / kicking fields -- older caches are rebuilt


def load_cache(sport: str) -> Dict:
    try:
        with gzip.open(_cache_path(sport), "rt") as fh:
            c = json.load(fh)
        if c.get("version") != CACHE_VERSION:
            return {"days": set(), "games": {}}
        c["days"] = set(c.get("days") or [])
        return c
    except (OSError, ValueError):
        return {"days": set(), "games": {}}


def save_cache(sport: str, cache: Dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with gzip.open(_cache_path(sport), "wt") as fh:
        json.dump({"version": CACHE_VERSION, "days": sorted(cache["days"]), "games": cache["games"]}, fh)


# ---------------------------------------------------------------- 1. update
def update(sport: str, cache: Dict, today: Optional[date] = None) -> int:
    c = D.CFG[sport]
    today = today or date.today()
    fresh = today - timedelta(days=RESCAN_DAYS)
    days = [d for d in D.season_days(c) if d < today and (d.isoformat() not in cache["days"] or d >= fresh)]
    ids = D.event_ids(c, days)
    new = [(gid, d) for gid, d in ids if gid not in cache["games"]]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        packs = list(ex.map(lambda t: (t[0], t[1], D.package(c, t[0])), new))
    n = 0
    for gid, d, p in packs:
        if p:
            cache["games"][gid] = [d, p]
            n += 1
    for d in days:
        if d < fresh:
            cache["days"].add(d.isoformat())
    return n


def games_of(cache: Dict):
    return sorted(((d, p) for d, p in cache["games"].values()), key=lambda t: t[0])


def _season_start(c, d: str):
    ss = None
    for a, _b in c["seasons"]:
        if a.isoformat() <= d:
            ss = a
    return ss


def history(sport: str, cache: Dict) -> M.History:
    h = M.History()
    for d, p in games_of(cache):
        home = next(t for t, v in p["teams"].items() if v["home"])
        away = next(t for t in p["teams"] if t != home)
        h.add(d, home, away, p["teams"][home]["score"], p["teams"][away]["score"])
    return h


# ---------------------------------------------------------------- 3. learn
def scenario_rows(sport: str, cache: Dict) -> List[Dict]:
    c = D.CFG[sport]
    kind = "ml" if c["kind"] == "hockey" else "spread"
    h = M.History()
    rows = []
    for gid, (d, p) in sorted(cache["games"].items(), key=lambda t: t[1][0]):
        home = next(t for t, v in p["teams"].items() if v["home"])
        away = next(t for t in p["teams"] if t != home)
        if p.get("fav") is not None and p.get("strength") is not None:
            fav = p["fav"]
            dog = away if fav == home else home
            x = M.features(h, d, fav, dog, fav == home, p["strength"], kind, c["close"], c["blow"],
                           season_start=_season_start(c, d), margin_per_strength=1.5)
            if x is not None:
                fm = p["teams"][fav]["score"] - p["teams"][dog]["score"]
                rows.append({"x": x, "y": M.label(fm, c["close"], c["blow"]), "d": d, "gid": gid,
                             "season": D.season_of(c, d), "strength": p["strength"]})
        h.add(d, home, away, p["teams"][home]["score"], p["teams"][away]["score"])
    return rows


def table_probs(sport: str, shares: List, strength: Optional[float]) -> Dict[str, float]:
    c = D.CFG[sport]
    if strength is None:
        f, cl, dg = shares[0][2:5]
    else:
        f, cl, dg = shares[-1][2:5]
        b = D.bucket(c, strength)
        for lo, hi, ff, cc, dd, *_ in shares:
            if (lo, hi) == tuple(b):
                f, cl, dg = ff, cc, dd
    return {"fav_blowout": f, "middle": max(0.0, 1 - f - cl - dg), "close": cl, "dog_blowout": dg}


def evaluate(sport: str, rows: List[Dict]) -> Dict:
    """Held-out comparison: the table vs the matchup model, by alternate games and by season."""
    c = D.CFG[sport]
    out = {}
    for how in ("alternate", "season"):
        part = (lambda r: str(r["_i"] % 2)) if how == "alternate" else (lambda r: r["season"])
        parts = sorted({part(r) for r in rows} - {"x"})
        if len(parts) < 2:
            continue
        P = {"table": [], "line": [], "matchup": []}
        Y = []
        for t in parts:
            train = [r for r in rows if part(r) != t]
            test = [r for r in rows if part(r) == t]
            if len(train) < 150 or not test:
                continue
            sh = _shares_from_rows(c, train)
            ml = M.fit([r["x"] for r in train], [r["y"] for r in train], feats=LINE_FEATS)
            mm = M.fit([r["x"] for r in train], [r["y"] for r in train], l2=MATCHUP_L2)
            for r in test:
                P["table"].append(table_probs(sport, sh, r["strength"]))
                P["line"].append(M.predict(ml, r["x"]))
                P["matchup"].append(M.predict(mm, r["x"]))
                Y.append(r["y"])
        if Y:
            out[how] = {"n": len(Y), **{k: round(M.log_loss(v, Y), 4) for k, v in P.items()},
                        **{f"{k}_brier": round(M.brier(v, Y), 4) for k, v in P.items()}}
    return out


def _shares_from_rows(c, rows) -> List:
    by: Dict = {}
    for r in rows:
        by.setdefault(tuple(D.bucket(c, r["strength"])), []).append(r["y"])
    res = []
    for (lo, hi), ys in sorted(by.items()):
        n = len(ys)
        res.append([lo, hi, (ys.count("fav_blowout") + 0.25) / (n + 1), (ys.count("close") + 0.25) / (n + 1),
                    (ys.count("dog_blowout") + 0.25) / (n + 1), n])
    return res


LINE_FEATS = ("strength",)
MATCHUP_L2 = 20.0


def _beats(ev: Dict, a: str, b: str) -> bool:
    """a beats b on games neither was fit on: better on alternate games, and no worse (within 0.002) on the other
    season when there is one."""
    if "alternate" not in ev or ev["alternate"][a] >= ev["alternate"][b]:
        return False
    if "season" in ev and ev["season"]["n"] >= 200 and ev["season"][a] > ev["season"][b] + 0.002:
        return False
    return True


def choose(ev: Dict) -> str:
    """Which scenario source the page uses: the matchup model only if it beats the line curve (and the table); the
    line curve if it beats the table; otherwise the table. Re-decided every night."""
    if not ev:
        return "table"
    best = "line" if _beats(ev, "line", "table") else "table"
    if _beats(ev, "matchup", best) and _beats(ev, "matchup", "table"):
        best = "matchup"
    return best


def adopted(ev: Dict) -> bool:
    return choose(ev) != "table"


def learn(sport: str, cache: Dict) -> Dict:
    c = D.CFG[sport]
    games = games_of(cache)
    shares = D.shares_of(c, games)
    prow = D.build_rows(c, games)
    eff, base, ns = D.effects_of(prow)
    cond = {h: D.conditional_holdout(prow, games, h) for h in ("season", "alternate")}
    trust = {}
    for g in eff:
        vals = [v.get(g) for v in cond.values() if v and v.get(g) is not None]
        trust[g] = 0.0 if not vals or min(vals) < 0 else round(min(1.0, sum(vals) / len(vals)), 3)
    rows = scenario_rows(sport, cache)
    for i, r in enumerate(rows):
        r["_i"] = i
    ev = evaluate(sport, rows) if len(rows) >= 300 else {}
    src = choose(ev)
    model = None
    if src == "line":
        model = M.fit([r["x"] for r in rows], [r["y"] for r in rows], feats=LINE_FEATS)
    elif src == "matchup":
        model = M.fit([r["x"] for r in rows], [r["y"] for r in rows], l2=MATCHUP_L2)
    return {"close": c["close"], "blow": c["blow"], "shares": shares, "effects": eff, "base": base, "n": ns,
            "minutes": D.minutes_effects(c, games),
            "trust": trust, "conditional": cond, "games": len(games),
            "lined": sum(1 for _, p in games if p.get("strength") is not None),
            "scenario": {"model": model, "source": src, "eval": ev, "adopted": src != "table", "rows": len(rows)},
            "fit_at": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------- 4. call today's games / 2. grade
def call_games(sport: str, cache: Dict, fit: Dict, day: date) -> List[Dict]:
    """Pre-game calls for games on `day` that haven't started: scenario chances (model if adopted, else table),
    the table's for comparison, and the top reasons."""
    import script_effects as SE
    c = D.CFG[sport]
    kind = "ml" if c["kind"] == "hockey" else "spread"
    h = history(sport, cache)
    base = f"https://site.api.espn.com/apis/site/v2/sports/{c['path']}"
    sb = D._get(f"{base}/scoreboard", {"dates": day.strftime("%Y%m%d"), **c.get("extra", {})}) or {}
    out = []
    for ev in sb.get("events") or []:
        state = (((ev.get("status") or {}).get("type") or {}).get("state"))
        if state not in ("pre", None):
            continue
        g = SE.parse_event(ev, sport)
        if not g:
            continue
        comp = (ev.get("competitions") or [{}])[0]
        ids = [str((cc.get("team") or {}).get("id")) for cc in comp.get("competitors") or []]
        homes = [cc.get("homeAway") == "home" for cc in comp.get("competitors") or []]
        if len(ids) != 2:
            continue
        fav_i = g["fav"]
        fav, dog = ids[fav_i], ids[1 - fav_i]
        tbl = table_probs(sport, fit["shares"], g["strength"])
        sc = fit.get("scenario") or {}
        probs, why, src = tbl, [], "table"
        x = M.features(h, day.isoformat(), fav, dog, homes[fav_i], g["strength"], kind, c["close"], c["blow"],
                       season_start=_season_start(c, day.isoformat()), margin_per_strength=1.5)
        if sc.get("adopted") and sc.get("model") and x is not None:
            probs, src = M.predict(sc["model"], x), sc.get("source") or "model"
            if src == "matchup":
                why = [[M.FEATURE_TEXT.get(f, f), cl, round(p, 3)] for f, cl, p in M.drivers(sc["model"], x)]
        out.append({"gid": str(ev.get("id")), "d": day.isoformat(), "kick": ev.get("date"),
                    "fav": g["teams"][fav_i]["display"], "dog": g["teams"][1 - fav_i]["display"],
                    "fav_id": fav, "dog_id": dog, "strength": g["strength"], "p": probs, "table": tbl, "why": why,
                    "home": g["teams"][0 if homes[0] else 1]["display"], "away": g["teams"][1 if homes[0] else 0]["display"],
                    "source": src, "context": context(h, fav, dog, day, c, _season_start(c, day.isoformat()))})
    return out


def context(h: M.History, fav: str, dog: str, day: date, c: Dict, season_start) -> Dict:
    """What the two teams have shown this season -- shown beside the call as background. (Tested: none of it
    improves the call beyond the line yet; the nightly job keeps testing it.)"""
    lo = season_start or date.min

    def summ(team):
        gs = [g for g in h.before(team, day) if g[0] >= lo]
        if not gs:
            return None
        return {"n": len(gs), "won_big": sum(g[1] >= c["blow"] for g in gs), "lost_big": sum(g[1] <= -c["blow"] for g in gs),
                "close": sum(abs(g[1]) <= c["close"] for g in gs), "avg_margin": round(sum(g[1] for g in gs) / len(gs), 1),
                "last5": [round(g[1]) for g in gs[-5:]], "b2b": bool(gs and (day - gs[-1][0]).days <= 1)}
    return {"fav": summ(fav), "dog": summ(dog)}


def grade(calls: Dict, cache: Dict, sport: str) -> int:
    """Move pending calls whose game is final into the graded list."""
    c = D.CFG[sport]
    still, n = [], 0
    for k in calls.get("pending", []):
        got = cache["games"].get(k["gid"])
        if not got:
            if k["d"] >= (date.today() - timedelta(days=4)).isoformat():
                still.append(k)
            continue
        p = got[1]
        fs, ds = p["teams"].get(k["fav_id"], {}).get("score"), p["teams"].get(k["dog_id"], {}).get("score")
        if fs is None or ds is None:
            continue
        k["y"] = M.label(fs - ds, c["close"], c["blow"])
        k["margin"] = fs - ds
        calls.setdefault("graded", []).append(k)
        n += 1
    calls["pending"] = still
    calls["graded"] = calls.get("graded", [])[-KEEP_GRADED:]
    return n


def track(calls: Dict) -> Dict:
    """How the logged calls did: log loss vs the table's, and calibration of P(favorite blows it open) / P(close)."""
    g = calls.get("graded") or []
    if not g:
        return {"n": 0}
    ys = [k["y"] for k in g]
    out = {"n": len(g), "model": M.log_loss([k["p"] for k in g], ys), "table": M.log_loss([k["table"] for k in g], ys),
           "bands": {}}
    for cls in ("fav_blowout", "close"):
        for lo in (0.0, 0.2, 0.35, 0.5, 0.65):
            hi = {0.0: 0.2, 0.2: 0.35, 0.35: 0.5, 0.5: 0.65, 0.65: 1.01}[lo]
            ks = [k for k in g if lo <= k["p"][cls] < hi]
            if ks:
                out["bands"][f"{cls}|{lo:.2f}-{min(hi, 1):.2f}"] = {
                    "n": len(ks), "said": sum(k["p"][cls] for k in ks) / len(ks),
                    "happened": sum(k["y"] == cls for k in ks) / len(ks)}
    return out


def run(sport: str, today: Optional[date] = None) -> Dict:
    import model_store as MS
    today = today or date.today()
    cache = load_cache(sport)
    added = update(sport, cache, today)
    save_cache(sport, cache)
    calls = MS.get_setting(f"scenario_calls:{sport}", None) or {"pending": [], "graded": []}
    graded = grade(calls, cache, sport)
    fit = learn(sport, cache)
    seen = {k["gid"] for k in calls["pending"]}
    new_calls = []
    for d in (today, today + timedelta(days=1)):
        for k in call_games(sport, cache, fit, d):
            if k["gid"] in seen:                                # re-call: the latest line and model win
                calls["pending"] = [x for x in calls["pending"] if x["gid"] != k["gid"]]
            calls["pending"].append(k)
            new_calls.append(k)
    calls["track"] = track(calls)
    fit["track"] = calls["track"]
    MS.save_setting(f"script_learn:{sport}", fit)
    MS.save_setting(f"scenario_calls:{sport}", calls)
    return {"sport": sport, "new_games": added, "graded": graded, "calls": len(new_calls), "games": fit["games"],
            "adopted": fit["scenario"]["adopted"], "eval": fit["scenario"]["eval"], "track": calls["track"]}


if __name__ == "__main__":
    for sp in (os.environ.get("SPORT") or (sys.argv[1] if len(sys.argv) > 1 else "NBA")).split(","):
        try:
            print(json.dumps(run(sp), default=str)[:3000])
        except Exception as exc:                                # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"{sp} failed: {exc}")
