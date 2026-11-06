"""Nov 6: how have the model's game-line leans done on graded games? Spread lean (model margin vs line) and total lean
(model total vs line), by sport and by size of disagreement."""
import os, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import intl_hoops as H, model_store as MS

leagues = ["NCAAMB", "NBA", "NHL", "NCAAF"] + [k for k in H.LEAGUES if k not in ("NCAAMB", "NBA", "NHL")]
for lg in leagues:
    try:
        recs = [r for r in MS.load_game_picks(lg) if r.get("final_home") is not None and r.get("final_away") is not None]
    except Exception as e:
        continue
    if not recs:
        continue
    sp, tot = [], []
    for r in recs:
        fm = float(r["final_home"]) - float(r["final_away"])
        hs, mm = r.get("home_spread"), r.get("model_margin")
        if hs is None and r.get("line") is not None and lg == "NCAAF":
            hs = r["line"]
        if hs is not None and mm is not None:
            res = fm + float(hs)
            if res != 0:
                lean_home = float(mm) + float(hs) > 0
                gap = abs(float(mm) + float(hs))
                sp.append((gap, lean_home == (res > 0)))
        lt, mt = r.get("line_total"), r.get("model_total")
        if lt is not None and mt is not None:
            ft = float(r["final_home"]) + float(r["final_away"])
            if ft != float(lt):
                tot.append((abs(float(mt) - float(lt)), (float(mt) > float(lt)) == (ft > float(lt))))
    print(f"\n## {lg}: {len(recs)} graded games")
    for name, rows, cuts in (("spread", sp, (0, 3, 6, 10, 15, 99)), ("total", tot, (0, 3, 6, 10, 15, 99))):
        if not rows:
            continue
        print(f"  {name} lean right {sum(w for _, w in rows) / len(rows):.1%} of {len(rows)}")
        for lo, hi in zip(cuts, cuts[1:]):
            g = [w for gp, w in rows if lo <= gp < hi]
            if len(g) >= 5:
                print(f"     disagreement {lo:>2}-{hi:<2} pts: {sum(g) / len(g):.1%} of {len(g)}")
