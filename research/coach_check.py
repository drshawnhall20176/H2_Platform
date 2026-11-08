import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, coach as CO
allb = B.list_bets()
for days in (30, None):
    b = CO.in_period(allb, days)
    print("CO ===", days)
    for r in CO.rules(b): print("CO RULE", r)
    for r in CO.report_card(b): print("CO CARD", r)
    for r in CO.price_check(b): print("CO PRICE", r)
    best, worst = CO.best_and_worst(b)
    for r in best: print("CO BEST", r)
    for r in worst: print("CO WORST", r)
