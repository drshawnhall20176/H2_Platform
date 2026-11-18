"""Nov 18: how wide do game finishes run around the book line? (game simulator MARGIN_SD / TOTAL_SD check)
ESPN summaries (pickcenter) for a sample of last season's + this season's games per league."""
import math, os, sys, random
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import postgame as PG, todays_best as TB
LEAGUES = {
    "NBA": ("basketball/nba", {}, [("2025-10-21", "2026-04-12"), ("2026-10-20", None)], 20),
    "NCAAMB": ("basketball/mens-college-basketball", {"groups": 50, "limit": 400}, [("2025-11-03", "2026-03-15"), ("2026-11-02", None)], 20),
    "NHL": ("hockey/nhl", {}, [("2025-10-07", "2026-04-16"), ("2026-10-06", None)], 3),
    "NFL": ("football/nfl", {}, [("2025-09-04", "2026-01-04"), ("2026-09-09", None)], 17),
    "NCAAF": ("football/college-football", {"groups": 80, "limit": 300}, [("2025-08-23", "2025-12-13"), ("2026-08-29", None)], 21),
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
            st = c.get("status") or {}
            if not (st.get("type") or {}).get("completed"): continue
            side = {t.get("homeAway"): t for t in c.get("competitors") or []}
            if "home" not in side or "away" not in side: continue
            out.append({"id": ev.get("id"), "hp": num(side["home"].get("score")), "ap": num(side["away"].get("score")),
                        "period": st.get("period"), "season": d.year if d.month > 7 else d.year - 1})
    return out
def phi(z): return 0.5 * (1 + math.erf(z / math.sqrt(2)))
rnd = random.Random(1)
for lg, (path, extra, spans, blow) in LEAGUES.items():
    ds = []
    for a, b in spans:
        a = date.fromisoformat(a); b = date.fromisoformat(b) if b else date.today() - timedelta(days=1)
        while a <= b: ds.append(a); a += timedelta(days=1)
    with ThreadPoolExecutor(max_workers=10) as ex:
        games = [g for gs in ex.map(lambda d: day(path, extra, d), ds) for g in gs if g["hp"] is not None]
    games = list({g["id"]: g for g in games}.values())
    smp = rnd.sample(games, min(1400, len(games)))
    def add(g):
        s = PG._http(f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary", {"event": g["id"]}) or {}
        pc = s.get("pickcenter") or []
        if pc:
            g["spread"], g["ou"] = num(pc[0].get("spread")), num(pc[0].get("overUnder"))
        return g
    with ThreadPoolExecutor(max_workers=10) as ex:
        smp = list(ex.map(add, smp))
    wl = [g for g in smp if g.get("spread") is not None]
    msd, tsd = TB.MARGIN_SD.get(lg), TB.TOTAL_SD.get(lg)
    if wl:
        sgn = 1 if sum((-g["spread"]) * (g["hp"] - g["ap"]) for g in wl) >= 0 else -1
        exp = [sgn * (-g["spread"]) for g in wl]
        res = [(g["hp"] - g["ap"]) - e for g, e in zip(wl, exp)]
        n = len(res); m = sum(res) / n; sd = math.sqrt(sum((x - m) ** 2 for x in res) / (n - 1))
        k = sum((x - m) ** 4 for x in res) / n / sd ** 4
        act_blow = sum(abs(g["hp"] - g["ap"]) >= blow for g in wl) / n
        sim_blow = sum(1 - phi((blow - e) / msd) + phi((-blow - e) / msd) for e in exp) / n
        fit_blow = sum(1 - phi((blow - e) / sd) + phi((-blow - e) / sd) for e in exp) / n
        # favorite win: actual vs normal(exp, msd)
        fav = [(abs(e), (g["hp"] - g["ap"]) * (1 if e > 0 else -1) > 0) for g, e in zip(wl, exp) if e != 0]
        pf = sum(phi(a / msd) for a, _ in fav) / len(fav); af = sum(w for _, w in fav) / len(fav)
        print(f"C {lg:6} games {len(games)} sampled-with-line {n}: margin SD around line {sd:.2f} (sim uses {msd}) kurtosis {k:.2f} "
              f"|resid|>2SD {sum(abs(x-m)>2*sd for x in res)/n:.1%} (normal 4.6%) | {blow}+ margin: actual {act_blow:.1%}, sim {sim_blow:.1%}, "
              f"at measured SD {fit_blow:.1%} | favorite won {af:.1%} vs sim {pf:.1%}")
        for s in sorted({g['season'] for g in wl}):
            rs = [x for g, x in zip(wl, res) if g["season"] == s]
            if len(rs) > 30:
                mm = sum(rs) / len(rs); print(f"C {lg:6}   season {s}-{s+1}: n{len(rs)} SD {math.sqrt(sum((x-mm)**2 for x in rs)/(len(rs)-1)):.2f}")
    wt = [g for g in smp if g.get("ou")]
    if wt:
        res = [(g["hp"] + g["ap"]) - g["ou"] for g in wt]
        n = len(res); m = sum(res) / n; sd = math.sqrt(sum((x - m) ** 2 for x in res) / (n - 1))
        print(f"C {lg:6} totals n{n}: SD around the total {sd:.2f} (sim uses {tsd}), bias {m:+.2f}, |resid|>2SD {sum(abs(x-m)>2*sd for x in res)/n:.1%}")
    if lg == "NHL":
        ot = [g for g in smp if g["period"]]
        act = sum((g["period"] or 0) > 3 for g in ot) / len(ot)
        def tie(a, b): return sum(math.exp(-a) * a ** k / math.factorial(k) * math.exp(-b) * b ** k / math.factorial(k) for k in range(15))
        pr = [tie(g["ou"] / 2, g["ou"] / 2) for g in ot if g.get("ou")]
        print(f"C NHL went to OT/SO: actual {act:.1%} of {len(ot)}; independent-Poisson (even game) implies {sum(pr)/max(len(pr),1):.1%}")
