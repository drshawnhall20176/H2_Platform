"""Does head-to-head history add anything beyond the model's earned chance (props) or the market spread (game lines)?"""
import sys, os, json, math, collections, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
from datetime import date, datetime, timedelta
import model_store as MS, daily_review as DR, props_money as PM, nba_engine as NE

S = requests.Session()
def get(url, **kw):
    for i in range(3):
        try:
            r = S.get(url, timeout=20, **kw)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(1)
    return None

SITE = {"NBA": "basketball/nba", "NHL": "hockey/nhl", "NCAAMB": "basketball/mens-college-basketball"}

def teams(lg):
    j = get(f"https://site.api.espn.com/apis/site/v2/sports/{SITE[lg]}/teams", params={"limit": 1000}) or {}
    out = {}
    for t in (j.get("sports") or [{}])[0].get("leagues", [{}])[0].get("teams", []):
        t = t.get("team") or {}
        for k in ("abbreviation", "displayName", "shortDisplayName", "name", "location"):
            if t.get(k):
                out[str(t[k]).lower()] = str(t["id"])
    return out

SCHED = {}
def schedule(lg, tid, season):
    k = (lg, tid, season)
    if k in SCHED:
        return SCHED[k]
    j = get(f"https://site.api.espn.com/apis/site/v2/sports/{SITE[lg]}/teams/{tid}/schedule", params={"season": season}) or {}
    games = []
    for e in j.get("events") or []:
        try:
            c = e["competitions"][0]
            if not c.get("status", {}).get("type", {}).get("completed", True):
                continue
            cs = c["competitors"]
            me = next(x for x in cs if str(x["id"]) == tid)
            op = next(x for x in cs if str(x["id"]) != tid)
            sc = lambda x: float(x["score"]["value"]) if isinstance(x.get("score"), dict) else float(x.get("score"))
            games.append({"id": str(e["id"]), "date": e["date"][:10], "opp": str(op["id"]), "home": me.get("homeAway") == "home",
                          "margin": sc(me) - sc(op)})
        except Exception:
            continue
    SCHED[k] = games
    return games

def meetings(lg, tid, oid, before, seasons):
    out = []
    for s in seasons:
        out += [g for g in schedule(lg, tid, s) if g["opp"] == oid and g["date"] < before]
    lo = (date.fromisoformat(before) - timedelta(days=420)).isoformat()
    return sorted([g for g in out if g["date"] >= lo], key=lambda g: g["date"], reverse=True)

def logit(p): p = min(max(p, 1e-4), 1 - 1e-4); return math.log(p / (1 - p))

def fit(X, y, iters=25):
    """logistic regression via Newton; returns coefs and SEs"""
    import numpy as np
    X = np.array(X, float); y = np.array(y, float); b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ b)); W = p * (1 - p)
        H = X.T @ (X * W[:, None]); g = X.T @ (y - p)
        b = b + np.linalg.solve(H, g)
    p = 1 / (1 + np.exp(-X @ b)); W = p * (1 - p)
    se = np.sqrt(np.diag(np.linalg.inv(X.T @ (X * W[:, None]))))
    return [round(float(v), 3) for v in b], [round(float(v), 3) for v in se]

def statkey(market):
    m = market.lower()
    parts = []
    if "point" in m or "pts" in m or m.startswith("p+") or "pra" in m: parts.append("pts")
    if "rebound" in m or "reb" in m or "+r" in m or "pra" in m: parts.append("reb")
    if "assist" in m or "ast" in m or "+a" in m or "pra" in m: parts.append("ast")
    if "3" in m and ("three" in m or "3pt" in m or "3-p" in m or "3pm" in m or "threes" in m):
        return ["fg3m"]
    return sorted(set(parts))

# ----------------------------------------------------------------- A. NBA props
print("== A. NBA player props: H2H vs the earned chance ==")
tm = teams("NBA")
days = [d for d in MS.snapshot_dates("NBA") if "2026-10-21" <= d <= "2026-11-23"]
g = DR.grade_dates("NBA", days)
rows = [r for rs in g.values() for r in rs if r.get("result") in ("hit", "miss") and r.get("chance") is not None and r.get("p_market") is not None]
print("sample team/opp/pid", [(r.get("team"), r.get("opp"), r.get("player_id"), r.get("slate_date")) for r in rows[:5]], "nteams", len(tm))
print("graded priced props", len(rows), "sample keys", sorted(rows[0].keys()) if rows else None)
mk = collections.Counter(r.get("market") for r in rows); print("markets", dict(mk))
BOX = {}
data = []
for r in rows:
    tid, oid = tm.get(str(r.get("team") or "").lower()), tm.get(str(r.get("opp") or "").lower())
    keys = statkey(str(r.get("market") or ""))
    if not tid or not oid or not keys or r.get("player_id") is None or r.get("line") is None:
        continue
    ms = meetings("NBA", tid, oid, r["slate_date"] if r.get("slate_date") else r.get("date", ""), ["2026", "2027"])
    vals = []
    for m in ms[:4]:
        if m["id"] not in BOX:
            try: BOX[m["id"]] = NE.get_game_boxscore(m["id"])
            except Exception: BOX[m["id"]] = {}
        ln = BOX[m["id"]].get(int(r["player_id"])) or BOX[m["id"]].get(str(r["player_id"]))
        if ln and (ln.get("min") or 0) > 5:
            vals.append(sum(float(ln.get(k) or 0) for k in keys))
    side = r.get("side"); pm = float(r["p_market"]); pm_side = pm if side == "Over" else 1 - pm
    try: e = PM.earned("NBA", r.get("market"), side, float(r["chance"]), pm_side)
    except Exception: e = None
    if e is None: continue
    line = float(r["line"]); sgn = 1 if side == "Over" else -1
    h2h = None if not vals else sgn * (sum(vals) / len(vals) - line) / max(line, 1.0)
    data.append({"hit": r["result"] == "hit", "earned": e, "pm": pm_side, "n": len(vals), "h2h": h2h})
