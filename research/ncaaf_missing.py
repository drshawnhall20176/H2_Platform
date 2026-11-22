import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pick_ledger as PL, sports
rows = [r for r in PL.rows("strong","ALL","2026-11-21") if r.get("player") in ("Elija Lofton","Caden High")]
for r in rows: print({k: r.get(k) for k in ("player","pid","game","time","market","result","close_checked")})
eng = sports.get("NCAAF").engine
res = eng.get_player_results("2026-11-21")
print("results:", len(res))
for pid in [str(r.get("pid")) for r in rows]:
    print(pid, res.get(pid) or res.get(int(pid)) if pid.isdigit() else None)
names = {str(v.get("name","")).lower(): k for k, v in res.items() if isinstance(v, dict)}
for n in ("lofton","high"):
    print(n, [(nm, k) for nm, k in names.items() if n in nm][:10])
import pick_ledger as PL2
cache = {}
print("finished games:", [g for g in PL2.finished_games("NCAAF","2026-11-21",cache) if any(t in str(g) for t in ("Kansas","Texas","Arizona","Oklahoma","Utah"))][:20])
