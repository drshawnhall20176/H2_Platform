"""Nov 8, round 2: football game script. Variants, held out by season and by alternate games:
  current  = baseline x the model's linear spread factor (football_props / football_special)
  none     = baseline (no script factor)
  bucket   = baseline x (actual/baseline in that spread bucket / actual/baseline at pick'em), fit on the other half
Plus NCAAF pace: the player's volume vs the opponent's recent plays per game (rush att + pass att), relative to the
opponents he faced lately."""
import os, sys, json, math
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import script_data as D, script_learn as L, football_props as FP, football_special as FS, props_engine as PE

RAW = {}
_orig_get = D._get
def _get(url, params):
    r = _orig_get(url, params)
    if url.endswith("/summary") and r:
        RAW[str(params.get("event"))] = r
    return r
D._get = _get

GROUPS = {"pass_yds": ("passingYards", lambda b: b.get("passingAttempts", 0) >= 15, "pass"),
          "pass_att": ("passingAttempts", lambda b: b.get("passingAttempts", 0) >= 15, "pass"),
          "rush_att": ("rushingAttempts", lambda b: b.get("rushingAttempts", 0) >= 8 and b.get("passingAttempts", 0) < 5, "rush"),
          "rush_yds": ("rushingYards", lambda b: b.get("rushingAttempts", 0) >= 8 and b.get("passingAttempts", 0) < 5, "rush"),
          "receptions": ("receptions", lambda b: b.get("receptions", 0) >= 2.5, "pass"),
          "rec_yds": ("receivingYards", lambda b: b.get("receptions", 0) >= 2.5, "pass"),
          "tackles": ("totalTackles", lambda b: b.get("totalTackles", 0) >= 4, "tkl")}
KEYS = ("passingYards", "passingAttempts", "rushingYards", "rushingAttempts", "receivingYards", "receptions", "totalTackles")
def factor(kind, sp):
    return 1 + FP.SCRIPT_PASS * sp if kind == "pass" else (1 - FP.SCRIPT_RUSH * sp if kind == "rush" else 1 + FS.SCRIPT["Tackles + Assists"] * sp)
def bucket(sp, sport):
    cuts = (3.5, 7.5, 13.5) if sport == "NFL" else (7.5, 14.5, 24.5)
    a = abs(sp); b = 0 if a < cuts[0] else 1 if a < cuts[1] else 2 if a < cuts[2] else 3
    return "pickem" if b == 0 else ("fav" if sp < 0 else "dog") + str(b)
def team_plays(raw):
    out = {}
    for t in ((raw or {}).get("boxscore") or {}).get("teams") or []:
        tid = str((t.get("team") or {}).get("id")); n = 0.0
        for s in t.get("statistics") or []:
            nm, v = s.get("name"), str(s.get("displayValue") or "")
            if nm == "rushingAttempts":
                n += D._f(v) or 0
            elif nm in ("completionAttempts",) and "-" in v:
                n += D._f(v.split("-")[1]) or 0
            elif nm in ("completionAttempts",) and "/" in v:
                n += D._f(v.split("/")[1]) or 0
        if n:
            out[tid] = n
    return out

