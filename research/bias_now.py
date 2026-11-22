import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data_checks as DC, props_engine as PE
for i in DC.check_bias(PE._et_today()): print("ALARM", i["detail"])
print("done")
