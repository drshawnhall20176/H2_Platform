"""
research/scenario_study.py — can the matchup call blowouts / close games better than the spread alone? (Nov 7)

Games and pre-game lines from ESPN (as in script_study.py). For each game, scenario_model.features() from that
season's earlier games only. Compared on held-out games (other season; alternate games):
  table     the scenario shares by spread bucket (what the Game Script page used)
  spread    multinomial logistic on the line alone
  matchup   the full feature set
Metrics: log loss and Brier (lower is better), and calibration of P(favorite blows it open).
Prints SCENARIOJSON for the production seed. Run one sport: wrappers scenario_study_<sport>.py.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenario_model as M                                     # noqa: E402
import script_study as S                                       # noqa: E402


def season_start(c, d):
    for a, b in c["seasons"]:
        if a.isoformat() <= d <= b.isoformat() or a.isoformat() <= d:
            last = a
    return last


def build(sport):
    c = S.CFG[sport]
    ids = S.event_ids(c)
    with ThreadPoolExecutor(max_workers=8) as ex:
        packs = list(ex.map(lambda t: (t[1], t[0], S.package(c, t[0])), ids))
    games = sorted([(d, gid, p) for d, gid, p in packs if p], key=lambda x: x[0])
    hist = M.History()
    rows = []
    for d, gid, p in games:
        home = next(t for t, v in p["teams"].items() if v["home"])
        away = next(t for t in p["teams"] if t != home)
        ss = None
        for a, b in c["seasons"]:
            if a.isoformat() <= d:
                ss = a
        if p["fav"] is not None and p["strength"] is not None:
            fav = p["fav"]
            dog = away if fav == home else home
            x = M.features(hist, d, fav, dog, fav == home, p["strength"], "ml" if c["kind"] == "hockey" else "spread",
                           c["close"], c["blow"], season_start=ss, margin_per_strength=1.5)
            if x is not None:
                fm = p["teams"][fav]["score"] - p["teams"][dog]["score"]
                rows.append({"x": x, "y": M.label(fm, c["close"], c["blow"]), "d": d, "season": S.season_of(c, d),
                             "strength": p["strength"], "gid": gid})
        hist.add(d, home, away, p["teams"][home]["score"], p["teams"][away]["score"])
    return c, rows


def table_model(c, train):
    by = defaultdict(lambda: defaultdict(int))
    for r in train:
        by[S.bucket(c, r["strength"])][r["y"]] += 1
    out = {}
    for b, cnt in by.items():
        n = sum(cnt.values())
        out[b] = {k: (cnt.get(k, 0) + 1) / (n + 4) for k in M.CLASSES}
    return lambda r: out.get(S.bucket(c, r["strength"])) or {k: 0.25 for k in M.CLASSES}


def evaluate(c, rows, how):
    if how == "season":
        part = lambda r: r["season"]                            # noqa: E731
    else:
        part = lambda r: str(rows.index(r) % 2) if False else r["_alt"]  # noqa: E731
    parts = sorted({part(r) for r in rows} - {"x"})
    if len(parts) < 2:
        return None
    res = defaultdict(list)
    ys = []
    cal = defaultdict(lambda: [0, 0.0, 0])
    for t in parts:
        train = [r for r in rows if part(r) != t]
        test = [r for r in rows if part(r) == t]
        if len(train) < 100 or not test:
            continue
        tab = table_model(c, train)
        ms = M.fit([r["x"] for r in train], [r["y"] for r in train], feats=("strength",))
        mf = M.fit([r["x"] for r in train], [r["y"] for r in train])
        for r in test:
            res["table"].append(tab(r))
            res["spread"].append(M.predict(ms, r["x"]))
            pf = M.predict(mf, r["x"])
            res["matchup"].append(pf)
            ys.append(r["y"])
            for cls in ("fav_blowout", "close"):
                bnd = min(int(pf[cls] * 10), 9)
                k = cal[(cls, bnd)]
                k[0] += 1
                k[1] += pf[cls]
                k[2] += r["y"] == cls
    if not ys:
        return None
    out = {"n": len(ys)}
    for k, ps in res.items():
        out[k] = {"logloss": round(M.log_loss(ps, ys), 4), "brier": round(M.brier(ps, ys), 4)}
    print(f"## held-out by {how}: n={len(ys)}")
    for k in ("table", "spread", "matchup"):
        print(f"  {k:8s} logloss {out[k]['logloss']:.4f}  brier {out[k]['brier']:.4f}")
    for (cls, bnd), (n, sp, hit) in sorted(cal.items()):
        if n >= 15:
            print(f"  CAL {cls:11s} said {sp / n:.0%} (n={n:4d}) happened {hit / n:.0%}")
    return out


def run(sport):
    c, rows = build(sport)
    for i, r in enumerate(rows):
        r["_alt"] = str(i % 2)
    print(f"===== {sport}: {len(rows)} games with a line and history")
    if len(rows) < 150:
        print("too few")
        return
    ev = {h: evaluate(c, rows, h) for h in ("season", "alternate")}
    full = M.fit([r["x"] for r in rows], [r["y"] for r in rows])
    W = full["W"]
    print("## coefficients (standardized; columns fav_blowout middle close dog_blowout)")
    for i, f in enumerate(full["feats"]):
        print(f"  {f:11s} " + " ".join(f"{w:+.2f}" for w in W[i]))
    print("SCENARIOJSON " + json.dumps({"sport": sport, "model": full, "eval": ev, "n": len(rows)}))


if __name__ == "__main__":
    for sp in (os.environ.get("SPORT") or "NBA").split(","):
        try:
            run(sp)
        except Exception as exc:                                # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"{sp} failed: {exc}")
