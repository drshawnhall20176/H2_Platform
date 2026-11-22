import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pick_ledger as PL, hot_tickets as HT
for r in PL.rows("hot","ALL","2026-11-22"): print("HOT", r.get("sport"), r.get("pick"), r.get("price"), r.get("earned"), r.get("time"), r.get("money_market"))
print("PARLAY", PL._get(HT.KEY.format(day="2026-11-22")))