print("props with team ids", len(data), "with >=1 H2H game", sum(1 for d in data if d["n"]), ">=2", sum(1 for d in data if d["n"] >= 2),
      "boxscores fetched", len(BOX))
def bucket(x):
    return "H2H strongly agrees (>+20%)" if x > .2 else "H2H agrees (0..20%)" if x > 0 else "H2H disagrees (-20..0%)" if x > -.2 else "H2H strongly disagrees (<-20%)"
for minn in (1, 2):
    by = collections.defaultdict(lambda: [0, 0, 0.0, 0.0])
    for d in data:
        if d["n"] >= minn:
            b = by[bucket(d["h2h"])]; b[0] += 1; b[1] += d["hit"]; b[2] += d["earned"]; b[3] += d["pm"]
    print(f" min {minn} H2H games:", {k: f"n={v[0]} hit {v[1]/v[0]:.1%} earned {v[2]/v[0]:.1%} market {v[3]/v[0]:.1%} hit-earned {100*(v[1]-v[2])/v[0]:+.1f}" for k, v in sorted(by.items())})
for minn in (1, 2):
    sub = [d for d in data if d["n"] >= minn]
    if len(sub) > 200:
        X = [[1.0, logit(d["earned"]), max(-1, min(1, d["h2h"]))] for d in sub]
        b, se = fit(X, [d["hit"] for d in sub])
        print(f" logistic (min {minn}): intercept {b[0]}±{se[0]}  logit(earned) {b[1]}±{se[1]}  H2H edge {b[2]}±{se[2]}  n={len(sub)}")
# ----------------------------------------------------------------- B. game lines
sys.exit(0)
print("== B. game lines: prior meetings vs the market spread ==")
for lg, seasons in (("NBA", ["2026", "2027"]), ("NHL", ["2026", "2027"]), ("NCAAMB", ["2026", "2027"])):
    tm = teams(lg)
    recs = [p for p in MS.load_game_picks(lg) if p.get("final_home") is not None and p.get("home_spread") is not None]
    if recs: print(lg, "sample game keys", sorted(recs[0].keys())[:40])
    rows = []
    for p in recs:
        hid, aid = tm.get(str(p.get("home") or "").lower()), tm.get(str(p.get("away") or "").lower())
        if not hid or not aid:
            continue
        ms = meetings(lg, hid, aid, str(p.get("kickoff") or "")[:10], seasons)
        if not ms:
            continue
        hm = sum(m["margin"] for m in ms[:4]) / len(ms[:4])          # home team's avg margin vs this opponent
        mkt = -float(p["home_spread"])
        res = float(p["final_home"]) - float(p["final_away"]) + float(p["home_spread"])
        if res == 0: continue
        mm = p.get("model_margin")
        rows.append({"sig": hm - mkt, "cover": res > 0, "n": len(ms[:4]), "model": None if mm is None else float(mm) - mkt})
    if not rows:
        print(lg, "no matched games"); continue
    by = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        k = "H2H says home better than spread by 5+" if r["sig"] >= 5 else "0..5" if r["sig"] >= 0 else "-5..0" if r["sig"] > -5 else "H2H says away better by 5+"
        b = by[k]; b[0] += 1; b[1] += (r["cover"] if r["sig"] >= 0 else not r["cover"])
    print(lg, "games with a prior meeting", len(rows), "of", len(recs), {k: f"n={v[0]} H2H side covered {v[1]/v[0]:.1%}" for k, v in by.items()})
    sub = [r for r in rows if r["model"] is not None]
    if len(sub) > 150:
        sd = (sum(r['sig']**2 for r in sub)/len(sub))**.5 or 1
        X = [[1.0, r["model"] / 10, r["sig"] / sd] for r in sub]
        b, se = fit(X, [r["cover"] for r in sub])
        print(f"  logistic home cover: model-vs-market {b[1]}±{se[1]}  H2H-vs-market (per sd) {b[2]}±{se[2]}  n={len(sub)}")
