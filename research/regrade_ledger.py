import sys
sys.path.insert(0, ".")
import pick_ledger as PL, sports
D = "2026-11-21"
cache = {}
print("RL final NBA:", PL.finished_games("NBA", D, cache))
for k, v in PL.grade_day(D).items():
    print("RL", k, v)
for kind, sp in (("strong", "ALL"), ("money", "NBA")):
    for r in PL.rows(kind, sp, D):
        if r.get("result") not in ("win", "loss", "push"):
            print("RL still", kind, r.get("pick"), r.get("result"))
r = PL.record("strong", "ALL", D)
print("RL strong record", r)
