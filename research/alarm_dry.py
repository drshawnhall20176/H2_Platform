import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data_checks as DC
for i in DC.check_bias("2026-11-22"): print("BIAS", i["detail"])
for i in DC.check_shown("2026-11-22"): print("SHOWN", i["detail"])
print("done")
