"""Nov 21 (owner: "I need today's strongest picks to be as accurate as possible ... refresh those with your
revisions"): replace today's strongest-picks ledger (15 picks ranked this morning by the model's raw chance) with the
list as it stands after the earned-chance rebuild."""
import sys
from datetime import datetime, timezone
sys.path.insert(0, ".")
import model_store as MS, pick_ledger as PL, todays_best as TB
D = "2026-11-21"
key = PL.KEY.format(kind="strong", sport="ALL", day=D)
old = PL.load("strong", "ALL", D)["rows"]
print(f"SR old ledger: {len(old)} picks")
for r in old.values():
    print(f"SR   old {r.get('sport')} {r.get('pick')} chance={r.get('chance')}")
MS.save_setting(key, {"rows": {}, "replaced": {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                               "old": list(old.values())}})
n = PL.record_strong(D)
print(f"SR new ledger: {n} picks")
for r in PL.rows("strong", "ALL", D):
    print(f"SR   new {r.get('time')} {r.get('sport')} {r.get('pick')} price={r.get('price')} model={r.get('raw_chance')} "
          f"earned={r.get('earned')} edge={PL.earned_edge(r)}")
