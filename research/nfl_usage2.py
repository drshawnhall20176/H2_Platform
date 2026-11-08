"""Nov 8: (1) receivers' targets: per-game vs per-snap x recent snap share (like defenders' tackles);
(2) defenders' tackles vs the OPPONENT's plays per game (pace). NFL 2023-2026, each game predicted from earlier games."""
import math
from collections import defaultdict
import nflreadpy as nfl
import pandas as pd

seasons = [2023, 2024, 2025, 2026]
snaps = pd.concat([nfl.load_snap_counts([s]).to_pandas() for s in seasons], ignore_index=True)
snaps = snaps[snaps["game_type"] == "REG"]
players = nfl.load_players().to_pandas()
idmap = dict(zip(players["pfr_id"], players["gsis_id"]))
snaps["gsis"] = snaps["pfr_player_id"].map(idmap)
ps = nfl.load_player_stats(seasons).to_pandas()
ps = ps[ps["season_type"] == "REG"]
W = [0.30, 0.25, 0.20, 0.15, 0.10]
def wmean(xs):
    xs = list(xs)[::-1][:5]; ww = W[:len(xs)]
    return sum(a * b for a, b in zip(xs, ww)) / sum(ww)

# ---- (1) receivers
st = ps[["player_id", "season", "week", "targets", "receptions", "receiving_yards"]].rename(columns={"player_id": "gsis"})
df = snaps[snaps["offense_snaps"].fillna(0) > 0].merge(st, on=["gsis", "season", "week"], how="inner")
df = df[df["position"].isin(["WR", "TE", "RB"])].sort_values(["pfr_player_id", "season", "week"])
res = defaultdict(lambda: [0, 0.0, 0.0, 0, 0])
for pid, g in df.groupby("pfr_player_id"):
    rows = g.to_dict("records")
    for i in range(3, len(rows)):
        hist, cur = rows[max(0, i - 8):i], rows[i]
        sn = [h["offense_snaps"] for h in hist]; pct = [h["offense_pct"] for h in hist]
        if wmean([h["targets"] for h in hist]) < 2:
            continue
        role = pct[-1] - sum(pct[-6:-1]) / max(1, len(pct[-6:-1]))
        bucket = "role up" if role >= 0.15 else "role down" if role <= -0.15 else "steady"
        for stat in ("targets", "receptions", "receiving_yards"):
            v = [h[stat] for h in hist]
            pg = wmean(v)
            psn = sum(v[-6:]) / max(1, sum(sn[-6:])) * wmean(sn[-3:])
            for mode in ("blend", "down-only"):
                use_snap = mode == "blend" and bucket != "role up" or mode == "down-only" and bucket == "role down"
                new = 0.5 * pg + 0.5 * psn if use_snap else pg
                y = cur[stat]
                line = math.floor(pg) + 0.5 if stat != "receiving_yards" else round(pg) + 0.5
                for k in ((stat, mode, "all"), (stat, mode, bucket), (stat, mode, int(cur["season"]))):
                    r = res[k]; r[0] += 1; r[1] += abs(pg - y); r[2] += abs(new - y)
                    if (pg > line) != (new > line):
                        r[3] += 1; r[4] += (y > line) == (new > line)
for k, (n, a, b, f, w) in sorted(res.items(), key=lambda kv: str(kv[0])):
    print("NU REC", k, f"n={n} MAE per-game {a/n:.3f} new {b/n:.3f} ({(a-b)/a:+.1%}) | side flips {f} new right {w/max(1,f):.1%}")

# ---- (2) opponent pace for tackles
team_plays = snaps.groupby(["season", "week", "team"])["offense_snaps"].max().reset_index()
team_plays = team_plays.sort_values(["team", "season", "week"])
pace = {}
for t, g in team_plays.groupby("team"):
    recs = g.to_dict("records")
    for i in range(len(recs)):
        prev = [r["offense_snaps"] for r in recs[max(0, i - 5):i]]
        if len(prev) >= 3:
            pace[(recs[i]["season"], recs[i]["week"], t)] = wmean(prev)
lg = team_plays["offense_snaps"].mean()
print("NU league plays/game", round(lg, 1))
dst = ps[["player_id", "season", "week", "def_tackles_solo", "def_tackle_assists"]].rename(columns={"player_id": "gsis"})
dd = snaps[snaps["defense_snaps"].fillna(0) > 0].merge(dst, on=["gsis", "season", "week"], how="inner").sort_values(["pfr_player_id", "season", "week"])
dd["tka"] = dd["def_tackles_solo"].fillna(0) + dd["def_tackle_assists"].fillna(0)
cell = defaultdict(lambda: [0, 0.0, 0.0])
ho = defaultdict(lambda: [0, 0.0, 0.0, 0, 0])
for pid, g in dd.groupby("pfr_player_id"):
    rows = g.to_dict("records")
    for i in range(3, len(rows)):
        hist, cur = rows[max(0, i - 5):i], rows[i]
        p = pace.get((cur["season"], cur["week"], cur["opponent"]))
        if p is None:
            continue
        # the opponents he faced lately ran how many plays? (his baseline already carries their pace)
        hp = [pace.get((h["season"], h["week"], h["opponent"])) for h in hist]
        hp = [x for x in hp if x]
        if not hp:
            continue
        rel = p / (sum(hp) / len(hp))
        b = "opp much faster (+6%)" if rel >= 1.06 else "opp faster (+3-6%)" if rel >= 1.03 else "opp much slower (-6%)" if rel <= 0.94 else "opp slower (-3-6%)" if rel <= 0.97 else "similar"
        for stat in ("def_tackles_solo", "tka"):
            base = wmean([h[stat] for h in hist])
            if base < 1.5:
                continue
            x = cell[(stat, b)]; x[0] += 1; x[1] += cur[stat]; x[2] += base
            new = base * rel
            line = math.floor(base) + 0.5
            hk = ho[(stat, int(cur["season"]))]
            hk[0] += 1; hk[1] += abs(base - cur[stat]); hk[2] += abs(new - cur[stat])
            if (base > line) != (new > line):
                hk[3] += 1; hk[4] += (cur[stat] > line) == (new > line)
for k, (n, y, b) in sorted(cell.items()):
    print("NU PACE", k, f"n={n} actual/own-avg {y/b:.3f}")
for k, (n, a, b, f, w) in sorted(ho.items()):
    print("NU PACEHO", k, f"n={n} MAE {a/n:.3f} -> x pace {b/n:.3f} ({(a-b)/a:+.1%}) | side flips {f} right {w/max(1,f):.1%}")
