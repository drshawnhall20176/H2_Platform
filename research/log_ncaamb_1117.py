"""Nov 17: log the owner's six NCAAMB singles ($2 each, DraftKings), Notre Dame @ Florida (no NCAAMB board today)."""
import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B
G = "Notre Dame Fighting Irish @ Florida Gators"
picks = [("Alex Condon", "PRA", 24.5, -205), ("Brady Koehler", "Threes Made", 1.5, 125),
         ("Braeden Shrewsberry", "PRA", 19.5, 130), ("B. Smith", "Assists", 6.5, 400),
         ("Rueben Chinyelu", "PRA", 19.5, -250), ("Thomas Haugh", "Points", 14.5, -245)]
print("fields", B._FIELDS if hasattr(B, "_FIELDS") else "")
for player, mk, line, odds in picks:
    f = {"slate_date": "2026-11-17", "sport": "NCAAMB", "game": G, "player": player, "market": mk, "side": "Over",
         "line": line, "entry_odds": float(odds), "entry_odds_source": "manual", "stake": 2.0, "book": "draftkings",
         "is_real_bet": True, "category": B.default_category("NCAAMB", from_model=False),
         "notes": "owner single; DraftKings slip Nov 17"}
    print("logged", B.add_bet(**f), player, mk, line, odds)
