import sys
sys.path.insert(0, ".")
import pick_ledger as PL
D = "2026-11-21"
print(f"SA added {PL.record_strong(D)}")
for r in PL.rows("strong", "ALL", D):
    print(f"SA {r.get('time')} {r.get('sport')} {r.get('kind')} {r.get('pick')} {r.get('price')} earned={r.get('earned')} edge={PL.earned_edge(r)}")
