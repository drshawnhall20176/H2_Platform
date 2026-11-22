import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pick_ledger as PL
for kind in ("strong","hot"):
    rows=list((PL.load(kind,"ALL","2026-11-22") or {}).get("rows",{}).values())
    pk=[r for r in rows if r.get("pickem_only") or r.get("price") is None]
    print(kind,"rows",len(rows),"pickem",len(pk),[ (r.get("pick"),r.get("earned"),r.get("first_seen")) for r in pk][:6])
