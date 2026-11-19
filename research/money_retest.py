"""Nov 19 (owner: "yes re-test"): every graded NBA prop read re-scored as TODAY's model would have read it -- the
current blend weights, side factors and trust toward the books' price (Nov 17) -- then which edge band, if any,
returns money at the price it carried. Answers whether the 💰 band (6-15%) still means what it was tested on."""
import os, sys, random
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, postgame as PG, props_engine as PE, calibration as CAL

SP = "NBA"
sf = CAL.side_factors(SP)
print("RT settings side_factors", sf, "trust(sport)", CAL.trust(SP), "market trusts", CAL.market_trusts(SP))
rows = []
dates = MS.snapshot_dates(SP); snaps = MS.load_snapshots(SP, dates)
for d in sorted({s["slate_date"] for s in snaps}):
    day = [s for s in snaps if s["slate_date"] == d]
    try:
        g = PG.grade(day, PG.fetch_results(SP, d, sorted({(s["team"], s["opp"]) for s in day})))
    except Exception:
        continue
    for r in g:
        if r.get("actual") is None or r.get("p_model") is None or r.get("p_market") is None:
            continue
        if (r.get("book") or "") in PE.PICKEM_BOOKS or r.get("market") in PE.MONEY_SKIP.get(SP, ()):
            continue
        op, up = r.get("over_price"), r.get("under_price")
        if op is None or up is None:
            continue
        w = PE.weight_for({}, SP, r["market"])
        if str(r.get("gap") or "").startswith("big"):
            w = min(w, PE.GAP_MODEL_WEIGHT)
        p = PE.blend(float(r["p_model"]), float(r["p_market"]), w)
        p = CAL.apply_side(p, sf)
        p = CAL.apply_trust(p, float(r["p_market"]), CAL.trust(SP, r["market"]))
        thr = PE.threshold(float(r["line"]))
        if r["actual"] == thr:
            continue
        for side, pr, ps in (("Over", op, p), ("Under", up, 1 - p)):
            dec = PE.decimal(pr)
            if not dec:
                continue
            ev = ps * dec - 1
            hit = (r["actual"] > thr) == (side == "Over")
            rows.append({"date": d, "market": r["market"], "side": side, "ev_now": ev, "ev_then": r.get("ev") if side == r.get("side") else None,
                         "dec": dec, "hit": hit, "player": r.get("player")})
print("RT side-reads", len(rows), "days", len({r["date"] for r in rows}))

def roi(x): return sum((r["dec"] - 1) if r["hit"] else -1 for r in x) / len(x)
def test(name, f, show_days=False):
    g = sorted([r for r in rows if f(r)], key=lambda r: r["date"])
    if len(g) < 30:
        print(f"RT {name} | n={len(g)}"); return
    days = sorted({r["date"] for r in g}); byd = {d: [r for r in g if r["date"] == d] for d in days}
    random.seed(1); b = sorted(roi([r for d in random.choices(days, k=len(days)) for r in byd[d]]) for _ in range(1000))
    th = [g[i * len(g) // 3:(i + 1) * len(g) // 3] for i in range(3)]
    hr = sum(r["hit"] for r in g) / len(g); need = sum(1 / r["dec"] for r in g) / len(g)
    print(f"RT {name} | n={len(g)} ({len(g)/len(days):.0f}/night) | hit {hr:.1%} vs {need:.1%} | ROI {roi(g):+.1%} | 90% {b[50]:+.1%}..{b[949]:+.1%} | thirds " + " ".join(f"{roi(t):+.1%}" for t in th))
    if show_days:
        for d in days[-6:]:
            print(f"RT    {d} n={len(byd[d])} ROI {roi(byd[d]):+.1%}")
band = lambda lo, hi: (lambda r: lo <= r["ev_now"] < hi)
for lo, hi in ((0, .03), (.03, .06), (.06, .10), (.10, .15), (.15, 9), (.06, .15), (.03, .15), (.04, .12), (.02, .10)):
    test(f"NOW edge {lo:.0%}-{hi:.0%}", band(lo, hi))
test("NOW 6-15 favorites (shorter than +100)", lambda r: .06 <= r["ev_now"] < .15 and r["dec"] < 2.0)
test("NOW 6-15 plus money", lambda r: .06 <= r["ev_now"] < .15 and r["dec"] >= 2.0)
test("NOW 3-15 favorites", lambda r: .03 <= r["ev_now"] < .15 and r["dec"] < 2.0)
test("NOW 6-15 by night", band(.06, .15), show_days=True)
test("THEN 6-15 (as tested)", lambda r: r["ev_then"] is not None and .06 <= r["ev_then"] < .15)
