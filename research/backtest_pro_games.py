"""
research/backtest_pro_games.py — do recency-weighted ratings beat NBA / NHL lines? (Nov 3)

Same walk-forward as the college backtest (backtest_ncaamb_games.py): ratings refitted each game day on the previous
~13 months (recency weights, last season discounted), against a historical odds snapshot at 18:00 UTC. Reports
spreads / puck lines and totals by GAP BAND (not cumulative -- the college run showed cumulative numbers hide where
the edge is), and moneylines at the MEDIAN book price (not the best -- best prices across many books were stale
outliers that made moneylines look far better than they are). Read-only.
"""
from __future__ import annotations

import os
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hist_odds as H  # noqa: E402
import intl_hoops as I  # noqa: E402

SEASONS = {"NBA": ((date(2023, 10, 20), date(2024, 6, 20)), (date(2024, 10, 20), date(2025, 6, 25)),
                   (date(2025, 10, 20), date(2026, 6, 25))),
           "NHL": ((date(2023, 10, 8), date(2024, 6, 25)), (date(2024, 10, 3), date(2025, 6, 25)),
                   (date(2025, 10, 6), date(2026, 6, 25)))}
TEST_FROM = date(2024, 10, 20)
BANDS = {"NBA": (0, 2, 4, 6, 8, 10, 14, 99), "NHL": (0, 0.25, 0.5, 0.75, 1.0, 1.5, 99)}
TOTAL_BANDS = {"NBA": (0, 3, 6, 9, 12, 99), "NHL": (0, 0.25, 0.5, 0.75, 1.0, 99)}


def med_price(ev, name):
    ps = []
    for b in ev.get("bookmakers") or []:
        for m in b.get("markets") or []:
            if m.get("key") == "h2h":
                for o in m.get("outcomes") or []:
                    if o.get("name") == name and o.get("price") is not None:
                        ps.append(H.decimal(o["price"]))
    ps = [p for p in ps if p]
    return statistics.median(ps) if ps else None


def band_rows(rows, key_gap, key_win, bands):
    out = []
    for lo, hi in zip(bands, bands[1:]):
        res = [r[key_win] for r in rows if r[key_win] is not None and lo <= abs(r[key_gap]) < hi]
        if res:
            out.append(f"  gap {lo:g}-{hi if hi < 99 else '+'}: {sum(res)}/{len(res)} = {sum(res) / len(res):.1%}")
    return out


def main() -> int:
    for lg in ("NBA", "NHL"):
        t0 = datetime.now()
        games = []
        for a, b in SEASONS[lg]:
            g = I.espn_range(lg, a, min(b, date.today() - timedelta(days=1)))
            print(f"  {lg} {a.year}: {len(g)} games")
            games += g
        print(f"{lg}: {len(games)} games crawled in {(datetime.now() - t0).seconds}s")
        by_day = defaultdict(list)
        for g in games:
            by_day[g["date"]].append(g)
        rows = []
        for d in sorted(x for x in by_day if x >= TEST_FROM.isoformat()):
            prior = [g for g in games if g["date"] < d and (date.fromisoformat(d) - date.fromisoformat(g["date"])).days <= 400]
            if len(prior) < 300:
                continue
            r = I.ratings_weighted(prior, I.decay_weights(prior, d, lg), I.LEAGUES[lg]["lam"])
            snap = H.snapshot(I.LEAGUES[lg]["odds_key"], f"{d}T18:00:00Z")
            for g in by_day[d]:
                ev = I.match_event(snap, g["home_team"], g["away_team"])
                proj = I.project(r, g["home_team"], g["away_team"], g.get("neutral_site", False))
                if not ev or not proj:
                    continue
                h = ev["home_team"] if I.find_team([ev["home_team"]], g["home_team"]) else ev["away_team"]
                a = ev["away_team"] if h == ev["home_team"] else ev["home_team"]
                sp, to, ml = H.line(ev, "spreads", h), H.line(ev, "totals", "Over"), H.h2h(ev, h)
                act_m = g["home_points"] - g["away_points"]
                act_t = g["home_points"] + g["away_points"]
                row = {"date": d, "margin": proj["margin"], "total": proj["total"], "ml_fair": ml["fair"],
                       "p": I.win_prob(proj["margin"], league=lg), "home_won": act_m > 0, "act_m": act_m,
                       "med_h": med_price(ev, h), "med_a": med_price(ev, a),
                       "sp_gap": None, "sp_win": None, "to_gap": None, "to_win": None}
                if sp:
                    lm = -sp["point"]
                    row["sp_gap"] = proj["margin"] - lm
                    diff = act_m - lm
                    row["sp_win"] = None if diff == 0 or row["sp_gap"] == 0 else ((diff > 0) == (row["sp_gap"] > 0))
                    row["line_m"] = lm
                if to:
                    row["to_gap"] = proj["total"] - to["point"]
                    diff = act_t - to["point"]
                    row["to_win"] = None if diff == 0 or row["to_gap"] == 0 else ((diff > 0) == (row["to_gap"] > 0))
                    row["line_t"] = to["point"]
                rows.append(row)
        print(f"{lg}: {len(rows)} games with ratings and a pre-game line · {H.usage()}")
        print("```")
        sp = [r for r in rows if r["sp_gap"] is not None]
        if sp:
            print(f"margin miss (n={len(sp)}): model {statistics.mean(abs(r['margin'] - r['act_m']) for r in sp):.2f} vs "
                  f"the line {statistics.mean(abs(r['line_m'] - r['act_m']) for r in sp):.2f}")
            print("spread / puck line by gap band (the model's side):")
            print("\n".join(band_rows(sp, "sp_gap", "sp_win", BANDS[lg])))
            bys = defaultdict(list)
            for r in sp:
                bys[I.season_of(lg, r["date"])].append(r)
            big = BANDS[lg][-3]
            for s, rs in sorted(bys.items()):
                res = [r["sp_win"] for r in rs if r["sp_win"] is not None and abs(r["sp_gap"]) >= big]
                if res:
                    print(f"  season {s}, gap {big:g}+: {sum(res)}/{len(res)} = {sum(res) / len(res):.1%}")
        tt = [r for r in rows if r["to_gap"] is not None]
        if tt:
            print("total by gap band:")
            print("\n".join(band_rows(tt, "to_gap", "to_win", TOTAL_BANDS[lg])))
        ml = [r for r in rows if r["ml_fair"] is not None and r["med_h"] and r["med_a"]]
        for lo, hi in ((0.03, 0.06), (0.06, 0.10), (0.10, 0.99)):
            bets = []
            for r in ml:
                for pp, mk, dec, won in ((r["p"], r["ml_fair"], r["med_h"], r["home_won"]),
                                         (1 - r["p"], 1 - r["ml_fair"], r["med_a"], not r["home_won"])):
                    if lo <= pp - mk < hi:
                        bets.append((dec - 1) if won else -1)
            if bets:
                print(f"moneyline edge {lo:.0%}-{hi:.0%} (median price): n={len(bets)} hit "
                      f"{sum(1 for b in bets if b > 0) / len(bets):.1%} profit/$1 {sum(bets) / len(bets):+.1%}")
        print("```")
    return 0


if __name__ == "__main__":
    sys.exit(main())
