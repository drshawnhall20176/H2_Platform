import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B
for b in B.list_bets():
    if b.get("market") in ("Spread", "Total", "Moneyline", "Puck Line") and str(b.get("slate_date")) >= "2026-11-01":
        print({k: b.get(k) for k in ("sport", "game", "player", "market", "side", "line", "entry_odds", "book", "notes", "ts_placed")})
