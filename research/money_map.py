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

report("sport", lambda r: r["sport"])
report("use", lambda r: (r["sport"], r["use"]))
report("use-all", lambda r: r["use"])
report("lock", lambda r: (r["sport"], "lock" if r["lock"] else "-"))
EB = lambda r: None if r["ev"] is None else band(r["ev"], [0, 0.03, 0.06, 0.10, 0.15], ["<0", "0-3%", "3-6%", "6-10%", "10-15%", "15%+"])
report("ev", lambda r: (r["sport"], EB(r)) if EB(r) else None)
report("ev-all", lambda r: EB(r))
ED = lambda r: None if r["edge"] is None else band(r["edge"], [-0.05, 0, 0.03, 0.06, 0.10], ["<-5", "-5-0", "0-3", "3-6", "6-10", "10+"])
report("edge-all", lambda r: ED(r))
report("edge", lambda r: (r["sport"], ED(r)) if ED(r) else None)
PB = lambda r: band(r["dec"], [1.5, 1.77, 2.0, 2.5], ["-200 or shorter", "-199..-130", "-129..+100", "+101..+150", "+150 or longer"])
report("price", lambda r: (r["sport"], PB(r)))
report("price-all", lambda r: PB(r))
report("market", lambda r: (r["sport"], r["market"]))
report("market-ev+", lambda r: (r["sport"], r["market"]) if (r["ev"] or 0) > 0.03 else None, 30)
report("lock-price", lambda r: (r["sport"], PB(r)) if r["lock"] else None, 30)
report("lock-ev", lambda r: (r["sport"], "ev+" if (r["ev"] or -1) > 0 else "ev-") if r["lock"] else None, 30)
json.dump(rows, open("/tmp/money_rows.json", "w"))
