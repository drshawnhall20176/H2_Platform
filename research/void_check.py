"""Nov 18: graded props that came back void -- the player wasn't in his team's box score. A real DNP, or a name we
failed to match (data lost)? For each void: is there a box-score player on the same team with the same last name?"""
import os, sys, difflib
from collections import Counter
from datetime import date
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, postgame as PG, props_engine as PE
for sp in ("NBA", "NHL", "NFL", "NCAAF"):
    ds = [d for d in MS.snapshot_dates(sp) if d < date.today().isoformat()]
    snaps = MS.load_snapshots(sp, ds)
    kinds = Counter(); ex = []
    for d in sorted({s["slate_date"] for s in snaps}):
        day = [s for s in snaps if s["slate_date"] == d]
        res = PG.fetch_results(sp, d, sorted({(s["team"], s["opp"]) for s in day}))
        for r in PG.grade(day, res):
            if r["result"] != "void": continue
            box = res.get((r.get("team"), r.get("opp"))) or {}
            tk = PG._team_key(sp, box, r.get("team"))
            names = list(((box.get("teams") or {}).get(tk) or {}).keys()) if tk is not None else []
            want = PG._norm(PE.norm_name(r.get("player")))
            if tk is None or not names:
                kinds["team not found in box"] += 1; ex.append(("team", d, r.get("player"), r.get("team"))); continue
            if want in names:
                kinds["player in box, stat missing for market " + str(r.get("market"))] += 1; continue
            last = want.split()[-1] if want else ""
            close = difflib.get_close_matches(want, names, n=1, cutoff=0.75)
            same_last = [n for n in names if n.split() and n.split()[-1] == last]
            if close or same_last:
                kinds["NAME MISMATCH (likely same player)"] += 1
                ex.append(("name", d, r.get("player"), (close or same_last)[0]))
            else:
                kinds["not in box (did not play)"] += 1
    print(f"V {sp}: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common()))
    seen = set()
    for e in ex:
        if (e[0], e[2]) in seen: continue
        seen.add((e[0], e[2]))
        print(f"VX {sp} {e}")
