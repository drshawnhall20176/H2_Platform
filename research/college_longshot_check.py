"""Nov 14: can college get long shots? (1) do the books post college alternate player lines, (2) NCAAF tail test."""
import math, os, sys
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import book_menu as BM, long_shots as LS, odds_api as O

key = os.environ.get("ODDS_API_KEY", "")
now = datetime.now(timezone.utc)
for label, sk, alts in (("NCAAF", "americanfootball_ncaaf", list(LS.SPORTS["NFL"]["alt"])),
                        ("NCAAMB", "basketball_ncaab", list(LS.SPORTS["NBA"]["alt"]))):
    try:
        evs = O.fetch_events_all(key, sport=sk)
    except Exception as exc:                                   # noqa: BLE001
        print("AV", label, "events failed", exc); continue
    up = sorted([e for e in evs if now < datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) < now + timedelta(hours=36)],
                key=lambda e: e["commence_time"])
    print(f"AV {label}: {len(up)} games in the next 36h; sampling 14")
    for book in ("draftkings", "fanduel"):
        have, rungs, mk = 0, 0, Counter()
        for e in up[:14]:
            try:
                res = BM.fetch_menu(key, sk, [e["id"]], alts, book, feed_by_event={e["id"]: sk})
            except Exception as exc:                           # noqa: BLE001
                print("AV err", exc); continue
            q = res.get("quotes") or []
            if q:
                have += 1; rungs += len(q); mk.update(x.get("market") for x in q)
        print(f"AV {label} {book}: {have}/{min(14, len(up))} games with alternate player lines, {rungs} rungs; {dict(mk)}")

# ---------------- NCAAF tail test (same method as research/tail_calibration_fb_nhl.py)
import ncaaf_data as ND, position_data as PD, props_backtest as BT, props_engine as PE
BINS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 0.30), (0.30, 0.40), (0.40, 0.55), (0.55, 1.01)]
cap = []; _orig = PE.read_line
def spy(model, vals, line, dist, *a, **k):
    cap.append((model, list(vals), dist, (k.get("sd_floor_frac", 0.25), k.get("sd_floor_abs", 1.0))))
    return _orig(model, vals, line, dist, *a, **k)
PE.read_line = spy
roster = ND.load_rosters(); rows = ND.load_player_game_stats()
pos = {str(p.get("id")): p.get("position") for p in roster if p.get("id") is not None}
seasons = sorted({int(r["season"]) for r in rows if r.get("season") is not None})
pg = []
for s in seasons[-2:]:
    sub = PD.ncaaf_pgames(rows, s, 999, pos)
    for q in sub:
        q["order"] = (s - 2000) * 100 + q["order"]
    pg += sub
print("TC NCAAF seasons", seasons[-2:], "pgames", len(pg))
for market in ("Receiving Yards", "Rush Yards", "Pass Yards", "Receptions", "Rush + Rec Yards", "Passing TDs"):
    cap.clear(); got = []
    orig = BT.summarize
    BT.summarize = lambda cases: (got.extend(cases), orig(cases))[1]
    try:
        BT.backtest_football(pg, "NCAAF", market, max_cases=8000)
    except Exception as exc:                                   # noqa: BLE001
        print("TC", market, "failed", type(exc).__name__, exc); BT.summarize = orig; continue
    BT.summarize = orig
    if len(cap) != len(got):
        print(f"TC {market}: capture mismatch {len(cap)} vs {len(got)}"); continue
    cell = defaultdict(lambda: [0, 0, 0.0])
    for (model, vals, dist, floor), c in zip(cap, got):
        if not model or model <= 0: continue
        step = PE.ladder_step(market, model); base = math.floor(model / step) * step
        for k in (1, 2, 3):
            n = base + k * step
            p = PE.prob_over(model, vals, n - 0.5, dist, *floor)
            if p is None: continue
            for lo, hi in BINS:
                if lo <= p < hi:
                    x = cell[(lo, hi)]; x[0] += 1; x[1] += c["actual"] >= n; x[2] += p
    ratios = []
    print(f"TC NCAAF {market}: cases {len(got)}")
    for lo, hi in BINS:
        n, h, ps = cell[(lo, hi)]
        ratios.append(round(h / ps, 2) if n >= 30 and ps else None)
        if n >= 30:
            print(f"TC    model {lo:.0%}-{hi:.0%}: n={n:5d} said {ps/n:5.1%} happened {h/n:5.1%} ratio {h/ps:.2f}")
    print(f"TC  TAIL[{market!r}] = {ratios}")
PE.read_line = _orig
