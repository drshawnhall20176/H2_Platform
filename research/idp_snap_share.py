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

res = defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0, 0])
for pid, g in df.groupby("pfr_player_id"):
    rows = g.to_dict("records")
    for i in range(3, len(rows)):
        hist, cur = rows[max(0, i - 8):i], rows[i]
        sn = [h["defense_snaps"] for h in hist]
        pct = [h["defense_pct"] for h in hist]
        role = (pct[-1] - sum(pct[-6:-1]) / max(1, len(pct[-6:-1]))) if len(pct) >= 2 else 0
        bucket = "role up" if role >= 0.15 else "role down" if role <= -0.15 else "steady"
        for stat, key in (("solo", solo), ("tka", "tka")):
            v = [h[key] for h in hist]
            pg = wmean(v)
            ps_ = sum(v[-6:]) / max(1, sum(sn[-6:])) * wmean(sn[-3:])
            bl = 0.5 * pg + 0.5 * ps_
            y = cur[key]
            for line in (math.floor(pg) + 0.5, math.floor(bl) + 0.5):
                a, b = pg > line, bl > line
                if a != b:                                       # the two reads disagree on the side
                    for k in ((stat, "all", "all"), (stat, bucket, "all"), (stat, "all", int(cur["season"]))):
                        r = res[k]; r[0] += 1; r[1] += (y > line) == b
            for k in ((stat, "all", int(cur["season"])),):
                r = res[k]; r[2] += abs(pg - y); r[3] += abs(bl - y); r[5] += 1
for k, r in sorted(res.items(), key=lambda kv: str(kv[0])):
    mae = f" | MAE per-game {r[2]/r[5]:.3f} blend {r[3]/r[5]:.3f} ({(r[2]-r[3])/r[2]:+.1%})" if r[5] else ""
    print("IDP2", k, f"disagreements {r[0]}, blend right {r[1]} = {r[1]/max(1,r[0]):.1%}" + mae)
