"""Nov 18: which of your bets have no closing price (so their CLV is unknown) -- by month, sport, market, book."""
import os, sys
from collections import Counter
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B
bets = B.list_bets()
for b in bets[:1]: print("KEYS", sorted(b.keys()))
nov = [b for b in bets if str(b.get("slate_date") or b.get("ts_placed"))[:7] == "2026-11"]
print("NOV bets", len(nov), "with close", sum(b.get("close_odds") is not None for b in nov))
c = Counter((b.get("sport"), b.get("market"), b.get("book"), b.get("close_odds") is not None) for b in nov)
for k, v in sorted(c.items(), key=lambda kv: -kv[1])[:30]: print("NC", k, v)
for b in [b for b in nov if b.get("close_odds") is None][:12]:
    print("NX", b.get("id"), b.get("sport"), b.get("player"), b.get("market"), b.get("side"), b.get("line"), b.get("book"), b.get("game"), b.get("slate_date"), str(b.get("notes"))[:60])
