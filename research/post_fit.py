import sys
sys.path.insert(0, ".")
import props_money as PM
rec = PM.refit()
print("PF", rec["coefs"].get("_post"))
