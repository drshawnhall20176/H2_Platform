"""Nov 19 (owner: "a winning strategy for the big weekend"; "what the model says is a money pick and its hit rate"):
every graded pre-game prop read, scored at the price it carried -- which tags / edges / prices / markets have
actually RETURNED money, and did it hold in both halves of the window (by date)?"""
import os, sys, json
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, postgame as PG, props_engine as PE

def dec(a):
    try:
        a = float(a)
    except (TypeError, ValueError):
        return None
    if a >= 100: return 1 + a / 100
    if a <= -100: return 1 + 100 / -a
    return None

def price_of(r):
    side = r.get("side") or "Over"
    if r.get("bet_use_tag") and r.get("bet_result") is not None:
        p = r.get("bet_over_price") if side == "Over" else r.get("bet_under_price")
        if p is not None: return p
    if r.get("price") is not None: return r["price"]
    return r.get("over_price") if side == "Over" else r.get("under_price")

def band(x, cuts, labels):
    for c, l in zip(cuts, labels):
        if x < c: return l
    return labels[-1]

rows = []
for sport in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"):
    dates = MS.snapshot_dates(sport)
    snaps = MS.load_snapshots(sport, dates)
    for d in sorted({s["slate_date"] for s in snaps}):
        day = [s for s in snaps if s["slate_date"] == d]
        try:
            g = PG.grade(day, PG.fetch_results(sport, d, sorted({(s["team"], s["opp"]) for s in day})))
        except Exception as e:
            print("MM err", sport, d, e); continue
        for r in g:
            r = PG.as_tagged(r)
            if r.get("result") not in ("hit", "miss"): continue
            if (r.get("book") or "") in PE.PICKEM_BOOKS: continue
            dd = dec(price_of(r))
            if not dd: continue
            ev = r.get("ev")
            ch = r.get("chance")
            rows.append({"sport": sport, "date": d, "market": r.get("market"), "use": PE.norm_use(r.get("use_tag")),
                         "lock": PE.most_probable(ch, r.get("cushion"), r.get("gap")), "ev": ev, "chance": ch,
                         "dec": dd, "hit": r["result"] == "hit",
                         "imp": 1 / dd, "edge": None if ch is None else ch - 1 / dd})
print("MM rows", len(rows))

def report(name, keyf, min_n=40):
    by = defaultdict(list)
    for r in rows:
        k = keyf(r)
        if k is not None: by[k].append(r)
    out = []
    for k, g in by.items():
        if len(g) < min_n: continue
        g.sort(key=lambda r: r["date"])
        half = len(g) // 2
        def roi(x): return sum((r["dec"] - 1) if r["hit"] else -1 for r in x) / len(x)
        hr = sum(r["hit"] for r in g) / len(g)
        imp = sum(r["imp"] for r in g) / len(g)
        out.append((roi(g), k, len(g), hr, imp, roi(g[:half]), roi(g[half:])))
    out.sort(reverse=True)
    for o in out:
        print(f"MM {name} | {o[1]} | n={o[2]} | hit {o[3]:.1%} vs needed {o[4]:.1%} | ROI {o[0]:+.1%} | 1st half {o[5]:+.1%} | 2nd half {o[6]:+.1%}")

import random
def test(name, f):
    g = sorted([r for r in rows if f(r)], key=lambda r: r["date"])
    if len(g) < 30:
        print("MR", name, "n", len(g)); return
    days = sorted({r["date"] for r in g})
    byd = {d: [r for r in g if r["date"] == d] for d in days}
    def roi(x): return sum((r["dec"] - 1) if r["hit"] else -1 for r in x) / len(x)
    random.seed(1); boots = []
    for _ in range(2000):
        x = [r for d in random.choices(days, k=len(days)) for r in byd[d]]
        boots.append(roi(x))
    boots.sort()
    thirds = [g[i * len(g) // 3:(i + 1) * len(g) // 3] for i in range(3)]
    hr = sum(r["hit"] for r in g) / len(g); imp = sum(r["imp"] for r in g) / len(g)
    print(f"MR {name} | n={len(g)} over {len(days)} days | hit {hr:.1%} vs needed {imp:.1%} | ROI {roi(g):+.1%} "
          f"| 90% range {boots[100]:+.1%}..{boots[1900]:+.1%} | thirds " + " ".join(f"{roi(t):+.1%}" for t in thirds)
          + f" | per day {len(g)/len(days):.1f}")
nba = lambda r: r["sport"] == "NBA"
ev = lambda r, lo, hi: r["ev"] is not None and lo <= r["ev"] < hi
test("NBA EV 6-15", lambda r: nba(r) and ev(r, .06, .15))
test("NBA EV 8-15", lambda r: nba(r) and ev(r, .08, .15))
test("NBA EV 10-15", lambda r: nba(r) and ev(r, .10, .15))
test("NBA EV 3-15", lambda r: nba(r) and ev(r, .03, .15))
test("NBA EV 6+", lambda r: nba(r) and ev(r, .06, 9))
test("NBA edge 3-10", lambda r: nba(r) and r["edge"] is not None and .03 <= r["edge"] < .10)
test("NBA EV 6-15 lock", lambda r: nba(r) and ev(r, .06, .15) and r["lock"])
test("NBA EV 6-15 fav", lambda r: nba(r) and ev(r, .06, .15) and r["dec"] < 2.0)
test("NBA EV 6-15 dog", lambda r: nba(r) and ev(r, .06, .15) and r["dec"] >= 2.0)
test("NBA lock", lambda r: nba(r) and r["lock"])
test("NFL EV 6-15", lambda r: r["sport"] == "NFL" and ev(r, .06, .15))
test("NCAAF EV 3-15", lambda r: r["sport"] == "NCAAF" and ev(r, .03, .15))
test("NHL EV 6-15", lambda r: r["sport"] == "NHL" and ev(r, .06, .15))
test("ALL EV 6-15 ex NHL", lambda r: r["sport"] != "NHL" and ev(r, .06, .15))
for m in ("Points", "Rebounds", "Assists", "Threes Made", "PRA", "PA", "PR", "RA"):
    test(f"NBA EV 6-15 {m}", lambda r, m=m: nba(r) and ev(r, .06, .15) and r["market"] == m)
