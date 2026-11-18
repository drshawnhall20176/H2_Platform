"""Nov 18 simulation audit: (A) are the prop distributions honest across the range (p_model reliability, tails);
(B) same-game correlation re-measured on all graded reads (slip simulator); (C) game-level spreads: how wide finishes
really are around the book line vs the game simulator's MARGIN_SD / TOTAL_SD, tails, NHL overtime."""
import math, os, sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as D, props_engine as PE, postgame as PG, todays_best as TB
TODAY = date.today().isoformat()

def graded(sp):
    ds = [d for d in MS.snapshot_dates(sp) if d < TODAY]
    rows = [r for recs in D.grade_dates(sp, ds).values() for r in recs
            if r.get("actual") is not None and r.get("line") is not None and r.get("result") in ("hit", "miss")]
    seen = {}
    for r in sorted(rows, key=lambda r: str(r.get("ts"))):
        seen[(r["slate_date"], r["game"], r.get("player"), r.get("market"), r.get("line"))] = r
    return list(seen.values()), ds

print("== A. prop distributions: model P(over) vs how often it went over")
CUTS = [0, .05, .1, .2, .3, .4, .5, .6, .7, .8, .9, .95, 1.01]
ALL = {}
for sp in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"):
    rows, ds = graded(sp)
    ALL[sp] = rows
    rows = [r for r in rows if r.get("p_model") is not None]
    print(f"A {sp} graded reads with a model chance: {len(rows)} over {len(ds)} slates")
    def table(rs, label):
        out = []
        for lo, hi in zip(CUTS, CUTS[1:]):
            s = [r for r in rs if lo <= float(r["p_model"]) < hi]
            if len(s) < 25: continue
            said = sum(float(r["p_model"]) for r in s) / len(s)
            hap = sum(r["actual"] > PE.threshold(float(r["line"])) for r in s) / len(s)
            se = math.sqrt(max(hap * (1 - hap), 1e-4) / len(s))
            out.append(f"{lo:.2f}-{hi:.2f}: n{len(s)} said {said:.1%} happened {hap:.1%} (±{1.96*se:.1%})")
        print(f"A {sp} {label:16} | " + " | ".join(out))
    table(rows, "all markets")
    mk = defaultdict(list)
    for r in rows: mk[r["market"]].append(r)
    for m, rs in sorted(mk.items(), key=lambda kv: -len(kv[1])):
        if len(rs) >= 400: table(rs, m)
    # the final, shown chance on the side the model took
    out = []
    for lo, hi in ((.5, .55), (.55, .6), (.6, .65), (.65, .7), (.7, .8), (.8, 1.01)):
        s = [r for r in ALL[sp] if r.get("chance") is not None and lo <= float(r["chance"]) < hi]
        if len(s) >= 25:
            out.append(f"{lo:.2f}-{hi:.2f}: n{len(s)} said {sum(float(r['chance']) for r in s)/len(s):.1%} hit {sum(r['result']=='hit' for r in s)/len(s):.1%}")
    print(f"A {sp} SHOWN chance    | " + " | ".join(out))
    # how far above projection players go: share of games at 1.5x / 2x projection (proj >= 3)
    big = [r for r in ALL[sp] if float(r.get("projection") or 0) >= 3]
    if big:
        print(f"A {sp} upside: n{len(big)} actual>=1.5x proj {sum(r['actual'] >= 1.5*float(r['projection']) for r in big)/len(big):.1%}"
              f"  >=2x {sum(r['actual'] >= 2*float(r['projection']) for r in big)/len(big):.1%}"
              f"  <=0.5x {sum(r['actual'] <= 0.5*float(r['projection']) for r in big)/len(big):.1%}")

print("\n== B. same-game correlation of Over outcomes (all graded reads), slip simulator uses", __import__("slip_sim").MEASURED_RHO)
def tet(a, b, c, d):
    if min(a, b, c, d) <= 0: return None
    return math.cos(math.pi / (1 + math.sqrt(a * d / (b * c))))
for sp in ("NBA", "NFL", "NHL", "NCAAF"):
    rows = ALL.get(sp) or []
    g = defaultdict(list)
    for r in rows: g[(r["slate_date"], r["game"])].append(r)
    cells = {"same player": [0, 0, 0, 0], "teammates": [0, 0, 0, 0], "opponents": [0, 0, 0, 0]}
    for grp in g.values():
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                a, b = grp[i], grp[j]
                if a.get("player") == b.get("player"):
                    kind = "same player"
                    if {a.get("market"), b.get("market")} & {"PRA", "PA", "PR", "RA", "PB", "Points"} and sp == "NHL" and False: pass
                    if {a.get("market"), b.get("market")} & {"PRA", "PA", "PR", "RA", "PB"}: continue
                    if sp == "NHL" and {a.get("market"), b.get("market")} & {"Points"}: continue
                elif a.get("team") == b.get("team"):
                    kind = "teammates"
                else:
                    kind = "opponents"
                if a.get("market") != b.get("market") and kind != "same player": continue
                oa = a["actual"] > PE.threshold(float(a["line"])); ob = b["actual"] > PE.threshold(float(b["line"]))
                c = cells[kind]; c[0 if oa and ob else 1 if oa else 2 if ob else 3] += 1
    for kind, (both, ao, bo, no) in cells.items():
        n = both + ao + bo + no
        if n < 150: continue
        r = tet(both, ao, bo, no)
        se = 1 / math.sqrt(n)
        print(f"B {sp:6} {kind:12} pairs {n:6d} latent rho {r if r is not None else float('nan'):+.3f} (rough ±{1.5*se:.3f})")

