"""Nov 18: the 🔒 Most probable record split -- sportsbook lines vs lines only a pick'em app posted."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, postgame as PG, props_engine as PE
for sport in ("NBA", "NFL", "NHL", "NCAAF", "NCAAMB"):
    dates = MS.snapshot_dates(sport)
    snaps = MS.load_snapshots(sport, dates)
    g = []
    for d in sorted({s["slate_date"] for s in snaps}):
        day = [s for s in snaps if s["slate_date"] == d]
        try:
            g += PG.grade(day, PG.fetch_results(sport, d, sorted({(s["team"], s["opp"]) for s in day})))
        except Exception as e:
            print("LS err", sport, d, e)
    g = [r for r in g if r.get("result") in ("hit", "miss") and PE.most_probable(r.get("chance"), r.get("cushion"), r.get("gap"))]
    for name, rows in (("book", [r for r in g if (r.get("book") or "") not in PE.PICKEM_BOOKS]),
                       ("pickem", [r for r in g if (r.get("book") or "") in PE.PICKEM_BOOKS])):
        h = sum(r["result"] == "hit" for r in rows); n = len(rows)
        ch = sum(r["chance"] for r in rows) / n if n else 0
        print("LS", sport, name, f"{h}-{n-h}", f"{h/n:.1%}" if n else "-", "model said", f"{ch:.1%}")
