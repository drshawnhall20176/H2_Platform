import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date, timedelta
import collections, math
import model_store as MS, intl_hoops as I, money_score as MSC
games = MS.load_results("NCAAMB", since="2025-10-01")
picks = [p for p in MS.load_game_picks("NCAAMB", ungraded=False) if p.get("final_home") is not None and str(p.get("kickoff") or "")[:10] >= "2026-11-03"]
def day_of(p):  # New York slate day
    from datetime import datetime
    import pytz
    return datetime.fromisoformat(str(p["kickoff"]).replace("Z","+00:00")).astimezone(pytz.timezone("US/Eastern")).date().isoformat()
for p in picks: p["_day"] = day_of(p)
def neu(p):
    for g in games:
        if g["date"][:10] in (p["_day"], (date.fromisoformat(p["_day"])+timedelta(days=1)).isoformat()) and I.find_team([g["home_team"]], p["home"]) and I.find_team([g["away_team"]], p["away"]):
            return str(g.get("neutral_site")).lower() in ("true","1")
    return False
for p in picks: p["_neu"] = neu(p)
cache = {}
def r_at(ds):
    if ds not in cache:
        gg=[g for g in games if g["date"][:10] < ds]
        cache[ds]=I.ratings_weighted(gg, I.decay_weights(gg, ds, "NCAAMB"), I.LEAGUES["NCAAMB"]["lam"], I.HFA_PRIOR["NCAAMB"])
    return cache[ds]
print("graded picks", len(picks), "neutral", sum(p["_neu"] for p in picks), "hfa prior", I.HFA_PRIOR["NCAAMB"])
rows = {"old": [], "new": []}
for p in picks:
    rows["old"].append((p["_day"], MSC.features(p, "NCAAMB"), p))
    pr = I.project(r_at(p["_day"]), p["home"], p["away"], neutral=p["_neu"])
    if not pr: continue
    q = dict(p, model_margin=pr["margin"], model_p=None)
    rows["new"].append((p["_day"], MSC.features(q, "NCAAMB", I.win_prob(pr["margin"], league="NCAAMB")), p))
days = sorted({d for d,_,_ in rows["old"]})
for ver in ("old", "new", "new_c0"):
    src = rows["new" if ver != "old" else "old"]
    w_by_day = {}
    tot = collections.Counter(); per = collections.defaultdict(lambda: [0,0.0])
    for D in days:
        train = {m: [f for d,fs,_ in src if d < D for f in fs if f["mkt"]==m and f["y"] is not None] for m in ("ML","SP")}
        if len(train["ML"]) < 80: continue
        w = {m: MSC.fit(train[m]) for m in ("ML","SP")}
        if ver == "new_c0":
            w = {m: [v[0], v[1], 0.0] for m, v in w.items()}
        w_by_day[D] = w
        for d, fs, p in src:
            if d != D: continue
            best = None
            for f in fs:
                if f["mkt"] not in ("ML","SP"): continue
                s = MSC.score_market(f, w[f["mkt"]])
                if s and (best is None or s["score"] > best[0]["score"]): best = (s, f)
            if not best: continue
            s, f = best
            if not (MSC.BAND[0] <= s["score"] <= MSC.BAND[1] and s["chance"] >= MSC.MIN_CHANCE): continue
            y = f["y"]
            if y is None: continue
            won = (y == 1.0) if s["side"] in ("home","over") else (y == 0.0)
            dec = MSC._dec(s["price"]); u = (dec - 1) if won else -1.0
            tot["n"] += 1; tot["w"] += won; tot["u"] += u
            per[D[:9]+("a" if D[8:]<"13" else "b")][0] += 1; per[D[:9]+("a" if D[8:]<"13" else "b")][1] += u
            tot["home"] += s["side"] == "home"
    last = w_by_day[max(w_by_day)] if w_by_day else None
    print(f"{ver:7s} 💰 picks {tot['n']}, won {tot['w']} ({tot['w']/max(1,tot['n']):.1%}), {tot['u']:+.1f}u ({tot['u']/max(1,tot['n']):+.1%} per $1), home side {tot['home']/max(1,tot['n']):.0%} | halves {[(k, v[0], round(v[1]/max(1,v[0]),3)) for k,v in sorted(per.items())]} | last fit ML {[round(x,3) for x in last['ML']] if last else None}")
