import sys
sys.path.insert(0, ".")
import todays_best as TB, pick_ledger as PL
D = "2026-11-21"
picks = []
for k in PL.strong_keys():
    rows = (TB.load_props(k, D) or {}).get("rows") or []
    picks += [dict(r, sport=r.get("sport") or k) for r in rows]
    e = [r for r in rows if r.get("earned") is not None]
    print(f"EC {k}: {len(rows)} saved, {len(e)} with earned")
top = PL.strongest(picks)
print(f"EC strongest {len(top)}")
for r in top:
    print(f"EC  {r['sport']} {r['pick']} price={r.get('price')} model={r.get('raw_chance')} earned={r.get('earned'):.3f} edge={r['earned_edge']:+.3f}")
