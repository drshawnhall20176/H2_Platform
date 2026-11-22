import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import collections
import analyst_ledger as AL
rows = AL.fetch_calls()
print("total calls", len(rows), "keys", sorted(rows[0].keys()) if rows else None)
by = collections.defaultdict(lambda: collections.Counter())
for r in rows:
    c = by[(r["date"], r["sport"])]
    c["n"] += 1
    c["settled"] += bool(r.get("settled_at"))
    c["hit"] += r.get("hit") == 1 or r.get("hit") is True
    c["miss"] += r.get("hit") == 0 and r.get("hit") is not None and r.get("hit") is not False or r.get("hit") is False
    c["void"] += bool(r.get("settled_at")) and r.get("hit") is None
    c["pub"] += bool(r.get("published_at"))
    c["marked"] += r.get("last_line") is not None or r.get("last_price") is not None
    c["priced"] += r.get("price") is not None
for (d, s), c in sorted(by.items())[-120:]:
    print(d, s, dict(c))
days = sorted({r["date"] for r in rows})
print("days with any calls:", len(days), "first", days[:1], "last", days[-3:])
# logged_at hour distribution (ET) -> when were they locked
import pytz, datetime as dt
hrs = collections.Counter()
for r in rows[-3000:]:
    la = r.get("logged_at")
    try:
        t = dt.datetime.fromisoformat(str(la).replace("Z","+00:00")).astimezone(pytz.timezone("US/Eastern")); hrs[t.hour]+=1
    except Exception: pass
print("lock hour ET:", sorted(hrs.items()))
print("posts:", AL._run(None, "SELECT kind, sport, post_date, posted_at FROM analyst_posts ORDER BY post_date DESC LIMIT 15", fetch=True))
