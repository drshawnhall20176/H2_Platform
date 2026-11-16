import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B
bets = B.list_bets(settled=False)
print("open bets", len(bets))
for b in bets[-25:]:
    print({k: b.get(k) for k in b if b.get(k) not in (None, "")})
