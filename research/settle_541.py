import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B
b = next(x for x in B.list_bets() if x["id"] == 541)
B.update_bet(541, result="loss", notes=((b.get("notes") or "") + ",Stefanini retired QF 6-2 5-2; settled per one-set-completed rule").strip(","))
b = next(x for x in B.list_bets() if x["id"] == 541)
print("S5", b["id"], b.get("result"), B.bet_pnl(b))
