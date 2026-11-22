import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone
import close_watch as W, ledger_close as LC
now = datetime.now(timezone.utc)
rows = W._ledger_rows(now)
print("shown picks today:", len(rows), "days", LC.slate_days(now))
ev = W._events(os.environ["ODDS_API_KEY"], sorted({r.get("sport") for r in rows}))
plan = W.ledger_plan(rows, ev)
matched = sum(len(g[3]) for g in plan)
print("matched to an event:", matched, "in", len(plan), "games")
ids = {id(r) for g in plan for r in g[3]}
for r in rows:
    if id(r) not in ids:
        print("  UNMATCHED", r.get("sport"), r.get("game"), r.get("time"), r.get("kickoff"))
for when, sp, e, items in plan:
    print(f"  {when:%m-%d %H:%M}Z {sp} {e['away_team']} @ {e['home_team']}: {len(items)} picks; markets {LC.markets_for(items, sp)}")
