"""Nov 19: the Bet Log's open bets (the morning brief shows 6 singles + 1 parlay from Wednesday unsettled)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bets as B
for b in B.list_bets(settled=False):
    print("OB", json.dumps(b, default=str)[:600])
