"""Nov 8: NHL power-play role. Current skater read = rate per minute of TOTAL ice time x projected ice time. Test:
even-strength rate x ES time + power-play rate x PP time (each recency weighted), so a skater moved onto / off the top
power-play unit is read by his new role. ESPN box scores, 2025-26 + 2026-27 regular seasons. Each game from earlier games."""
import os, sys, math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import script_data as D, props_engine as PE

c = D.CFG["NHL"]
ids = D.event_ids(c)
print("NPP games", len(ids))
def mmss(v):
    try:
        m, s = str(v).split(":"); return int(m) + int(s) / 60
    except Exception:
        return None
def one(t):
    gid, d = t
    s = D._get(f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/summary", {"event": gid}) or {}
    out = []
    for grp in (s.get("boxscore") or {}).get("players") or []:
        tid = str((grp.get("team") or {}).get("id"))
        for sg in grp.get("statistics") or []:
            if sg.get("name") == "goalies":
                continue
            keys = sg.get("keys") or []
            for a in sg.get("athletes") or []:
                if not a.get("stats"):
                    continue
                r = dict(zip(keys, a["stats"]))
                toi, pp, es = mmss(r.get("timeOnIce")), mmss(r.get("powerPlayTimeOnIce")), mmss(r.get("evenStrengthTimeOnIce"))
                if not toi:
                    continue
                g, ast = D._f(r.get("goals")) or 0, D._f(r.get("assists")) or 0
                out.append({"pid": (a.get("athlete") or {}).get("id"), "d": str(d), "toi": toi, "pp": pp or 0.0,
                            "es": es if es is not None else toi - (pp or 0), "sog": D._f(r.get("shotsTotal")) or 0, "pts": g + ast})
    return out
with ThreadPoolExecutor(max_workers=8) as ex:
    games = list(ex.map(one, ids))
by = defaultdict(list)
for g in games:
    for r in g:
        by[r["pid"]].append(r)
res = defaultdict(lambda: [0, 0.0, 0.0, 0, 0])
for pid, rs in by.items():
    rs.sort(key=lambda r: r["d"])
    for i in range(5, len(rs)):
        hist, cur = rs[max(0, i - 10):i][::-1], rs[i]          # newest first
        toi_p = PE.wmean([h["toi"] for h in hist[:5]])
        pp_p = PE.wmean([h["pp"] for h in hist[:5]]); es_p = PE.wmean([h["es"] for h in hist[:5]])
        if toi_p < 12:
            continue
        pp_prev = sum(h["pp"] for h in hist[1:6]) / len(hist[1:6])
        role = hist[0]["pp"] - pp_prev
        bucket = "PP up 1.5+ min" if role >= 1.5 else "PP down 1.5+ min" if role <= -1.5 else "steady"
        for stat in ("sog", "pts"):
            tot_rate = sum(h[stat] for h in hist) / sum(h["toi"] for h in hist)
            cur_pred = tot_rate * toi_p
            # split rates: PP share of production estimated with a league prior (PP minutes ~2x as productive)
            es_min = sum(h["es"] for h in hist); pp_min = sum(h["pp"] for h in hist); prod = sum(h[stat] for h in hist)
            k = 2.0 if stat == "sog" else 3.5
            denom = es_min + k * pp_min
            es_rate = prod / denom if denom else 0
            new_pred = es_rate * es_p + es_rate * k * pp_p
            y = cur[stat]
            line = 2.5 if stat == "sog" and cur_pred >= 2 else 1.5 if stat == "sog" else 0.5
            for key in ((stat, "all"), (stat, bucket)):
                r = res[key]; r[0] += 1; r[1] += abs(cur_pred - y); r[2] += abs(new_pred - y)
                # probability read (Poisson) vs the line
                def p_over(lam):
                    return 1 - sum(math.exp(-lam) * lam ** j / math.factorial(j) for j in range(int(line) + 1))
                a, b = p_over(cur_pred) > 0.5, p_over(new_pred) > 0.5
                if a != b:
                    r[3] += 1; r[4] += (y > line) == b
for k, (n, a, b, f, w) in sorted(res.items()):
    print("NPP", k, f"n={n} MAE total-TOI {a/n:.3f} split ES/PP {b/n:.3f} ({(a-b)/a:+.1%}) | side flips {f} split right {w/max(1,f):.1%}")
