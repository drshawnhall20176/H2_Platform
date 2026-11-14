"""Nov 14 -- (1) are the learning loops live and what have they learned; (2) the damage from the missing NBA
regression on real graded reads; (3) how correlated same-game props really are (vs the parlay simulator's 0.08 / 0.30)."""
import math, os, sys
from collections import defaultdict
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as D, props_engine as PE, player_props as PPR, long_shots as LS, calibration as CAL

print("== 1. what the loops have learned (active)")
for c in MS.list_calibration(): print("CAL", c.get("sport"), c.get("s"), str(c.get("approved_ts"))[:16], str(c.get("details"))[:120])
for b in MS.list_blend(): print("BLEND", b.get("sport"), b.get("market"), b.get("w"), str(b.get("approved_ts"))[:16])
for t in MS.list_tuning(): print("TUNE", t.get("sport"), t.get("slot") or t.get("market"), t.get("factor") or t.get("f"), str(t.get("approved_ts"))[:16])
for sp in ("NBA", "NFL", "NHL", "NCAAF", "NCAAMB"):
    ms = MS.daily_review_mornings(sp)[:3]
    tr = MS.daily_review_mornings(f"{sp}-tuning")[:2]
    rep = MS.load_daily_review(sp, ms[0]) if ms else None
    auto = (rep or {}).get("calibration", {}).get("auto") or []
    print("REVIEW", sp, "mornings", ms, "tuning reports", tr, "| auto:", [(a.get("side") or a.get("kind"), a.get("decision") or a.get("action"), a.get("s") or a.get("new")) for a in auto][:4])

print("\n== 2. NBA: what the new regression would have changed on graded reads (last 21 days)")
import position_data as PD
smp = PD.nba_league_props_sample(date.today().isoformat())
pg = (smp.get("cur") or []) + (smp.get("prior") or [])
byp = defaultdict(list)
for q in pg: byp[str(q["pid"])].append(q)
for v in byp.values(): v.sort(key=lambda q: str(q["order"]))
dates = [d for d in MS.snapshot_dates("NBA") if d >= (date.today() - timedelta(days=21)).isoformat() and d < date.today().isoformat()]
graded = [r for recs in D.grade_dates("NBA", dates).values() for r in recs]
print("graded NBA reads", len(graded))
lg_cache = {}
stats = defaultdict(lambda: [0, 0, 0, 0, 0])   # market -> [reads, lean changed, old lean hits(of changed), new lean hits(of changed), changed with result]
flip_rows = []
for r in graded:
    mk = r.get("market")
    if mk not in PPR.MARKETS or not PPR.shrink_minutes(mk) or r.get("actual") is None or r.get("line") is None:
        continue
    hist = [q for q in byp.get(str(r.get("player_id")), []) if str(q["order"])[:10] < r["slate_date"] and PE.num((q.get("stats") or {}).get("min")) > 0][-PPR.HIT_N:][::-1]
    if len(hist) < 3: continue
    vals = [PPR.market_value(q.get("stats") or {}, mk) for q in hist]; mins = [PE.num(q["stats"].get("min")) for q in hist]
    raw, _ = PE.rate_and_opportunity(vals, mins)
    key = (r["slate_date"], mk)
    if key not in lg_cache:
        lg_cache[key] = PPR.league_rate([q for q in pg if str(q["order"])[:10] < r["slate_date"]], mk)
    new = PE.shrink_toward(raw, mins, lg_cache[key], PPR.shrink_minutes(mk))
    if not raw or not new: continue
    f = LS.fit(r, "NBA")
    if not f: continue
    proj2 = float(r["projection"]) * new / raw
    k = PE.k_needed(float(r["line"]))
    p_new = LS.rung_raw(dict(f, projection=proj2), k)
    p_old = r.get("p_model")
    pm = r.get("p_market")
    def lean(p):
        if p is None: return None
        pf = PE.blend(p, pm, PE.MODEL_WEIGHT) if pm is not None else p
        eo, eu = PE.ev(pf, r.get("over_price")), PE.ev(1 - pf, r.get("under_price"))
        c = [(e, s) for e, s in ((eo, "Over"), (eu, "Under")) if e is not None]
        if not c: return None
        e, s = max(c)
        return s if e >= PE.MIN_EV else "No lean"
    lo, ln = lean(p_old), lean(p_new)
    st = stats[mk]; st[0] += 1
    over_hit = r["actual"] > PE.threshold(float(r["line"]))
    if lo != ln:
        st[1] += 1
        if lo in ("Over", "Under"): st[2] += (over_hit == (lo == "Over"))
        if ln in ("Over", "Under"): st[3] += (over_hit == (ln == "Over"))
        st[4] += 1
        flip_rows.append((r["slate_date"], r.get("player"), mk, r["line"], lo, ln, over_hit))
for mk, (n, ch, oh, nh, c) in stats.items():
    olds = sum(1 for x in flip_rows if x[2] == mk and x[4] in ("Over", "Under"))
    news = sum(1 for x in flip_rows if x[2] == mk and x[5] in ("Over", "Under"))
    print(f"DMG {mk:12} reads {n:5d}  lean changed {ch:4d}  old leans among them: {oh}/{olds} hit  new leans: {nh}/{news} hit")
ov = [x for x in flip_rows if x[4] == "Over" and x[5] != "Over"]
print(f"DMG Overs the old model took that the new one drops: {len(ov)}, hit {sum(1 for x in ov if x[6])}")

print("\n== 3. same-game correlation of Over outcomes (all graded reads with a line, last 28 days)")
def tet(a, b, c, d):
    if min(a, b, c, d) <= 0: return None
    return math.cos(math.pi / (1 + math.sqrt(a * d / (b * c))))
for sp in ("NBA", "NFL", "NHL", "NCAAMB"):
    ds = [d for d in MS.snapshot_dates(sp) if d >= (date.today() - timedelta(days=28)).isoformat() and d < date.today().isoformat()]
    rows = [r for recs in D.grade_dates(sp, ds).values() for r in recs if r.get("actual") is not None and r.get("line") is not None]
    seen = {}
    for r in rows:
        seen[(r["slate_date"], r["game"], r.get("player"), r.get("market"))] = r
    rows = list(seen.values())
    g = defaultdict(list)
    for r in rows: g[(r["slate_date"], r["game"])].append(r)
    cells = {"same player, two markets": [0, 0, 0, 0], "teammates": [0, 0, 0, 0], "opponents": [0, 0, 0, 0]}
    for grp in g.values():
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                a, b = grp[i], grp[j]
                if a.get("player") == b.get("player"):
                    kind = "same player, two markets"
                    if {a.get("market"), b.get("market")} & {"PRA", "PA", "PR", "RA", "PB"}: continue    # combos contain each other
                elif a.get("team") == b.get("team"):
                    kind = "teammates"
                else:
                    kind = "opponents"
                if a.get("market") != b.get("market") and kind != "same player, two markets": continue
                oa = a["actual"] > PE.threshold(float(a["line"])); ob = b["actual"] > PE.threshold(float(b["line"]))
                c = cells[kind]; c[0 if oa and ob else 1 if oa else 2 if ob else 3] += 1
    for kind, (both, a_only, b_only, none) in cells.items():
        n = both + a_only + b_only + none
        if n < 200: continue
        print(f"CORR {sp:6} {kind:26} pairs {n:6d}  latent rho {tet(both, a_only, b_only, none) or 0:+.3f}")
