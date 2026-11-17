"""Nov 17: log the owner's six NCAAMB singles ($2 each, DraftKings) -- game, team and player id from today's board."""
import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, model_store as MS
picks = [("condon", "PRA", 24.5, -205), ("koehler", "Threes Made", 1.5, 125), ("shrewsberry", "PRA", 19.5, 130),
         ("braden smith", "Assists", 6.5, 400), ("chinyelu", "PRA", 19.5, -250), ("haugh", "Points", 14.5, -245)]
snaps = MS.load_snapshots("NCAAMB", ["2026-11-17"])
print("snapshots", len(snaps))
for key, mk, line, odds in picks:
    cand = [s for s in snaps if key in str(s.get("player")).lower()]
    exact = [s for s in cand if s.get("market") == mk]
    s = max(exact or cand, key=lambda x: str(x.get("ts")), default=None)
    if s is None:
        print("NOT ON BOARD", key, mk); continue
    f = {"slate_date": "2026-11-17", "sport": "NCAAMB", "game": s.get("game"), "player": s.get("player"),
         "player_id": s.get("player_id"), "market": mk, "side": "Over", "line": line, "entry_odds": float(odds),
         "entry_odds_source": "manual", "stake": 2.0, "book": "draftkings", "is_real_bet": True,
         "model_prob": (s.get("chance") if s.get("market") == mk and s.get("side") == "Over" and s.get("line") == line else None),
         "category": B.default_category("NCAAMB", from_model=False), "notes": "owner single; slip Nov 17"}
    print("logged", B.add_bet(**f), s.get("player"), mk, line, odds, "|", s.get("game"), "| board:",
          s.get("market"), s.get("line"), s.get("projection"), s.get("side"), s.get("chance"), s.get("use_tag"))
