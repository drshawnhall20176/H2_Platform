import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B
bs = [b for b in B.list_bets() if b.get("market") in ("Spread", "Total", "Moneyline", "Puck Line")]
for b in bs[-8:]:
    print("GL", {k: b.get(k) for k in ("id", "sport", "player", "market", "side", "line", "entry_odds", "close_odds", "book", "game", "slate_date")})
print("GL count", len(bs), "with close", sum(b.get("close_odds") is not None for b in bs))
