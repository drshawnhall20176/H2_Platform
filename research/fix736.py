import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B
B.update_bet(736, entry_odds=945.0)
b = next(x for x in B.list_bets() if x.get("id") == 736)
print("BET", b["id"], b.get("market"), b.get("entry_odds"), b.get("stake"))
