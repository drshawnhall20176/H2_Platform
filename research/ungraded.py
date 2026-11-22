import sys
sys.path.insert(0, ".")
import pick_ledger as PL, sports
D = "2026-11-21"
for kind, sp in (("strong", "ALL"), ("money", "NBA")):
    for r in PL.rows(kind, sp, D):
        if r.get("result") in ("win", "loss", "push", "void"):
            continue
        s = r.get("sport")
        res = sports.get(s).engine.get_player_results(D) or {}
        pid = r.get("pid")
        a = res.get(pid) if pid is not None else None
        if a is None and pid is not None:
            try: a = res.get(int(pid))
            except Exception: pass
        print(f"UG {kind} {s} {r.get('pick')} pid={pid!r} line={r.get('line')} game={r.get('game')} time={r.get('time')} in_results={a is not None} n_results={len(res)} sample_keys={list(res)[:3]}")
