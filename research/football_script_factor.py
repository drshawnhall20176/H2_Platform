"""Nov 8: is the football props model's game-script factor right for big spreads? (owner: two college pass-yard bets
lost by <10 yards in blowouts). ESPN box scores + pre-game spreads, 2025 + 2026 seasons, NFL and NCAAF.
For each player-game: baseline = recency-weighted mean of his previous 5 games; the model's current factor from his
team's spread (football_props SCRIPT_PASS / SCRIPT_RUSH, football_special SCRIPT). Residual = actual / (baseline x
factor), by the team's spread bucket. Held out: bucket corrections fit on one season, tested on the other."""
import os, sys, json
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import script_data as D, script_learn as L, football_props as FP, football_special as FS, props_engine as PE

GROUPS = {   # name: (stat key, eligible(base), factor kind)
    "pass_yds": ("passingYards", lambda b: b.get("passingAttempts", 0) >= 15, "pass"),
    "pass_att": ("passingAttempts", lambda b: b.get("passingAttempts", 0) >= 15, "pass"),
    "rush_att": ("rushingAttempts", lambda b: b.get("rushingAttempts", 0) >= 8 and b.get("passingAttempts", 0) < 5, "rush"),
    "rush_yds": ("rushingYards", lambda b: b.get("rushingAttempts", 0) >= 8 and b.get("passingAttempts", 0) < 5, "rush"),
    "receptions": ("receptions", lambda b: b.get("receptions", 0) >= 2.5, "pass"),
    "rec_yds": ("receivingYards", lambda b: b.get("receptions", 0) >= 2.5, "pass"),
    "tackles": ("totalTackles", lambda b: b.get("totalTackles", 0) >= 4, "tkl"),
}
def factor(kind, sp):
    if kind == "pass":
        return 1 + FP.SCRIPT_PASS * sp
    if kind == "rush":
        return 1 - FP.SCRIPT_RUSH * sp
    return 1 + FS.SCRIPT["Tackles + Assists"] * sp
def bucket(sp, sport):
    cuts = (3.5, 7.5, 13.5) if sport == "NFL" else (7.5, 14.5, 24.5)
    a = abs(sp)
    b = 0 if a < cuts[0] else 1 if a < cuts[1] else 2 if a < cuts[2] else 3
    lab = ["pickem", f"{cuts[0]}-{cuts[1]}", f"{cuts[1]}-{cuts[2]}", f"{cuts[2]}+"][b]
    return lab if b == 0 else ("fav " if sp < 0 else "dog ") + lab

out = {}
for sport in ("NFL", "NCAAF"):
    c = D.CFG[sport]
    cache = {"days": set(), "games": {}}
    L.update(sport, cache)
    games = L.games_of(cache)
    print("FS", sport, "games", len(games), "with spread", sum(1 for _, p in games if p.get("strength")))
    hist = defaultdict(list)
    rows = []
    for d, p in games:
        season = D.season_of(c, d)
        for pid, st in p["players"].items():
            for k in ("passingYards", "passingAttempts", "rushingYards", "rushingAttempts", "receivingYards", "receptions", "totalTackles"):
                st.setdefault(k, 0.0)
            h = hist[pid]
            if len(h) >= 3 and p.get("strength") is not None and p.get("fav") is not None:
                sp = -p["strength"] if st.get("team") == p["fav"] else p["strength"]
                recent = h[-5:][::-1]
                base = {k: PE.wmean([x.get(k, 0.0) for x in recent]) for k in ("passingYards", "passingAttempts", "rushingYards", "rushingAttempts", "receivingYards", "receptions", "totalTackles")}
                for g, (key, ok, kind) in GROUPS.items():
                    if ok(base) and base[key] > 0:
                        rows.append({"sport": sport, "g": g, "season": season, "sp": sp, "b": bucket(sp, sport),
                                     "base": base[key], "f": factor(kind, sp), "y": st.get(key) or 0.0})
            h.append({k: v for k, v in st.items() if isinstance(v, (int, float))})
    # residual by bucket
    cell = defaultdict(lambda: [0, 0.0, 0.0, 0.0])
    for r in rows:
        for k in ((r["g"], r["b"]), (r["g"], r["b"], r["season"])):
            x = cell[k]; x[0] += 1; x[1] += r["y"]; x[2] += r["base"] * r["f"]; x[3] += r["base"]
    for k in sorted(cell, key=str):
        n, y, m, b = cell[k]
        if len(k) == 2 and n >= 40:
            print("FS", sport, f"{k[0]:10s} {k[1]:14s} n={n:5d}  actual/baseline {y/b:.3f}  model factor {m/b:.3f}  residual (actual/model) {y/m:.3f}")
    # held out: residual per (g, bucket) fit on one season, applied to the other
    for g in GROUPS:
        tot = [0, 0.0, 0.0, 0, 0]
        for fit_s, test_s in (("0", "1"), ("1", "0")):
            res = {}
            for k, (n, y, m, b) in cell.items():
                if len(k) == 3 and k[0] == g and k[2] == fit_s and n >= 30:
                    shrink = n / (n + 150)
                    res[k[1]] = 1 + (y / m - 1) * shrink
            for r in rows:
                if r["g"] != g or r["season"] != test_s:
                    continue
                cur = r["base"] * r["f"]
                new = cur * res.get(r["b"], 1.0)
                tot[0] += 1; tot[1] += abs(cur - r["y"]); tot[2] += abs(new - r["y"])
                line = int(cur) + 0.5 if g in ("pass_att", "rush_att", "receptions", "tackles") else round(cur)
                if (cur > line) != (new > line):
                    tot[3] += 1; tot[4] += (r["y"] > line) == (new > line)
        if tot[0]:
            print("FSHO", sport, f"{g:10s} n={tot[0]} MAE current {tot[1]/tot[0]:.2f} corrected {tot[2]/tot[0]:.2f} ({(tot[1]-tot[2])/tot[1]:+.1%})"
                  f" | side flips {tot[3]}, corrected right {tot[4]} = {tot[4]/max(1,tot[3]):.1%}")
    out[sport] = {f"{k[0]}|{k[1]}": (cell[k][1] / cell[k][2], cell[k][0]) for k in cell if len(k) == 2}
print("FSJSON " + json.dumps(out))
