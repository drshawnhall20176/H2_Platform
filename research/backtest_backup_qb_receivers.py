"""research/backtest_backup_qb_receivers.py — when a BACKUP QB starts, what happens to his receivers? (Nov 5)
For each team-game: the team's top two targets earners over the previous 4 games (WR/TE). Model-shaped projection =
recency-weighted mean of the player's last 8 games x the pass script (1 + 0.006 x spread). Actual / projected for
targets, receptions and receiving yards, usual QB vs backup QB. Also the OPPONENT defense: sacks and the backup's
passing yards vs the usual starter's average."""
from collections import defaultdict

import nflreadpy as nfl


def wmean(v, h=4.0):
    w = [0.5 ** (i / h) for i in range(len(v))]
    return sum(a * b for a, b in zip(v, w)) / sum(w)


SEASONS = [2022, 2023, 2024, 2025, 2026]
ws = nfl.load_player_stats(SEASONS).to_pandas()
if "season_type" in ws.columns:
    ws = ws[ws["season_type"] == "REG"]
att = "attempts" if "attempts" in ws.columns else "passing_attempts"
sch = nfl.load_schedules(SEASONS).to_pandas()
spread = {}
for r in sch.itertuples(index=False):
    if r.spread_line == r.spread_line:
        spread[(int(r.season), int(r.week), r.home_team)] = -float(r.spread_line)
        spread[(int(r.season), int(r.week), r.away_team)] = float(r.spread_line)

tg = defaultdict(dict)
for r in ws.itertuples(index=False):
    o = int(r.season) * 100 + int(r.week)
    g = tg[r.team].setdefault(o, {"qbs": {}, "rec": {}})
    pos = str(r.position or "")
    if pos == "QB":
        g["qbs"][r.player_id] = float(getattr(r, att) or 0)
    if pos in ("WR", "TE"):
        g["rec"][r.player_id] = (float(r.targets or 0), float(r.receptions or 0), float(r.receiving_yards or 0))

res = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
cnt = defaultdict(int)
for team, gs in tg.items():
    orders = sorted(gs)
    for idx, o in enumerate(orders):
        s, w = divmod(o, 100)
        prev = [gs[x] for x in orders[max(0, idx - 6):idx] if x // 100 == s]
        if len(prev) < 3 or not gs[o]["qbs"]:
            continue
        starters = [max(p["qbs"], key=p["qbs"].get) for p in prev if p["qbs"]]
        qb1 = max(set(starters), key=starters.count)
        if starters.count(qb1) < 3:
            continue
        backup = max(gs[o]["qbs"], key=gs[o]["qbs"].get) != qb1
        sp = spread.get((s, w, team))
        if sp is None:
            continue
        tot = defaultdict(float)
        for x in orders[max(0, idx - 4):idx]:
            for pid, v in gs[x]["rec"].items():
                tot[pid] += v[0]
        for pid in sorted(tot, key=tot.get, reverse=True)[:2]:
            hist = [gs[x]["rec"][pid] for x in reversed(orders[:idx]) if pid in gs[x]["rec"] and x // 100 == s][:8]
            if len(hist) < 3 or pid not in gs[o]["rec"]:
                continue
            script = 1 + 0.006 * sp
            key = "backup QB" if backup else "usual QB"
            cnt[key] += 1
            for j, name in enumerate(("targets", "receptions", "rec yards")):
                res[key][name][0] += gs[o]["rec"][pid][j]
                res[key][name][1] += wmean([h[j] for h in hist]) * script

print(f"{'games':12s} {'n':>6s}  " + "  ".join(f"{m:>18s}" for m in ("targets", "receptions", "rec yards")))
for k in ("usual QB", "backup QB"):
    print(f"{k:12s} {cnt[k]:6d}  " + "  ".join(f"{res[k][m][0] / res[k][m][1] - 1:+18.1%}" for m in ("targets", "receptions", "rec yards")))
