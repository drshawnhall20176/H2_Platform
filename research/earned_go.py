import sys
sys.path.insert(0, ".")
import props_money as PM
rec = PM.refit()
for sp, c in rec["coefs"].items():
    print(f"EG {sp} fits: {sorted(c)}")
