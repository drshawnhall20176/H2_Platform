"""research/backtest_backup_qb_rush.py — when a BACKUP quarterback starts, do the running backs carry more than the
model's formula expects? (Nov 5, Ravens: Lamar out, third-stringer starting.) Read-only.

Model-shaped projection for a team's lead back (most carries over the team's previous 4 games): recency-weighted
mean of his last 8 games' carries x the game-script rule (1 - 0.008 x spread; underdogs run less). Same for the team's
non-QB rush attempts. Compares actual / projected in games the team's established QB started vs games a backup
started, overall and for underdogs."""
import math
from collections import defaultdict

import nflreadpy as nfl


def rw(n, h=4.0):
    return [0.5 ** (i / h) for i in range(n)]


def wmean(v):
    w = rw(len(v))
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

team_games = defaultdict(dict)        # (team) -> {order: {"qb": pid, "rb": {pid: carries}, "rush": n}}
for r in ws.itertuples(index=False):
    o = int(r.season) * 100 + int(r.week)
    g = team_games[r.team].setdefault(o, {"qbs": {}, "rb": {}, "rush": 0.0})
    pos = str(r.position or "")
    car = float(getattr(r, "carries") or 0)
    if pos == "QB":
        g["qbs"][r.player_id] = float(getattr(r, att) or 0)
    else:
        g["rush"] += car
    if pos == "RB":
        g["rb"][r.player_id] = car

res = defaultdict(list)
for team, gs in team_games.items():
    orders = sorted(gs)
    for idx, o in enumerate(orders):
        s, w = divmod(o, 100)
        prev = [gs[x] for x in orders[max(0, idx - 6):idx] if x // 100 == s or (x // 100 == s - 1 and w <= 3)]
        if len(prev) < 3 or not gs[o]["qbs"]:
            continue
        starters = [max(p["qbs"], key=p["qbs"].get) for p in prev if p["qbs"]]
        qb1 = max(set(starters), key=starters.count)
        if starters.count(qb1) < 3:
            continue
        today = max(gs[o]["qbs"], key=gs[o]["qbs"].get)
        backup = today != qb1
        # lead back: most carries over the previous 4 games
        tot = defaultdict(float)
        for p in [gs[x] for x in orders[max(0, idx - 4):idx]]:
            for pid, c in p["rb"].items():
                tot[pid] += c
        if not tot:
            continue
        rb1 = max(tot, key=tot.get)
        hist = [gs[x]["rb"][rb1] for x in reversed(orders[:idx]) if rb1 in gs[x]["rb"]][:8]
        team_hist = [gs[x]["rush"] for x in reversed(orders[:idx])][:8]
        if len(hist) < 3 or rb1 not in gs[o]["rb"]:
            continue
        sp = spread.get((s, w, team))
        if sp is None:
            continue
        script = 1 - 0.008 * sp
        dog = sp >= 3
        key = ("backup QB" if backup else "usual QB") + (" · underdog 3+" if dog else " · other")
        res[key].append((wmean(hist) * script, gs[o]["rb"][rb1], wmean(hist), wmean(team_hist) * script, gs[o]["rush"]))
        res["backup QB · all" if backup else "usual QB · all"].append(res[key][-1])

print(f"{'games':28s} {'n':>5s} {'RB1 actual/proj':>16s} {'(no script)':>12s} {'team runs act/proj':>19s}")
for k in sorted(res):
    rs = res[k]
    rb = sum(a for _, a, _, _, _ in rs) / sum(p for p, *_ in rs) - 1
    rb_ns = sum(a for _, a, _, _, _ in rs) / sum(b for _, _, b, _, _ in rs) - 1
    tm = sum(t for *_, t in rs) / sum(tp for _, _, _, tp, _ in rs) - 1
    print(f"{k:28s} {len(rs):5d} {rb:+16.1%} {rb_ns:+12.1%} {tm:+19.1%}")
