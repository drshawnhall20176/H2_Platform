"""Nov 16 morning: what didn't update? Unsettled bets, ungraded reads, last snapshot times per sport."""
import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, model_store as MS
bets = B.list_bets()
open_ = [b for b in bets if not b.get("result") and str(b.get("date") or b.get("game_date") or "") >= "2026-11-14"]
print("open bets since Nov 14:", len(open_))
for b in open_[:40]:
    print(" ", b.get("id"), b.get("date") or b.get("game_date"), b.get("sport"), b.get("player") or b.get("team"), b.get("market"), b.get("side"), b.get("line"), b.get("odds"), b.get("notes"))
for sp in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"):
    for d in ("2026-11-15", "2026-11-16"):
        try:
            s = MS.load_snapshots(sp, [d])
        except Exception as e:
            print(sp, d, "err", e); continue
        ts = max((str(x.get("ts")) for x in s), default=None)
        print(f"{sp} {d}: {len(s)} snapshots, newest {ts}")
    try:
        g = MS.load_graded(sp, ["2026-11-15"]) if hasattr(MS, "load_graded") else None
        if g is not None: print(f"   graded Nov 15: {len(g)}")
    except Exception as e:
        print("   graded err", e)
print([n for n in dir(MS) if n.startswith("load")])
