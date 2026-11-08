"""Nov 8: do NFL defenders' tackles read better per SNAP x recent snap share than per GAME (what football_special does)?
Held out: predict each defender-game from games before it only. 2023-2025 regular seasons + 2026 so far."""
import sys, math
from collections import defaultdict
import nflreadpy as nfl
import pandas as pd

seasons = [2023, 2024, 2025, 2026]
snaps = pd.concat([nfl.load_snap_counts([s]).to_pandas() for s in seasons], ignore_index=True)
print("IDP snap cols", list(snaps.columns)[:30])
ps = nfl.load_player_stats(seasons).to_pandas()
print("IDP stat cols", [c for c in ps.columns if "tackl" in c or c in ("player_id", "player_display_name", "team", "week", "season", "season_type", "position")])
players = nfl.load_players().to_pandas()
idmap = dict(zip(players["pfr_id"], players["gsis_id"]))
snaps = snaps[snaps.get("game_type", "REG").astype(str).eq("REG")] if "game_type" in snaps else snaps
snaps["gsis"] = snaps["pfr_player_id"].map(idmap)
solo = "def_tackles_solo"
ast = next(c for c in ("def_tackle_assists", "def_tackles_with_assist", "def_tackle_assist") if c in ps.columns)
ps = ps[ps["season_type"].astype(str).eq("REG")] if "season_type" in ps else ps
st = ps[["player_id", "season", "week", solo, ast]].rename(columns={"player_id": "gsis"})
df = snaps.merge(st, on=["gsis", "season", "week"], how="left")
df = df[df["defense_snaps"].fillna(0) > 0].copy()
df[solo] = df[solo].fillna(0); df[ast] = df[ast].fillna(0)
df["tka"] = df[solo] + df[ast]
print("IDP rows", len(df), "matched stats", int(df["gsis"].notna().sum()))
df = df.sort_values(["pfr_player_id", "season", "week"])

W = [0.30, 0.25, 0.20, 0.15, 0.10]
def wmean(xs):
    xs = xs[::-1][:5]; w = W[:len(xs)]
    return sum(a * b for a, b in zip(xs, w)) / sum(w)

res = defaultdict(lambda: defaultdict(list))
for pid, g in df.groupby("pfr_player_id"):
    rows = g.to_dict("records")
    for i in range(3, len(rows)):
        hist, cur = rows[max(0, i - 8):i], rows[i]
        if hist[-1]["season"] != cur["season"] and len([h for h in hist if h["season"] == cur["season"]]) < 1:
            pass
        sn = [h["defense_snaps"] for h in hist]
        pct = [h["defense_pct"] for h in hist]
        for stat in ("solo", "tka"):
            key = solo if stat == "solo" else "tka"
            v = [h[key] for h in hist]
            per_game = wmean(v)
            rate = sum(v[-6:]) / max(1, sum(sn[-6:]))               # per snap, last 6 games
            team_snaps = cur["defense_snaps"] / cur["defense_pct"] if cur["defense_pct"] else None
            exp_snaps = wmean(sn[-3:]) if len(sn) >= 3 else wmean(sn)   # current role: last 3 games, weighted
            per_snap = rate * exp_snaps
            blend = 0.5 * per_game + 0.5 * per_snap
            y = cur[key]
            role = (pct[-1] - sum(pct[-6:-1]) / max(1, len(pct[-6:-1]))) if len(pct) >= 2 else 0
            bucket = "role up 15+ pts" if role >= 0.15 else "role down 15+ pts" if role <= -0.15 else "steady"
            for b in ("all", bucket):
                r = res[(stat, b)]
                r["pg"].append(abs(per_game - y)); r["ps"].append(abs(per_snap - y)); r["bl"].append(abs(blend - y))
                r["n"].append(1)
                # over/under a typical line: per-game avg rounded to .5 -- does the snap read call the side better?
                line = math.floor(per_game) + 0.5
                if per_snap != per_game:
                    call_over = per_snap > per_game
                    r["side"].append(1 if (y > line) == call_over else 0)
for (stat, b), r in sorted(res.items()):
    n = len(r["n"])
    side = r["side"]
    print("IDP", stat, f"{b:18s} n={n:6d}  MAE per-game {sum(r['pg'])/n:.3f} | per-snap {sum(r['ps'])/n:.3f} | blend {sum(r['bl'])/n:.3f}"
          f" | snap read calls side vs per-game line {sum(side)}/{len(side)} = {sum(side)/max(1,len(side)):.1%}")
# by season for the held-out check (stable across seasons?)
