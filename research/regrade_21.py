import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pick_ledger as PL
print(PL.grade_day("2026-11-21"))
for r in PL.rows("strong","ALL","2026-11-21"):
    if r.get("player") in ("Elija Lofton","Caden High"): print(r.get("player"), r.get("result"))
print("record:", PL.record("strong","ALL","2026-11-21"))
import data_checks as DC
try: DC.main([])
except SystemExit: pass
import health_check as HC
rec = HC.run(); print("health:", rec["state"], [i["text"] for i in rec["items"] if i["level"] != "info"])
