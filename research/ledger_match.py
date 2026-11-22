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
        print("  UNMATCHED", r.get("_day"), r.get("sport"), r.get("game"), r.get("time"), r.get("kickoff"))
for when, sp, e, items in plan:
    print(f"  {when:%m-%d %H:%M}Z {sp} {e['away_team']} @ {e['home_team']}: {len(items)} picks; markets {LC.markets_for(items, sp)}")
import pick_ledger as PL
for d in ("2026-11-21","2026-11-22"):
    for k in ("strong",):
        for r in PL.rows(k,"ALL",d):
            if r.get("sport")=="NFL": print("NFLROW", d, r.get("game"), r.get("time"), r.get("first_seen"), r.get("result"))
for e in ev.get("NFL", [])[:16]: print("NFLEV", e["away_team"], "@", e["home_team"], e["commence_time"])
