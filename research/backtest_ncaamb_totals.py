"""
research/backtest_ncaamb_totals.py — do the NCAAMB ratings' projected totals beat the totals line? (Nov 6)

Same walk-forward as backtest_ncaamb_games.py (ratings refitted each game day on the previous ~13 months only, odds
from a 16:00 UTC snapshot before tip). Live this season the total lean was right 57% of 70, 64% at 3+ points off --
but 26 of tonight's 31 qualifying games were Unders, so the questions are: does it hold over two full seasons, does it
hold for Overs AND Unders, in November AND later, and in both seasons separately? Break-even at -110 is 52.4%.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hist_odds as H  # noqa: E402
import intl_hoops as I  # noqa: E402
from backtest_ncaamb_games import SEASONS, SNAP, TEST_FROM, home_side  # noqa: E402

BE = 0.524


def rate(res):
    return f"{sum(res)}/{len(res)} = {sum(res) / max(1, len(res)):.1%}" + (" ✓" if res and sum(res) / len(res) > BE else "")


def main() -> int:
    games = []
    for a, b in SEASONS:
        games += I.ncaamb_range(a, min(b, date.today() - timedelta(days=1)))
    by_day = defaultdict(list)
    for g in games:
        by_day[g["date"]].append(g)
    rows = []
    for d in sorted(x for x in by_day if x >= TEST_FROM.isoformat()):
        prior = [g for g in games if g["date"] < d and (date.fromisoformat(d) - date.fromisoformat(g["date"])).days <= 400]
        if len(prior) < 500:
            continue
        r = I.ratings_weighted(prior, I.decay_weights(prior, d, "NCAAMB"), I.LEAGUES["NCAAMB"]["lam"],
                               I.HFA_PRIOR["NCAAMB"])
        snap = H.snapshot("basketball_ncaab", f"{d}T{SNAP}Z")
        for g in by_day[d]:
            ev = I.match_event(snap, g["home_team"], g["away_team"])
            proj = I.project(r, g["home_team"], g["away_team"], g.get("neutral_site", False))
            if not ev or not proj or home_side(ev, g["home_team"]) is None:
                continue
            to = H.line(ev, "totals", "Over")
            if not to:
                continue
            final = g["home_points"] + g["away_points"]
            if final == to["point"]:
                continue
            rows.append({"date": d, "season": I.season_of("NCAAMB", d), "gap": proj["total"] - to["point"],
                         "over_won": final > to["point"]})
    print(f"{len(rows)} graded totals · {H.usage()}")
    hit = lambda rs: [(r["over_won"] == (r["gap"] > 0)) for r in rs]          # noqa: E731
    print("```")
    print(f"model leans Under on {sum(1 for r in rows if r['gap'] < 0) / len(rows):.0%} of games; "
          f"Overs actually won {sum(r['over_won'] for r in rows) / len(rows):.1%}")
    for lo, hi in ((0, 3), (3, 6), (6, 10), (10, 99), (3, 99)):
        g = [r for r in rows if lo <= abs(r["gap"]) < hi]
        print(f"gap {lo:>2}-{hi:<2}: all {rate(hit(g))} | Unders {rate(hit([r for r in g if r['gap'] < 0]))} "
              f"| Overs {rate(hit([r for r in g if r['gap'] > 0]))}")
    print("-- 3+ off, by season --")
    for s in sorted({r["season"] for r in rows}):
        g = [r for r in rows if r["season"] == s and abs(r["gap"]) >= 3]
        print(f"  {s}: all {rate(hit(g))} | Unders {rate(hit([r for r in g if r['gap'] < 0]))} "
              f"| Overs {rate(hit([r for r in g if r['gap'] > 0]))}")
    print("-- 3+ off, by month --")
    bym = defaultdict(list)
    for r in rows:
        if abs(r["gap"]) >= 3:
            bym[r["date"][5:7]].append(r)
    for m in ("11", "12", "01", "02", "03", "04"):
        g = bym.get(m, [])
        if g:
            print(f"  month {m}: all {rate(hit(g))} | Unders {rate(hit([r for r in g if r['gap'] < 0]))} "
                  f"| Overs {rate(hit([r for r in g if r['gap'] > 0]))}")
    print("```")
    return 0


if __name__ == "__main__":
    sys.exit(main())
