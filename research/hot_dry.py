import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hot_tickets as HT
c = HT.candidates(__import__("props_engine")._et_today())
print("candidates:", len(c))
for r in c[:10]: print("  ", r.get("sport"), r.get("pick"), r.get("price"), round(float(r["earned"]),3), round(r["need"],3), r.get("time"), r.get("game"))
HT.run(post=False)
