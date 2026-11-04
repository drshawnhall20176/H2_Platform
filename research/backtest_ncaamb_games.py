"""
research/backtest_ncaamb_games.py — do recency-weighted ratings beat college basketball lines? (Nov 3)

Walk-forward over the 2024-25 and 2025-26 seasons: each game day the ratings are refitted on every D-I game in the
previous ~13 months (recency weights, last season discounted: intl_hoops.decay_weights), then compared with a
historical odds snapshot at 16:00 UTC (late morning ET, before nearly every tip). Reports spreads by how far the model
is from the line, by month (early season is where college lines are softest and the model is weakest), totals and
moneylines. Read-only.
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

SEASONS = ((date(2023, 11, 1), date(2024, 4, 10)), (date(2024, 11, 1), date(2025, 4, 10)),
           (date(2025, 11, 1), date(2026, 4, 10)))
TEST_FROM = date(2024, 11, 1)
SNAP = "16:00:00"


def home_side(ev, espn_home):
    """The odds event's name for ESPN's home team, or None when it can't be told for certain."""
    k = I._key(espn_home)
    if I._key(ev["home_team"]) == k and I._key(ev["away_team"]) != k:
        return ev["home_team"]
    if I._key(ev["away_team"]) == k and I._key(ev["home_team"]) != k:
        return ev["away_team"]
    fh = I.find_team([ev["home_team"]], espn_home) is not None
    fa = I.find_team([ev["away_team"]], espn_home) is not None
    if fh == fa:
        return None
    return ev["home_team"] if fh else ev["away_team"]


