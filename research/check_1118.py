import os, sys, json
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, betlog as B, daily_review as DR
for c in MS.list_calibration():
    if "trust" in str(c.get("sport")):
        print("CAL", c.get("id"), c.get("sport"), c.get("s"), c.get("created_at") or c.get("approved_at"), str(c.get("meta") or c.get("details"))[:160])
bets = [x for x in B.list_bets(settled=False) if x.get("id") == 759]
print("SETTLE", DR.settle("NBA", bets))
