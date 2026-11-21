import sys
sys.path.insert(0, ".")
import data_checks as DC
rec = DC.run(save=False)
print("DCX", rec["errors"], rec["warnings"])
for i in rec["issues"]:
    print("DCX", i["level"], i["check"], i["detail"][:400])
