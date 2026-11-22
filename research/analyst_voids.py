import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import collections, analyst_ledger as AL
rows = AL.fetch_calls()
for sp in ("NFL","NBA","NHL","NCAAF"):
    c = collections.Counter(); v = collections.Counter()
    for r in rows:
        if r["sport"] != sp or not r.get("settled_at"): continue
        c[r["market"]] += 1
        if r.get("hit") is None: v[r["market"]] += 1
    print(sp, {m: f"{v[m]}/{c[m]}" for m in c})
ex = [r for r in rows if r["sport"]=="NFL" and r["date"]=="2026-11-01" and r.get("hit") is None][:12]
for r in ex: print("  void", r["player"], r["market"], r["side"], r["line"], r.get("actual"))
