import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import collections, math, daily_review as DR, model_store as MS, props_money as PM, props_engine as PE, money_score as MSC
def rows_for(sp, d0, d1):
    days = [d for d in MS.snapshot_dates(sp) if d0 <= d < d1]
    g = DR.grade_dates(sp, days); out = []
    for r in (x for rs in g.values() for x in rs):
        if r.get("actual") is None or r.get("p_model") is None or r.get("line") is None: continue
        thr = PE.threshold(float(r["line"]))
        if r["actual"] == thr: continue
        pmod = float(r["p_model"]); side = "Over" if pmod >= 0.5 else "Under"
        pk = (r.get("book") or "") in PE.PICKEM_BOOKS or r.get("p_market") is None
        pm_side = None if pk else (float(r["p_market"]) if side == "Over" else 1 - float(r["p_market"]))
        e = PM.earned(sp, r.get("market"), side, pmod if side == "Over" else 1 - pmod, pm_side, post=True)
        if e is None: continue
        out.append({"sp": sp, "side": side, "kind": "pk" if pk else "priced", "e": e, "y": float((r["actual"] > thr) == (side == "Over")), "shown": PM.shown(sp, r)})
    return out
train, test = [], []
for sp in PM.SPORTS:
    train += rows_for(sp, "2026-10-20", "2026-11-12"); test += rows_for(sp, "2026-11-12", "2026-11-22")
print("train", len(train), "test", len(test))
def key(r, pooled=False): return f"{r['side']}|{r['kind']}" if pooled else f"{r['sp']}|{r['side']}|{r['kind']}"
fits = {}
groups = collections.defaultdict(list)
for r in train:
    groups[key(r)].append(r); groups[key(r, True)].append(r)
for k, rs in groups.items():
    if len(rs) >= 200:
        w = MSC.fit([{"pm": 0.5, "pmod": min(max(r["e"],1e-4),1-1e-4), "y": r["y"]} for r in rs], lam=3.0)
        if w: fits[k] = w
def adj(r):
    w = fits.get(key(r)) or fits.get(key(r, True))
    if not w: return r["e"]
    lg = lambda p: math.log(p/(1-p))
    return 1/(1+math.exp(-(w[0] + w[1]*lg(0.5) + w[2]*(lg(min(max(r['e'],1e-4),1-1e-4)) - lg(0.5)))))
def report(lab, rs, f):
    by = collections.defaultdict(list)
    for r in rs: by[(r["sp"], r["side"], r["kind"])].append(r)
    br = sum((f(r)-r["y"])**2 for r in rs)/len(rs)
    worst = []
    for k, v in by.items():
        if len(v) >= 60:
            s = sum(f(r) for r in v)/len(v); h = sum(r["y"] for r in v)/len(v); worst.append((abs(s-h), k, s, h, len(v)))
    worst.sort(reverse=True)
    sh = [r for r in rs if r["shown"]]
    s_sh = sum(f(r) for r in sh)/max(1,len(sh)); h_sh = sum(r["y"] for r in sh)/max(1,len(sh))
    print(f"{lab}: brier {br:.4f} | shown picks said {s_sh:.1%} hit {h_sh:.1%} (n={len(sh)}) | biggest gaps: " + "; ".join(f"{k[0]} {k[1]} {k[2]}: said {s:.0%} hit {h:.0%} n={n}" for _,k,s,h,n in worst[:6]))
    clear = [r for r in rs if f(r) > 0.5425]
    print(f"   would clear the pick'em bar (54.25%): {len(clear)} reads, hit {sum(r['y'] for r in clear)/max(1,len(clear)):.1%}")
report("TEST, earned now", test, lambda r: r["e"])
report("TEST, + side stage", test, adj)
print("fits:", {k: [round(x,3) for x in v[:3]] for k, v in sorted(fits.items())})
