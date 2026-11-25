"""Do home/away and rest-day splits add anything beyond the model's earned chance on NBA props? (Nov 25)

For each graded, priced NBA prop since opening night:
  * venue: is the player's team at home?  rest: days since the team's previous game (0 = back-to-back)
  * the player's own venue split: his average at tonight's venue minus his overall average, over this season's games
    before the date, as a share of the line and signed for the side (positive = the split favours the bet)
  * the same for back-to-backs vs rested games
Then: hit rate vs earned chance by bucket, and a logistic fit hit ~ logit(earned) + each feature.
Prints only aggregates -- no bets, no picks.
"""
import sys, os, collections, math, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date
import requests
import model_store as MS, daily_review as DR, props_money as PM, nba_engine as NE
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


S = requests.Session()


def get(url, **kw):
    for _ in range(3):
        try:
            r = S.get(url, timeout=20, **kw)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(1)
    return None


SCHED = {}


def schedule(tid):
    if tid in SCHED:
        return SCHED[tid]
    j = get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{tid}/schedule",
            params={"season": "2027", "seasontype": 2}) or {}
    out = []
    for e in j.get("events") or []:
        try:
            c = e["competitions"][0]
            me = next(x for x in c["competitors"] if str(x["id"]) == tid)
            out.append({"id": str(e["id"]), "date": e["date"][:10], "home": me.get("homeAway") == "home",
                        "done": c.get("status", {}).get("type", {}).get("completed", False)})
        except Exception:
            continue
    SCHED[tid] = sorted(out, key=lambda g: g["date"])
    return SCHED[tid]


BOX = {}


def box(gid):
    if gid not in BOX:
        try:
            BOX[gid] = NE.get_game_boxscore(gid)
        except Exception:
            BOX[gid] = {}
    return BOX[gid]


print("== NBA props: home/away and rest splits vs the earned chance ==")
days = [d for d in MS.snapshot_dates("NBA") if "2026-10-21" <= d <= "2026-11-24"]
g = DR.grade_dates("NBA", days)
rows = [r for rs in g.values() for r in rs if r.get("result") in ("hit", "miss") and r.get("chance") is not None
        and r.get("p_market") is not None]
print("graded priced props", len(rows))
data = []
for r in rows:
    tid = str(r.get("team") or "")
    keys = statkey(str(r.get("market") or ""))
    day = r.get("slate_date") or r.get("date")
    if not tid or not keys or r.get("player_id") is None or r.get("line") is None or not day:
        continue
    sch = schedule(tid)
    today = next((x for x in sch if x["date"] in (day, (date.fromisoformat(day)).isoformat())), None)
    if today is None:
        continue
    before = [x for x in sch if x["date"] < today["date"] and x["done"]]
    rest = (date.fromisoformat(today["date"]) - date.fromisoformat(before[-1]["date"])).days - 1 if before else None
    vals = []                                   # (value, home?, back-to-back?)
    for i, x in enumerate(before[-20:]):
        ln = box(x["id"]).get(int(r["player_id"])) or box(x["id"]).get(str(r["player_id"]))
        if not ln or (ln.get("min") or 0) <= 5:
            continue
        k = before.index(x)
        b2b = k > 0 and (date.fromisoformat(x["date"]) - date.fromisoformat(before[k - 1]["date"])).days == 1
        vals.append((sum(float(ln.get(s) or 0) for s in keys), x["home"], b2b))
    side = r.get("side")
    pm = float(r["p_market"]); pm_side = pm if side == "Over" else 1 - pm
    try:
        e = PM.earned("NBA", r.get("market"), side, float(r["chance"]), pm_side)
    except Exception:
        e = None
    if e is None or len(vals) < 6:
        continue
    line = max(float(r["line"]), 1.0); sgn = 1 if side == "Over" else -1
    allavg = sum(v for v, _, _ in vals) / len(vals)
    ven = [v for v, h, _ in vals if h == today["home"]]
    b2bv = [v for v, _, b in vals if b]
    is_b2b = rest == 0
    same_rest = b2bv if is_b2b else [v for v, _, b in vals if not b]
    data.append({"hit": r["result"] == "hit", "earned": e, "over": side == "Over", "home": today["home"],
                 "b2b": is_b2b,
                 "ven": None if len(ven) < 3 else sgn * (sum(ven) / len(ven) - allavg) / line,
                 "rst": None if len(same_rest) < 3 else sgn * (sum(same_rest) / len(same_rest) - allavg) / line})
print("props analysed", len(data), "boxscores", len(BOX), "home", sum(d["home"] for d in data),
      "back-to-back", sum(d["b2b"] for d in data))


def show(name, key):
    by = collections.defaultdict(lambda: [0, 0, 0.0])
    for d in data:
        k = key(d)
        if k is None:
            continue
        b = by[k]; b[0] += 1; b[1] += d["hit"]; b[2] += d["earned"]
    print(" ", name, {k: f"n={v[0]} hit {v[1]/v[0]:.1%} earned {v[2]/v[0]:.1%} hit-earned {100*(v[1]-v[2])/v[0]:+.1f}"
                     for k, v in sorted(by.items())})


show("venue x side", lambda d: f"{'home' if d['home'] else 'away'} {'Over' if d['over'] else 'Under'}")
show("rest x side", lambda d: f"{'b2b' if d['b2b'] else 'rested'} {'Over' if d['over'] else 'Under'}")
bk = lambda x: None if x is None else ("split favours bet 10%+" if x > .1 else "0..10%" if x > 0 else "-10..0%" if x > -.1
                                      else "split against bet 10%+")
show("player's venue split", lambda d: bk(d["ven"]))
show("player's rest split", lambda d: bk(d["rst"]))
for name, f in (("venue split", "ven"), ("rest split", "rst")):
    sub = [d for d in data if d[f] is not None]
    if len(sub) > 300:
        X = [[1.0, logit(d["earned"]), max(-1, min(1, d[f]))] for d in sub]
        b, se = fit(X, [d["hit"] for d in sub])
        print(f"  logistic {name}: logit(earned) {b[1]}±{se[1]}  split {b[2]}±{se[2]}  n={len(sub)}")
for name, f in (("home (any side)", lambda d: 1.0 if d["home"] else 0.0),
                ("back-to-back Over", lambda d: 1.0 if d["b2b"] and d["over"] else 0.0),
                ("back-to-back Under", lambda d: 1.0 if d["b2b"] and not d["over"] else 0.0)):
    X = [[1.0, logit(d["earned"]), f(d)] for d in data]
    b, se = fit(X, [d["hit"] for d in data])
    print(f"  logistic {name}: coef {b[2]}±{se[2]}  n={len(data)}")
