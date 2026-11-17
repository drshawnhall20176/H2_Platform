import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B
B.update_bet(755, player="Braeden Smith")
b = [x for x in B.list_bets() if x.get("id") == 755][0]
print("FIXED", b.get("id"), b.get("player"), b.get("market"), b.get("line"), b.get("entry_odds"), b.get("game"))
