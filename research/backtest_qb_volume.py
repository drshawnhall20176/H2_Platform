"""research/backtest_qb_volume.py — where does the QB pass-attempt projection's upward bias come from?
Projects each starting QB's attempts from prior games only: base = recency-weighted mean of his last 8 games;
then x the opponent's attempts-allowed factor and/or x the spread script (+0.6% per point of underdog), and reports
bias (actual / projected - 1) and mean absolute error for each."""
import math
from collections import defaultdict
import nflreadpy as nfl

def rw(n, h=4.0): return [0.5 ** (i / h) for i in range(n)]
def wmean(v): w = rw(len(v)); return sum(a * b for a, b in zip(v, w)) / sum(w)

ws = nfl.load_player_stats([2024, 2025, 2026]).to_pandas()
ws = ws[(ws["position"] == "QB") & (ws["season_type"] == "REG")] if "season_type" in ws.columns else ws[ws["position"] == "QB"]
att_col = "attempts" if "attempts" in ws.columns else "passing_attempts"
sch = nfl.load_schedules([2024, 2025, 2026]).to_pandas()
spread = {}
for r in sch.itertuples(index=False):
    if r.spread_line == r.spread_line:
        spread[(r.season, r.week, r.home_team)] = -float(r.spread_line)    # home team's spread (negative = favored)
        spread[(r.season, r.week, r.away_team)] = float(r.spread_line)
games = sorted(((int(r.season) * 100 + int(r.week), r.player_id, r.team, r.opponent_team, float(getattr(r, att_col) or 0))
                for r in ws.itertuples(index=False)), key=lambda t: t[0])
# starters only: 15+ attempts
games = [g for g in games if g[4] >= 15]
by_qb = defaultdict(list)
allowed = defaultdict(list)
for o, p, t, opp, a in games:
    by_qb[p].append((o, a))
    allowed[opp].append((o, a))
league = defaultdict(list)
res = defaultdict(list)
for o, p, t, opp, a in games:
    s, w = divmod(o, 100)
    if not ((s == 2025 and 4 <= w <= 18) or (s == 2026 and 3 <= w <= 9)):
        continue
    hist = [x for oo, x in reversed(by_qb[p]) if oo < o][:8]
    dh = [x for oo, x in reversed(allowed[opp]) if oo < o][:8]
    lg = [x for oo, _p, _t, _o, x in games if o - 100 <= oo < o]
    if len(hist) < 3 or len(dh) < 3 or not lg:
        continue
    base = wmean(hist)
    f = wmean(dh) / (sum(lg) / len(lg))
    sp = spread.get((s, w, t))
    sc = 1 + 0.006 * sp if sp is not None else 1.0
    for name, proj in (("base", base), ("base x defense", base * f), ("base x script", base * sc),
                       ("base x defense x script (current shape)", base * f * sc),
                       ("base x defense^0.5", base * f ** 0.5), ("base x defense^0.5 x script", base * f ** 0.5 * sc),
                       ("base x script x2", base * (1 + 0.012 * sp) if sp is not None else base)):
        res[name].append((proj, a))
for name, rs in res.items():
    bias = sum(a for _, a in rs) / sum(p for p, _ in rs) - 1
    mae = sum(abs(a - p) for p, a in rs) / len(rs)
    print(f"{name:42s} n={len(rs)}  actual vs projected {bias:+.1%}  MAE {mae:.2f}")