def main() -> int:
    skipped = defaultdict(int)
    t0 = datetime.now()
    games = []
    for a, b in SEASONS:
        g = I.ncaamb_range(a, min(b, date.today() - timedelta(days=1)))
        print(f"  {a.year}-{b.year}: {len(g)} D-I games")
        games += g
    print(f"{len(games)} games crawled in {(datetime.now() - t0).seconds}s")
    by_day = defaultdict(list)
    for g in games:
        by_day[g["date"]].append(g)
    rows = []
    days = sorted(d for d in by_day if d >= TEST_FROM.isoformat())
    for d in days:
        prior = [g for g in games if g["date"] < d and (date.fromisoformat(d) - date.fromisoformat(g["date"])).days <= 400]
        if len(prior) < 500:
            continue
        r = I.ratings_weighted(prior, I.decay_weights(prior, d, "NCAAMB"), I.LEAGUES["NCAAMB"]["lam"],
                               I.HFA_PRIOR["NCAAMB"])
        snap = H.snapshot("basketball_ncaab", f"{d}T{SNAP}Z")
        for g in by_day[d]:
            ev = I.match_event(snap, g["home_team"], g["away_team"])
            proj = I.project(r, g["home_team"], g["away_team"], g.get("neutral_site", False))
            if not ev or not proj:
                continue
            h_ev = home_side(ev, g["home_team"])
            if h_ev is None:                                   # Nov 4: never guess which side is home -- a flip
                skipped["orientation"] += 1                    # turns the line inside out and fakes a huge "edge"
                continue
            a_ev = ev["away_team"] if h_ev == ev["home_team"] else ev["home_team"]
            sp, to = H.line(ev, "spreads", h_ev), H.line(ev, "totals", "Over")
            ml, mla = H.h2h(ev, h_ev), H.h2h(ev, a_ev)
            rows.append(dict(g, margin=proj["margin"], total=proj["total"],
                             line_margin=(-sp["point"]) if sp else None, line_total=to["point"] if to else None,
                             ml_fair=ml["fair"], ml_best_h=ml["best"], ml_best_a=mla["best"],
                             n_prior_cur=sum(1 for x in prior if I.season_of("NCAAMB", x["date"]) == I.season_of("NCAAMB", d))))
        if len(rows) and len(rows) % 1000 < len(by_day[d]):
            print(f"  ... {d}: {len(rows)} priced games, {H.usage()}")
    print(f"{len(rows)} games with ratings and a pre-game line · {H.usage()} · skipped (home side unclear): "
          f"{skipped['orientation']}")
    if not rows:
        return 0

    def ats(rs, lo, w=1.0):
        res = []
        for r in rs:
            if r["line_margin"] is None:
                continue
            m = w * r["margin"] + (1 - w) * r["line_margin"]
            edge = m - r["line_margin"]
            diff = (r["home_points"] - r["away_points"]) - r["line_margin"]
            if abs(edge) < max(lo, 1e-9) or diff == 0:
                continue
            res.append((diff > 0) == (edge > 0))
        return res

    print("```")
    sp = [r for r in rows if r["line_margin"] is not None]
    print(f"margin miss (n={len(sp)}): model "
          f"{statistics.mean(abs(r['margin'] - r['home_points'] + r['away_points']) for r in sp):.2f} pts vs the line "
          f"{statistics.mean(abs(r['line_margin'] - r['home_points'] + r['away_points']) for r in sp):.2f}")
    for lo in (0, 2, 3, 4, 5, 6, 8, 10):
        a, b = ats(sp, lo), ats(sp, lo, 0.5)
        print(f"spread, model {lo:>2}+ pts off: {sum(a)}/{len(a)} = {sum(a) / max(1, len(a)):.1%}"
              f"   (half model/half line: {sum(b)}/{len(b)} = {sum(b) / max(1, len(b)):.1%})")
    print("-- by month, model 4+ off --")
    bym = defaultdict(list)
    for r in sp:
        bym[r["date"][:7]].append(r)
    for m in sorted(bym):
        a = ats(bym[m], 4)
        print(f"  {m}: {sum(a)}/{len(a)} = {sum(a) / max(1, len(a)):.1%}")
    print("-- by season, model 4+ / 6+ off --")
    bys = defaultdict(list)
    for r in sp:
        bys[I.season_of("NCAAMB", r["date"])].append(r)
    for s, rs in sorted(bys.items()):
        a, b = ats(rs, 4), ats(rs, 6)
        print(f"  {s}: 4+ {sum(a)}/{len(a)} = {sum(a) / max(1, len(a)):.1%} · 6+ {sum(b)}/{len(b)} = {sum(b) / max(1, len(b)):.1%}")
    tt = [r for r in rows if r["line_total"] is not None]
    print(f"total miss (n={len(tt)}): model "
          f"{statistics.mean(abs(r['total'] - r['home_points'] - r['away_points']) for r in tt):.2f} vs the line "
          f"{statistics.mean(abs(r['line_total'] - r['home_points'] - r['away_points']) for r in tt):.2f}")
    for lo in (0, 3, 5, 8):
        res = []
        for r in tt:
            e = r["total"] - r["line_total"]
            d = r["home_points"] + r["away_points"] - r["line_total"]
            if abs(e) >= max(lo, 1e-9) and d != 0:
                res.append((d > 0) == (e > 0))
        print(f"total, model {lo}+ pts off: {sum(res)}/{len(res)} = {sum(res) / max(1, len(res)):.1%}")
    ml = [r for r in rows if r["ml_fair"] is not None]
    for edge in (0.03, 0.05, 0.08):
        bets = []
        for r in ml:
            p = I.win_prob(r["margin"])
            hw = r["home_points"] > r["away_points"]
            for pp, mk, price, won in ((p, r["ml_fair"], r["ml_best_h"], hw), (1 - p, 1 - r["ml_fair"], r["ml_best_a"], not hw)):
                if price is not None and pp - mk >= edge:
                    bets.append((H.decimal(price) - 1) if won else -1)
        if bets:
            print(f"moneyline edge >= {edge:.0%}: n={len(bets)} hit {sum(1 for b in bets if b > 0) / len(bets):.1%} "
                  f"profit/$1 {sum(bets) / len(bets):+.1%}")
    print("```")
    return 0


if __name__ == "__main__":
    sys.exit(main())