for sport in ("NFL", "NCAAF"):
    c = D.CFG[sport]
    cache = {"days": set(), "games": {}}
    L.update(sport, cache)
    gids = {json.dumps(p["teams"], sort_keys=True): gid for gid, (d, p) in cache["games"].items()}
    games = sorted(((d, p, gid) for gid, (d, p) in cache["games"].items()), key=lambda t: t[0])
    tplays = defaultdict(list)          # team -> [(gi, plays)]
    hist = defaultdict(list)
    rows = []
    for gi, (d, p, gid) in enumerate(games):
        tp = team_plays(RAW.get(str(gid)))
        teams = list(p["teams"])
        for pid, st in p["players"].items():
            for k in KEYS:
                st.setdefault(k, 0.0)
            h = hist[pid]
            tm = st.get("team"); opp = next((t for t in teams if t != tm), None)
            if len(h) >= 3:
                recent = h[-5:][::-1]
                base = {k: PE.wmean([x[0].get(k, 0.0) for x in recent]) for k in KEYS}
                sp = None
                if p.get("strength") is not None and p.get("fav") is not None:
                    sp = -p["strength"] if tm == p["fav"] else p["strength"]
                # pace: opponent's recent plays/game vs the opponents he faced lately
                def opp_pace(o, before):
                    xs = [n for g2, n in tplays.get(o, []) if g2 < before][-5:]
                    return sum(xs) / len(xs) if len(xs) >= 2 else None
                op = opp_pace(opp, gi)
                hp = [opp_pace(x[1], x[2]) for x in recent]
                hp = [x for x in hp if x]
                rel = op / (sum(hp) / len(hp)) if op and hp else None
                for g, (key, ok, kind) in GROUPS.items():
                    if ok(base) and base[key] > 0:
                        rows.append({"g": g, "season": D.season_of(c, d), "alt": gi % 2, "sp": sp,
                                     "b": bucket(sp, sport) if sp is not None else None, "base": base[key],
                                     "f": factor(kind, sp) if sp is not None else 1.0, "y": st.get(key) or 0.0, "pace": rel})
            h.append(({k: v for k, v in st.items() if isinstance(v, (int, float))}, opp, gi))
        for t, n in tp.items():
            tplays[t].append((gi, n))
    print("FS2", sport, "games", len(games), "rows", len(rows), "with spread", sum(1 for r in rows if r["sp"] is not None),
          "with pace", sum(1 for r in rows if r["pace"]))
    for split in ("season", "alt"):
        for g in GROUPS:
            rs = [r for r in rows if r["g"] == g and r["sp"] is not None]
            halves = sorted({r[split] for r in rs})
            if len(halves) < 2:
                continue
            tot = defaultdict(float); flips = defaultdict(lambda: [0, 0])
            for test in halves:
                fit = [r for r in rs if r[split] != test]
                cell = defaultdict(lambda: [0.0, 0.0, 0])
                for r in fit:
                    x = cell[r["b"]]; x[0] += r["y"]; x[1] += r["base"]; x[2] += 1
                pk = cell["pickem"][0] / cell["pickem"][1] if cell["pickem"][1] else 1.0
                corr = {b: 1 + ((y / bs) / pk - 1) * (n / (n + 60)) for b, (y, bs, n) in cell.items() if bs}
                for r in (r for r in rs if r[split] == test):
                    preds = {"current": r["base"] * r["f"], "none": r["base"], "bucket": r["base"] * corr.get(r["b"], 1.0)}
                    for k, v in preds.items():
                        tot[k] += abs(v - r["y"])
                    tot["n"] += 1
                    cur = preds["current"]
                    line = math.floor(cur) + 0.5 if g in ("pass_att", "rush_att", "receptions", "tackles") else round(cur) + 0.5
                    for k in ("none", "bucket"):
                        if (cur > line) != (preds[k] > line):
                            flips[k][0] += 1; flips[k][1] += (r["y"] > line) == (preds[k] > line)
            n = tot["n"]
            print("FS2HO", sport, split, f"{g:10s} n={int(n)} MAE current {tot['current']/n:.2f} none {tot['none']/n:.2f} "
                  f"bucket {tot['bucket']/n:.2f} | flips vs current: none {flips['none'][1]}/{flips['none'][0]} "
                  f"={flips['none'][1]/max(1,flips['none'][0]):.1%}, bucket {flips['bucket'][1]}/{flips['bucket'][0]} ={flips['bucket'][1]/max(1,flips['bucket'][0]):.1%}")
    # bucket table (all data, relative to pick'em) -> the factors to ship
    tab = defaultdict(lambda: [0.0, 0.0, 0])
    for r in rows:
        if r["sp"] is not None:
            x = tab[(r["g"], r["b"])]; x[0] += r["y"]; x[1] += r["base"]; x[2] += 1
    for g in GROUPS:
        pk = tab[(g, "pickem")][0] / tab[(g, "pickem")][1]
        print("FS2TAB", sport, g, " ".join(f"{b}:{(tab[(g,b)][0]/tab[(g,b)][1])/pk:.3f}(n{tab[(g,b)][2]})" for b in
              ("fav3", "fav2", "fav1", "pickem", "dog1", "dog2", "dog3") if tab[(g, b)][1]))
    # pace
    pc = defaultdict(lambda: [0.0, 0.0, 0]); pho = defaultdict(lambda: [0, 0.0, 0.0, 0, 0])
    for r in rows:
        if not r["pace"]:
            continue
        rel = r["pace"]
        b = "opp +6%" if rel >= 1.06 else "opp +3-6%" if rel >= 1.03 else "opp -6%" if rel <= 0.94 else "opp -3-6%" if rel <= 0.97 else "similar"
        x = pc[(r["g"], b)]; x[0] += r["y"]; x[1] += r["base"]; x[2] += 1
        for w in (0.5, 1.0):
            new = r["base"] * (1 + w * (rel - 1)); cur = r["base"]
            line = math.floor(cur) + 0.5 if r["g"] in ("pass_att", "rush_att", "receptions", "tackles") else round(cur) + 0.5
            k = pho[(r["g"], w)]; k[0] += 1; k[1] += abs(cur - r["y"]); k[2] += abs(new - r["y"])
            if (cur > line) != (new > line):
                k[3] += 1; k[4] += (r["y"] > line) == (new > line)
    for g in GROUPS:
        sim = pc[(g, "similar")]
        if sim[1]:
            print("FS2PACE", sport, g, " ".join(f"{b}:{(pc[(g,b)][0]/pc[(g,b)][1])/(sim[0]/sim[1]):.3f}(n{pc[(g,b)][2]})"
                                             for b in ("opp -6%", "opp -3-6%", "similar", "opp +3-6%", "opp +6%") if pc[(g, b)][1]))
    for (g, w), (n, a, b, f, wr) in sorted(pho.items()):
        print("FS2PACEHO", sport, g, w, f"n={n} MAE {a/n:.3f} -> {b/n:.3f} ({(a-b)/a:+.1%}) flips {f} right {wr/max(1,f):.1%}")
