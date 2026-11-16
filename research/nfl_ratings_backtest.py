"""
research/nfl_ratings_backtest.py -- does the ratings model (the one behind every other Game Lab) belong on the NFL
Game Lab? Walk-forward on real results and closing lines from nflverse schedules (no Odds API credits).

Nov 16 result (lam chosen on 2024, then held out on 2025 + 2026 through week 10, 434 games):
  margin MAE 9.99 vs the books' 9.64; total MAE 10.91 vs 10.43; model favourite won 65.0% (books' 66.9%)
  spread: the model's side covered 205-222 (48.0%); totals 222-212 (51.2%). 52.4% breaks even.
  residual SD: margin 12.7, total 13.8 (-> MARGIN_SD 13.0, TOTAL_SD 13.5)
Conclusion: a reasonable projection (within ~0.4 points of the books on margin), NOT a pick source. Shown as previews.
"""
import sys, math, warnings; warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/claude/h2_platform")
import nflreadpy as nfl, numpy as np
import intl_hoops as I, game_picks as GP
I.LEAGUES["NFL"] = {"title": "NFL", "odds_key": "americanfootball_nfl", "min_games": 0, "lam": 3.0, "decay": True, "sd": 13.5}
df = nfl.load_schedules([2023, 2024, 2025, 2026]).to_pandas()
df = df[df.home_score.notna()].sort_values("gameday")
games = [{"date": str(r.gameday)[:10], "home_team": r.home_team, "away_team": r.away_team, "home_points": float(r.home_score),
          "away_points": float(r.away_score), "neutral_site": str(r.location) == "Neutral", "season": int(r.season),
          "spread_line": float(r.spread_line), "total_line": float(r.total_line), "week": int(r.week)} for r in df.itertuples()]
from datetime import date, timedelta
def run(seasons, lam, hfa):
    out = []
    days = sorted({g["date"] for g in games if g["season"] in seasons})
    for d in days:
        since = (date.fromisoformat(d) - timedelta(days=400)).isoformat()
        hist = [g for g in games if since <= g["date"] < d]
        if len(hist) < 150: continue
        r = I.ratings_weighted(hist, I.decay_weights(hist, d, "NFL"), lam, hfa)
        for g in [x for x in games if x["date"] == d and x["season"] in seasons]:
            m = GP.project(r, g["home_team"], g["away_team"], g["neutral_site"])
            if m is None: continue
            out.append({**g, "mm": m[0], "mt": m[1]})
    return out
def report(rows, label):
    act = np.array([g["home_points"] - g["away_points"] for g in rows]); line = np.array([g["spread_line"] for g in rows]); mm = np.array([g["mm"] for g in rows])
    tot = np.array([g["home_points"] + g["away_points"] for g in rows]); tl = np.array([g["total_line"] for g in rows]); mt = np.array([g["mt"] for g in rows])
    edge = mm - line
    def ats(mask):
        w = l = 0
        for a, ln, e, k in zip(act, line, edge, mask):
            if not k or a == ln or e == 0: continue
            if (a > ln) == (e > 0): w += 1
            else: l += 1
        return w, l
    def ou(mask):
        w = l = 0
        for a, ln, e, k in zip(tot, tl, mt - tl, mask):
            if not k or a == ln or e == 0: continue
            if (a > ln) == (e > 0): w += 1
            else: l += 1
        return w, l
    fav = ((mm > 0) == (act > 0))[act != 0]
    print(f"{label}: n={len(rows)}  margin MAE model {np.abs(act-mm).mean():.2f} vs line {np.abs(act-line).mean():.2f} | total MAE model {np.abs(tot-mt).mean():.2f} vs line {np.abs(tot-tl).mean():.2f} | model fav won {fav.mean():.1%} (line fav {(((line>0)==(act>0))[act!=0]).mean():.1%}) | margin resid SD {np.std(act-mm):.1f} total resid SD {np.std(tot-mt):.1f}")
    for lo, hi in ((0, 99), (0, 2), (2, 4), (4, 99)):
        w, l = ats((np.abs(edge) >= lo) & (np.abs(edge) < hi)); print(f"   spread gap {lo}-{hi}: {w}-{l} ({w/max(w+l,1):.1%})", end="")
    print()
    for lo, hi in ((0, 99), (0, 2), (2, 4), (4, 99)):
        w, l = ou((np.abs(mt - tl) >= lo) & (np.abs(mt - tl) < hi)); print(f"   total gap {lo}-{hi}: {w}-{l} ({w/max(w+l,1):.1%})", end="")
    print()
for lam in (3.0, 8.0, 20.0):
    for hfa in ((1.7, 200.0),):
        report(run({2024}, lam, hfa), f"TUNE 2024 lam={lam}")
print("---- held out (lam 3.0 chosen on 2024) ----")
report(run({2025}, 3.0, (1.7, 200.0)), "HELD-OUT 2025")
report(run({2026}, 3.0, (1.7, 200.0)), "HELD-OUT 2026")
report(run({2025, 2026}, 3.0, (1.7, 200.0)), "HELD-OUT 2025-26")
