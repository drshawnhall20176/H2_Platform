"""research/backtest_game_lab.py — NFL Game Lab vs the closing line (2024-2026 regular season).

Reproduces Game Lab's projection for every game from games BEFORE it (same season): each team's last-4 scoring
average x the opponent's season points-allowed / league average (the odds-ratio blend), no home field. Then
compares against nflverse's closing spread / total / moneyline:
  * MAE of the projected margin and total vs the actual, next to the closing line's own MAE;
  * ATS / O-U hit rate when the model disagrees with the closing number by 1.5+, 3+, 5+ points;
  * moneyline log loss vs the closing no-vig probability.
Variants: + home field, season-long averages, shrink toward the market."""
import math
from collections import defaultdict

import nflreadpy as nfl

SD_MARGIN, SD_TOTAL = 13.5, 13.0          # historical NFL sd of margin / total around a good projection


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def no_vig(ml_home, ml_away):
    def imp(a):
        return 100 / (a + 100) if a > 0 else -a / (-a + 100)
    h, a = imp(ml_home), imp(ml_away)
    return h / (h + a)


sch = nfl.load_schedules([2024, 2025, 2026]).to_pandas()
sch = sch[(sch["game_type"] == "REG")]
games = sch.dropna(subset=["home_score", "away_score"]).sort_values(["season", "week"])
res = defaultdict(list)
for season, g_season in games.groupby("season"):
    g_season = g_season.sort_values("week")
    for row in g_season.itertuples(index=False):
        prior = g_season[g_season["week"] < row.week]
        if prior.empty or row.week < 4:
            continue
        lg = (prior["home_score"].sum() + prior["away_score"].sum()) / (2 * len(prior))

        def scored(team, n=None):
            pts = [(r.week, r.home_score if r.home_team == team else r.away_score) for r in prior.itertuples()
                   if team in (r.home_team, r.away_team)]
            pts = [p for _, p in sorted(pts)]
            pts = pts[-n:] if n else pts
            return sum(pts) / len(pts) if pts else None

        def allowed(team):
            pts = [r.away_score if r.home_team == team else r.home_score for r in prior.itertuples()
                   if team in (r.home_team, r.away_team)]
            return sum(pts) / len(pts) if pts else None
        h, a = row.home_team, row.away_team
        hs4, as4, hss, ass, ha, aa = scored(h, 4), scored(a, 4), scored(h), scored(a), allowed(h), allowed(a)
        if None in (hs4, as4, ha, aa) or row.spread_line != row.spread_line or row.total_line != row.total_line:
            continue
        margin, total = row.home_score - row.away_score, row.home_score + row.away_score
        line_margin, line_total = row.spread_line, row.total_line     # spread_line: home favored by (+)
        p_mkt = no_vig(row.home_moneyline, row.away_moneyline) if row.home_moneyline == row.home_moneyline else None
        variants = {
            "Game Lab (current)": (hs4 * aa / lg, as4 * ha / lg),
            "+ home field 1.8": (hs4 * aa / lg + 0.9, as4 * ha / lg - 0.9),
            "season avgs + HFA": (hss * aa / lg + 0.9, ass * ha / lg - 0.9),
        }
        for name, (hp, ap) in variants.items():
            pm, pt = hp - ap, hp + ap
            res[name].append((pm, pt, margin, total, line_margin, line_total, p_mkt))
            for w in (0.25, 0.5):
                res[f"{name} x{w} + market"].append((w * pm + (1 - w) * line_margin, w * pt + (1 - w) * line_total,
                                                    margin, total, line_margin, line_total, p_mkt))
print(f"games: {len(res['Game Lab (current)'])}")
L = res["Game Lab (current)"]
print(f"closing line   margin MAE {sum(abs(m - lm) for _, _, m, _, lm, _, _ in L) / len(L):.2f}   "
      f"total MAE {sum(abs(t - lt) for _, _, _, t, _, lt, _ in L) / len(L):.2f}")
for name, rs in res.items():
    mae_m = sum(abs(m - pm) for pm, _, m, _, _, _, _ in rs) / len(rs)
    mae_t = sum(abs(t - pt) for _, pt, _, t, _, _, _ in rs) / len(rs)
    out = [f"{name:34s} margin MAE {mae_m:.2f}  total MAE {mae_t:.2f}"]
    for thr in (1.5, 3, 5):
        ats = [(1 if (m - lm) * (pm - lm) > 0 else 0) for pm, _, m, _, lm, _, _ in rs if abs(pm - lm) >= thr and m != lm]
        ou = [(1 if (t - lt) * (pt - lt) > 0 else 0) for _, pt, _, t, _, lt, _ in rs if abs(pt - lt) >= thr and t != lt]
        out.append(f"| {thr:g}+: ATS {sum(ats) / max(len(ats), 1):.1%} (n{len(ats)}) O/U {sum(ou) / max(len(ou), 1):.1%} (n{len(ou)})")
    ll_m = [(-math.log(phi(pm / SD_MARGIN)) if m > 0 else -math.log(1 - phi(pm / SD_MARGIN)))
            for pm, _, m, _, _, _, pk in rs if m != 0 and pk is not None]
    out.append(f"| ML logloss {sum(ll_m) / max(len(ll_m), 1):.4f}")
    print("  ".join(out))
mk = [(-math.log(pk) if m > 0 else -math.log(1 - pk)) for _, _, m, _, _, _, pk in L if m != 0 and pk is not None]
print(f"closing moneyline logloss {sum(mk) / len(mk):.4f}  (breakeven ATS/O-U at -110: 52.4%)")
