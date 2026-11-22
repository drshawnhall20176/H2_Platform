import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hot_tickets as HT, props_engine as PE
HT.MAX_FAV = -100000
day = PE._et_today()
c = HT.candidates(day)
print("no price cap:", len(c))
for r in c[:12]: print("  ", r.get("sport"), r.get("pick"), r.get("price"), round(float(r["earned"]),3), round(r["need"],3), r.get("lock"), r.get("money"))
import pick_ledger as PL, todays_best as TB
n=0; big=[]
for k in PL.strong_keys():
    for r in (TB.load_props(k, day) or {}).get("rows") or []:
        n+=1
        if r.get("earned") is not None and r.get("price") is not None and float(r["price"]) <= -200: big.append((k, r["pick"], r["price"], round(r["earned"],3), r.get("lock")))
print("saved rows", n, "priced -200 or shorter with earned:", len(big)); print(big[:15])
