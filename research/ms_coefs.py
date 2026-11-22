import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import money_score as MSC
c = MSC.coefs()
for k, v in sorted(c.items()): print(k, [round(x, 3) for x in v] if v else v)
