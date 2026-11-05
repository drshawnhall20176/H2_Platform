"""research/backtest_nfl_lines_defense.py — what injured OFFENSIVE LINEMEN and injured TOP DEFENDERS do (Nov 5).
Snap counts (2022-26) mark each team's regulars from its previous 4 games; a regular with no snaps today is "out".
Outcomes vs a model-shaped baseline (the team's own recent average x the spread script):
  OL out (0 / 1 / 2+ of the usual five):  sacks taken, QB passing yards, running backs' rush yards and yards/carry
  defense missing edge rushers (0 / 1+ of top two) -> the OPPONENT's sacks taken and passing yards
  defense missing cornerbacks (0 / 1+ of top two)  -> the OPPONENT's passing yards and top receiver's yards"""
from collections import defaultdict

import nflreadpy as nfl

SEASONS = [2022, 2023, 2024, 2025, 2026]


def wmean(v, h=4.0):
    w = [0.5 ** (i / h) for i in range(len(v))]
    return sum(a * b for a, b in zip(v, w)) / sum(w)


snaps = nfl.load_snap_counts(SEASONS).to_pandas()
ws = nfl.load_player_stats(SEASONS).to_pandas()
if "season_type" in ws.columns:
    ws = ws[ws["season_type"] == "REG"]
if "game_type" in snaps.columns:
    snaps = snaps[snaps["game_type"] == "REG"]
sack_col = next(c for c in ("sacks_suffered", "sacks", "passing_sacks") if c in ws.columns)
print("sack column:", sack_col)
sch = nfl.load_schedules(SEASONS).to_pandas()
spread = {}
for r in sch.itertuples(index=False):
    if r.spread_line == r.spread_line:
        spread[(int(r.season), int(r.week), r.home_team)] = -float(r.spread_line)
        spread[(int(r.season), int(r.week), r.away_team)] = float(r.spread_line)

# team-game outcomes
team = defaultdict(lambda: {"sacks": 0.0, "pass_yds": 0.0, "rb_yds": 0.0, "rb_car": 0.0, "wr": {}})
opp_of = {}
for r in ws.itertuples(index=False):
    k = (int(r.season), int(r.week), r.team)
    opp_of[k] = r.opponent_team
    t = team[k]
    pos = str(r.position or "")
    if pos == "QB":
        t["sacks"] += float(getattr(r, sack_col) or 0)
        t["pass_yds"] += float(r.passing_yards or 0)
    if pos == "RB":
        t["rb_yds"] += float(r.rushing_yards or 0)
        t["rb_car"] += float(r.carries or 0)
    if pos in ("WR", "TE"):
        t["wr"][r.player_id] = (float(r.targets or 0), float(r.receiving_yards or 0))

# regulars and who's out, per team-game
OL = {"T", "G", "C", "OL", "OT", "OG"}
EDGE = {"DE", "OLB", "EDGE"}
CB = {"CB"}
by_tg = defaultdict(dict)
for r in snaps.itertuples(index=False):
    k = (int(r.season), int(r.week), r.team)
    by_tg[k][r.player] = (str(r.position or ""), float(r.offense_pct or 0), float(r.defense_pct or 0))
order = defaultdict(list)
for (s, w, t) in by_tg:
    order[t].append((s, w))
missing = {}
for t, sw in order.items():
    sw.sort()
    for i, (s, w) in enumerate(sw):
        prev = [by_tg[(s2, w2, t)] for s2, w2 in sw[max(0, i - 4):i] if s2 == s]
        if len(prev) < 3:
            continue
        def regulars(group, col, need, top):
            pct = defaultdict(list)
            for g in prev:
                for name, (pos, o, d) in g.items():
                    if pos in group:
                        pct[name].append(o if col == "o" else d)
            reg = [(sum(v) / len(prev), n) for n, v in pct.items() if len(v) >= 2 and sum(v) / len(prev) >= need]
            return [n for _, n in sorted(reg, reverse=True)[:top]]
        today = by_tg[(s, w, t)]
        def out(names, col):
            return sum(1 for n in names if n not in today or (today[n][1] if col == "o" else today[n][2]) <= 0)
        missing[(s, w, t)] = {"ol": out(regulars(OL, "o", 0.6, 5), "o"), "edge": out(regulars(EDGE, "d", 0.5, 2), "d"),
                              "cb": out(regulars(CB, "d", 0.6, 2), "d")}

# baselines and comparisons
hist = defaultdict(list)
for k in sorted(team, key=lambda k: (k[0], k[1])):
    hist[k[2]].append(k)
acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
cnt = defaultdict(int)
for t, keys in hist.items():
    for i, k in enumerate(keys):
        s, w, _ = k
        prev = [team[x] for x in keys[max(0, i - 8):i][::-1] if x[0] == s]
        sp = spread.get(k)
        if len(prev) < 3 or sp is None:
            continue
        cur = team[k]
        base = {"sacks": wmean([p["sacks"] for p in prev]), "pass_yds": wmean([p["pass_yds"] for p in prev]) * (1 + 0.006 * sp),
                "rb_yds": wmean([p["rb_yds"] for p in prev]) * (1 - 0.008 * sp), "rb_car": wmean([p["rb_car"] for p in prev]) * (1 - 0.008 * sp)}
        # top receiver by targets over previous games
        tg = defaultdict(float)
        for p in prev[:4]:
            for pid, (a, _) in p["wr"].items():
                tg[pid] += a
        wr1 = max(tg, key=tg.get) if tg else None
        wr1_base = wmean([p["wr"][wr1][1] for p in prev if wr1 in p["wr"]]) * (1 + 0.006 * sp) if wr1 and \
            sum(1 for p in prev if wr1 in p["wr"]) >= 3 else None
        m_own = missing.get(k)
        opp = opp_of.get(k)
        m_def = missing.get((s, w, opp)) if opp else None
        if m_own:
            g = "OL out: " + ("0" if m_own["ol"] == 0 else ("1" if m_own["ol"] == 1 else "2+"))
            cnt[g] += 1
            for st in ("sacks", "pass_yds", "rb_yds", "rb_car"):
                acc[g][st][0] += cur[st]
                acc[g][st][1] += base[st]
        if m_def:
            for kind in ("edge", "cb"):
                g = f"opp {kind} out: " + ("0" if m_def[kind] == 0 else "1+")
                cnt[g] += 1
                for st in ("sacks", "pass_yds"):
                    acc[g][st][0] += cur[st]
                    acc[g][st][1] += base[st]
                if wr1_base and wr1 in cur["wr"]:
                    acc[g]["wr1_yds"][0] += cur["wr"][wr1][1]
                    acc[g]["wr1_yds"][1] += wr1_base

for g in sorted(acc):
    parts = []
    for st, (a, b) in acc[g].items():
        parts.append(f"{st} {a / b - 1:+.1%}")
    if "rb_yds" in acc[g] and acc[g]["rb_car"][0]:
        ypc_a = acc[g]["rb_yds"][0] / acc[g]["rb_car"][0]
        ypc_b = acc[g]["rb_yds"][1] / acc[g]["rb_car"][1]
        parts.append(f"rb yds/carry {ypc_a / ypc_b - 1:+.1%}")
    print(f"{g:18s} n={cnt[g]:5d}  " + "  ".join(parts))
