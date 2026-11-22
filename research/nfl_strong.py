import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB, pick_ledger as PL, props_engine as PE
day = PE._et_today()
rows = [dict(r, sport="NFL") for r in (TB.load_props("NFL", day) or {}).get("rows") or []]
print("saved NFL rows", len(rows))
for r in sorted(rows, key=lambda r: -(PL.earned_edge(r) or -9))[:14]:
    print("  ", r.get("time"), r.get("pick"), r.get("price"), "ee", None if PL.earned_edge(r) is None else round(PL.earned_edge(r),3), "started" if PL.started(day, r) else "", "kept" if r.get("on_board") is False or r.get("kept") else "")
print("strongest NFL now:", [(r.get("time"), r.get("pick")) for r in PL.strongest(rows)])
led = [(r.get("time"), r.get("pick"), r.get("first_seen","")[11:16]) for r in PL.rows("strong","ALL",day) if r.get("sport")=="NFL"]
print("ledger NFL today:", led)
