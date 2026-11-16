import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, prop_settlement as PS
bets = [b for b in B.list_bets(settled=False) if b.get("id") == 742]
plan = PS.build_plan(bets, "NBA")
print("PLAN", {k: plan[k] for k in plan})