print("\n== C. game finishes around the book line (ESPN scoreboards)")
LEAGUES = {
    "NBA": ("basketball/nba", {}, [("2025-10-21", "2026-04-12"), ("2026-10-20", None)]),
    "NCAAMB": ("basketball/mens-college-basketball", {"groups": 50, "limit": 400}, [("2025-11-03", "2026-03-15"), ("2026-11-02", None)]),
    "NHL": ("hockey/nhl", {}, [("2025-10-07", "2026-04-16"), ("2026-10-06", None)]),
    "NFL": ("football/nfl", {}, [("2025-09-04", "2026-01-04"), ("2026-09-09", None)]),
    "NCAAF": ("football/college-football", {"groups": 80, "limit": 300}, [("2025-08-23", "2025-12-13"), ("2026-08-29", None)]),
}
def num(x):
    try:
        v = float(x); return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None
def day(path, extra, d):
    data = PG._http(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard", dict(extra, dates=d.strftime("%Y%m%d"))) or {}
    out = []
    for ev in data.get("events") or []:
        for c in ev.get("competitions") or []:
            st = (c.get("status") or {})
            if not (st.get("type") or {}).get("completed"): continue
            side = {t.get("homeAway"): t for t in c.get("competitors") or []}
            if "home" not in side or "away" not in side: continue
            o = (c.get("odds") or [{}])[0] if c.get("odds") else {}
            out.append({"id": ev.get("id"), "hp": num(side["home"].get("score")), "ap": num(side["away"].get("score")),
                        "spread": num(o.get("spread")), "ou": num(o.get("overUnder")), "period": st.get("period"),
                        "season": (ev.get("season") or {}).get("year")})
    return out
def phi(z): return 0.5 * (1 + math.erf(z / math.sqrt(2)))
for lg, (path, extra, spans) in LEAGUES.items():
    ds = []
    for a, b in spans:
        a = date.fromisoformat(a); b = date.fromisoformat(b) if b else date.today() - timedelta(days=1)
        while a <= b: ds.append(a); a += timedelta(days=1)
    with ThreadPoolExecutor(max_workers=10) as ex:
        games = {g["id"]: g for gs in ex.map(lambda d: day(path, extra, d), ds) for g in gs}.values()
    games = [g for g in games if g["hp"] is not None and g["ap"] is not None]
    wl = [g for g in games if g["spread"] is not None]
    # sign check: home spread negative = favored, so actual margin should rise as -spread rises
    if wl:
        c = sum((-g["spread"]) * (g["hp"] - g["ap"]) for g in wl)
        sgn = 1 if c >= 0 else -1
        res = [(g["hp"] - g["ap"]) - sgn * (-g["spread"]) for g in wl]
        n = len(res); m = sum(res) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in res) / (n - 1))
        k = sum((x - m) ** 4 for x in res) / n / sd ** 4
        t2 = sum(abs(x - m) > 2 * sd for x in res) / n
        cur = TB.MARGIN_SD.get(lg)
        blow = BLOW = {"NBA": 20, "NCAAMB": 20, "NHL": 3, "NFL": 17, "NCAAF": 21}[lg]
        act_blow = sum(abs(g["hp"] - g["ap"]) >= blow for g in wl) / n
        sim_blow = (sum(1 - phi((blow - sgn * (-g["spread"])) / cur) + phi((-blow - sgn * (-g["spread"])) / cur) for g in wl) / n) if cur else None
        print(f"C {lg:6} games {len(games)} with spread {n}: margin residual SD {sd:.2f} (sim uses {cur}), bias {m:+.2f}, "
              f"kurtosis {k:.2f} (normal 3), |resid|>2SD {t2:.1%} (normal 4.6%), {blow}+ blowouts actual {act_blow:.1%} sim-implied {sim_blow if sim_blow is None else f'{sim_blow:.1%}'}")
        for s in sorted({g['season'] for g in wl}):
            rs = [(g["hp"] - g["ap"]) - sgn * (-g["spread"]) for g in wl if g["season"] == s]
            if len(rs) > 30:
                mm = sum(rs) / len(rs); print(f"C {lg:6}   season {s}: n{len(rs)} SD {math.sqrt(sum((x-mm)**2 for x in rs)/(len(rs)-1)):.2f}")
    wt = [g for g in games if g["ou"]]
    if wt:
        res = [(g["hp"] + g["ap"]) - g["ou"] for g in wt]
        n = len(res); m = sum(res) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in res) / (n - 1))
        print(f"C {lg:6} totals n{n}: residual SD {sd:.2f} (sim uses {TB.TOTAL_SD.get(lg)}), bias {m:+.2f}, |resid|>2SD {sum(abs(x-m)>2*sd for x in res)/n:.1%}")
    if lg == "NHL":
        ot = [g for g in games if g["period"]]
        act = sum((g["period"] or 0) > 3 for g in ot) / len(ot)
        def pois_tie(mu_h, mu_a):
            return sum(math.exp(-mu_h) * mu_h ** k / math.factorial(k) * math.exp(-mu_a) * mu_a ** k / math.factorial(k) for k in range(15))
        pred = [pois_tie(g["ou"] / 2 + 0.15, g["ou"] / 2 - 0.15) for g in ot if g["ou"]]
        print(f"C NHL overtime: actual {act:.1%} of {len(ot)}; independent-Poisson sim implies {sum(pred)/len(pred):.1%}")
