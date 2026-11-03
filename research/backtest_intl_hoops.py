"""
research/backtest_intl_hoops.py — do opponent-adjusted ratings beat EuroLeague / NBL lines? (Nov 3)

Walk-forward: each game day, ratings are fitted on that season's completed games before it (once a league has enough
games), then compared with a historical odds snapshot taken shortly before tip. Reports spreads (by how far the model
is from the line), totals and moneylines, plus how close each projection came. Read-only.
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

SNAP_HOUR = {"EUROLEAGUE": "14:00:00", "NBL": "02:00:00"}       # UTC, a few hours before the usual tip


def load(league):
    if league == "EUROLEAGUE":
        out = []
        for code in ("E2022", "E2023", "E2024", "E2025"):
            g = I.euroleague_season(code)
            print(f"  EuroLeague {code}: {len(g)} games")
            out += g
        return out
    out = []
    for y in (2023, 2024, 2025):
        g = I.nbl_range(date(y, 9, 1), min(date(y + 1, 5, 31), date.today()))
        print(f"  NBL {y}-{y + 1}: {len(g)} games")
        out += g
    return out


def main() -> int:
    for league, cfg in I.LEAGUES.items():
        t0 = datetime.now()
        games = load(league)
        print(f"{league}: {len(games)} completed games ({(datetime.now() - t0).seconds}s)")
        if not games:
            continue
        for g in games:
            g["season"] = I.season_of(league, g["date"])
        by_day = defaultdict(list)
        for g in games:
            by_day[g["date"]].append(g)
        rows = []
        for d in sorted(by_day):
            if d < "2023-01-01":
                continue
            season = I.season_of(league, d)
            prior = [g for g in games if g["season"] == season and g["date"] < d]
            if len(prior) < cfg["min_games"]:
                continue
            r = I.ratings(prior, cfg["lam"])
            snap = H.snapshot(cfg["odds_key"], f"{d}T{SNAP_HOUR[league]}Z", regions="us,eu")
            for g in by_day[d]:
                proj = I.project(r, g["home_team"], g["away_team"], g.get("neutral_site", False))
                ev = I.match_event(snap, g["home_team"], g["away_team"])
                if not proj or not ev:
                    continue
                home_name = ev["home_team"] if I.same_team(ev["home_team"], g["home_team"]) else ev["away_team"]
                away_name = ev["away_team"] if home_name == ev["home_team"] else ev["home_team"]
                sp = H.line(ev, "spreads", home_name)
                to = H.line(ev, "totals", "Over")
                ml = H.h2h(ev, home_name)
                mla = H.h2h(ev, away_name)
                rows.append(dict(g, margin=proj["margin"], total=proj["total"],
                                 line_margin=(-sp["point"]) if sp else None, line_total=to["point"] if to else None,
                                 ml_fair=ml["fair"], ml_best_h=ml["best"], ml_best_a=mla["best"]))
        print(f"{league}: {len(rows)} games with ratings and a pre-game snapshot · {H.usage()}")
        if not rows:
            continue
        print("```")
        act = [r["home_points"] - r["away_points"] for r in rows]
        sp_rows = [r for r in rows if r["line_margin"] is not None]
        if sp_rows:
            mae_m = statistics.mean(abs(r["margin"] - (r["home_points"] - r["away_points"])) for r in sp_rows)
            mae_l = statistics.mean(abs(r["line_margin"] - (r["home_points"] - r["away_points"])) for r in sp_rows)
            print(f"margin miss (n={len(sp_rows)}): model {mae_m:.2f} pts vs the line {mae_l:.2f}")
            for lo in (0, 2, 4, 6, 8):
                for w in (1.0, 0.5):
                    res = []
                    for r in sp_rows:
                        m = w * r["margin"] + (1 - w) * r["line_margin"]
                        edge = m - r["line_margin"]
                        if abs(edge) < lo or abs(edge) < 1e-9:
                            continue
                        diff = (r["home_points"] - r["away_points"]) - r["line_margin"]
                        if diff == 0:
                            continue
                        res.append((diff > 0) == (edge > 0))
                    if res:
                        print(f"spread, model {lo}+ pts off the line (weight {w:.1f}): {sum(res)}/{len(res)} = "
                              f"{sum(res) / len(res):.1%}")
        tt = [r for r in rows if r["line_total"] is not None]
        if tt:
            print(f"total miss (n={len(tt)}): model "
                  f"{statistics.mean(abs(r['total'] - r['home_points'] - r['away_points']) for r in tt):.2f} vs the line "
                  f"{statistics.mean(abs(r['line_total'] - r['home_points'] - r['away_points']) for r in tt):.2f}")
            for lo in (0, 3, 6, 9):
                res = []
                for r in tt:
                    edge = r["total"] - r["line_total"]
                    diff = r["home_points"] + r["away_points"] - r["line_total"]
                    if abs(edge) < max(lo, 1e-9) or diff == 0:
                        continue
                    res.append((diff > 0) == (edge > 0))
                if res:
                    print(f"total, model {lo}+ pts off: {sum(res)}/{len(res)} = {sum(res) / len(res):.1%}")
        ml = [r for r in rows if r["ml_fair"] is not None]
        if ml:
            for edge in (0.03, 0.05, 0.08):
                bets = []
                for r in ml:
                    p = I.win_prob(r["margin"])
                    home_won = r["home_points"] > r["away_points"]
                    for pp, mk, price, won in ((p, r["ml_fair"], r["ml_best_h"], home_won),
                                               (1 - p, 1 - r["ml_fair"], r["ml_best_a"], not home_won)):
                        if price is not None and pp - mk >= edge:
                            bets.append((H.decimal(price) - 1) if won else -1)
                if bets:
                    print(f"moneyline edge >= {edge:.0%}: n={len(bets)} hit {sum(1 for b in bets if b > 0) / len(bets):.1%} "
                          f"profit/$1 {sum(bets) / len(bets):+.1%} (best price)")
        by_season = defaultdict(list)
        for r in sp_rows:
            edge = r["margin"] - r["line_margin"]
            diff = (r["home_points"] - r["away_points"]) - r["line_margin"]
            if abs(edge) >= 4 and diff != 0:
                by_season[r["season"]].append((diff > 0) == (edge > 0))
        for s, res in sorted(by_season.items()):
            print(f"  season {s}: spread 4+ off {sum(res)}/{len(res)} = {sum(res) / len(res):.1%}")
        print("```")
    return 0


if __name__ == "__main__":
    sys.exit(main())
