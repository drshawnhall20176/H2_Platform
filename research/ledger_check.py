import sys
sys.path.insert(0, ".")
import pick_ledger as PL
D = "2026-11-21"
for kind, sps in (("strong", ["ALL"]), ("money", ["NBA", "NHL", "NFL", "NCAAF", "NCAAMB"]), ("games", ["NCAAMB"])):
    for sp in sps:
        rs = PL.rows(kind, sp, D)
        print(f"LC {kind} {sp}: {len(rs)}")
        for r in rs[:20]:
            print(f"LC   {r.get('first_seen')} {r.get('sport')} {r.get('pick')} {r.get('price')} ch={r.get('chance')} t={r.get('time')} stake={r.get('stake')}")
