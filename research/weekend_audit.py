"""Nov 20 weekend audit: calibration, edge bands, market-EV, locks, CLV and grading coverage by sport (current model).
Lines start with AUD so the log can be grepped."""
import sys
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, ".")
import calibration as CAL           # noqa: E402
import clv                          # noqa: E402
import daily_review as DR           # noqa: E402
import model_store as MS            # noqa: E402
import props_engine as PE           # noqa: E402

SPORTS = ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB")
SINCE = (date.today() - timedelta(days=45)).isoformat()


def p_now(sport, r):
    w = PE.weight_for({}, sport, r.get("market"))
    if str(r.get("gap") or "").startswith("big"):
        w = min(w, PE.GAP_MODEL_WEIGHT)
    pm = float(r["p_market"])
    p = PE.blend(float(r["p_model"]), pm, w)
    p = CAL.apply_side(p, CAL.side_factors(sport))
    return CAL.apply_trust(p, pm, CAL.trust(sport, r.get("market")))


def roi(rows):
    return sum((x["dec"] - 1) if x["hit"] else -1 for x in rows) / len(rows) if rows else 0.0


def line(tag, rows):
    if not rows:
        return f"{tag}: n=0"
    n = len(rows)
    hit = sum(x["hit"] for x in rows) / n
    need = sum(1 / x["dec"] for x in rows) / n
    days = len({x["date"] for x in rows})
    pz = sum(x.get("p", 0) for x in rows) / n
    return f"{tag}: n={n} days={days} said={pz:.1%} hit={hit:.1%} needed={need:.1%} roi={roi(rows):+.1%}"


for sp in SPORTS:
    dates = [d for d in MS.snapshot_dates(sp) if d >= SINCE]
    g = DR.grade_dates(sp, dates)
    allrows = [r for rs in g.values() for r in rs]
    # grading coverage, last 7 slates
    for d in sorted(g)[-7:]:
        rs = g[d]
        print(f"AUD {sp} COVER {d}: reads={len(rs)} graded={sum(r.get('actual') is not None for r in rs)}")
    reads = []
    for r in allrows:
        if r.get("actual") is None or r.get("p_model") is None or r.get("p_market") is None:
            continue
        if (r.get("book") or "") in PE.PICKEM_BOOKS:
            continue
        op, up = r.get("over_price"), r.get("under_price")
        if op is None or up is None:
            continue
        thr = PE.threshold(float(r["line"]))
        if r["actual"] == thr:
            continue
        p = p_now(sp, r)
        best = None
        for side, pr, ps in (("Over", op, p), ("Under", up, 1 - p)):
            dec = PE.decimal(pr)
            if not dec:
                continue
            pm_side = float(r["p_market"]) if side == "Over" else 1 - float(r["p_market"])
            x = {"side": side, "p": ps, "ev": ps * dec - 1, "mev": pm_side * dec - 1, "dec": dec,
                 "hit": (r["actual"] > thr) == (side == "Over"), "date": str(r.get("slate_date")),
                 "market": r.get("market"), "book": r.get("book")}
            # closing move of this side: first read vs last pre-game read (no-vig)
            f = clv._nv(side, r.get("first_over_price"), r.get("first_under_price"))
            l = clv._nv(side, r.get("over_price"), r.get("under_price"))
            fl, ll = r.get("first_line"), r.get("line")
            mv = None
            if fl is not None and ll is not None and abs(float(fl) - float(ll)) > 1e-9:
                mv = 1 if ((float(ll) > float(fl)) == (side == "Over")) else -1
            elif f is not None and l is not None:
                mv = 1 if l - f >= 0.01 else -1 if f - l >= 0.01 else 0
            x["clv"] = mv
            if best is None or x["ev"] > best["ev"]:
                best = x
        if best:
            best["lock"] = PE.is_lock(r.get("chance"), r.get("cushion"), r.get("gap"), r.get("book"))
            reads.append(best)
    print(f"AUD {sp} READS {len(reads)} graded+priced since {SINCE}")
    # calibration of the played side
    for lo, hi in ((0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 0.7), (0.7, 1.01)):
        print(f"AUD {sp} CAL " + line(f"{lo:.2f}-{hi:.2f}", [x for x in reads if lo <= x["p"] < hi]))
    # model edge bands
    for lo, hi in ((-1, 0), (0, 0.03), (0.03, 0.06), (0.06, 0.10), (0.10, 0.15), (0.15, 9)):
        b = [x for x in reads if lo <= x["ev"] < hi]
        c = [x["clv"] for x in b if x["clv"] is not None]
        print(f"AUD {sp} EV " + line(f"{lo:+.2f}..{hi:+.2f}", b)
              + (f" clv_beat={sum(v > 0 for v in c)/len(c):.0%} clv_lost={sum(v < 0 for v in c)/len(c):.0%} (n={len(c)})" if c else ""))
    # market-only EV (price vs consensus no-vig)
    for lo, hi in ((-9, -0.04), (-0.04, -0.02), (-0.02, 0), (0, 0.02), (0.02, 9)):
        print(f"AUD {sp} MEV " + line(f"{lo:+.2f}..{hi:+.2f}", [x for x in reads if lo <= x["mev"] < hi]))
    # agreement: model edge >= 3% and the price no worse than consensus -2%
    for tag, f in (("model3+&mev>-2", lambda x: x["ev"] >= 0.03 and x["mev"] > -0.02),
                   ("model3+&mev>0", lambda x: x["ev"] >= 0.03 and x["mev"] > 0),
                   ("model6-15&mev>-2", lambda x: 0.06 <= x["ev"] < 0.15 and x["mev"] > -0.02),
                   ("chance60+&ev>0", lambda x: x["p"] >= 0.6 and x["ev"] > 0),
                   ("lock", lambda x: x["lock"]),
                   ("lock&ev>0", lambda x: x["lock"] and x["ev"] > 0),
                   ("Under&ev3+", lambda x: x["side"] == "Under" and x["ev"] >= 0.03),
                   ("Over&ev3+", lambda x: x["side"] == "Over" and x["ev"] >= 0.03)):
        b = [x for x in reads if f(x)]
        half = len(b) // 2
        bs = sorted(b, key=lambda x: x["date"])
        print(f"AUD {sp} RULE " + line(tag, b)
              + (f" halves={roi(bs[:half]):+.1%}/{roi(bs[half:]):+.1%}" if half else ""))
    # markets with model edge >= 3%
    bym = defaultdict(list)
    for x in reads:
        if x["ev"] >= 0.03:
            bym[x["market"]].append(x)
    for m, b in sorted(bym.items(), key=lambda kv: -len(kv[1]))[:12]:
        if len(b) >= 30:
            print(f"AUD {sp} MKT " + line(f"{m}", b))
    # how many qualifying reads per slate (volume a user would see)
    perday = defaultdict(int)
    for x in reads:
        if x["ev"] >= 0.03 and x["mev"] > -0.02:
            perday[x["date"]] += 1
    if perday:
        v = sorted(perday.values())
        print(f"AUD {sp} VOLUME model3+&mev>-2 per slate: median={v[len(v)//2]} max={v[-1]} slates={len(v)}")
print("AUD DONE")
