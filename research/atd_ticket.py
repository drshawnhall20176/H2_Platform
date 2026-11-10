import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B
n = 0
for b in B.list_bets():
    if B._ticket(b) and not B.is_parlay_header(b) and B._result(b) == "win" and B.leg_price(b) is None:
        n += 1
        print("AT", b["id"], b.get("slate_date"), B._ticket(b), b.get("player"), b.get("market"), b.get("side"), b.get("line"), b.get("notes"))
print("AT unpriced winning legs", n)
