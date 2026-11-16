import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, daily_review as DR
bets = [b for b in B.list_bets(settled=False) if b.get("id") == 742]
print("SETTLE", DR.settle("NBA", bets))
