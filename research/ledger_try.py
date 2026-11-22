import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone
import close_watch as W
now = datetime.now(timezone.utc)
rows = [r for r in W._ledger_rows(now) if r["_day"] == "2026-11-22"]
ev = W._events(os.environ["ODDS_API_KEY"], sorted({r.get("sport") for r in rows}))
for when, sp, e, items in W.ledger_plan(rows, ev):
    got = W.capture_ledger(e, items, os.environ["ODDS_API_KEY"], sp)   # no save: a dry run
    print(f"{sp} {e['away_team']} @ {e['home_team']}: {len(got)}/{len(items)}")
    for r in items:
        import ledger_close as LC
        print("   ", r.get("pick"), r.get("book"), r.get("line") if not r.get("money_market") else r.get("money_line"), r.get("price"), "->", got.get(LC.cap_key(r)))
