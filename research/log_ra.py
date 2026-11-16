import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, model_store as MS
picks = {"Jayson Tatum": (13.5, 100), "Alperen Sengun": (16.5, -110), "Trae Young": (11.5, -128)}
latest = {}
for s in MS.load_snapshots("NBA", ["2026-11-16"]):
    if s.get("market") == "RA" and s.get("player") in picks:
        if s["player"] not in latest or str(s.get("ts")) > str(latest[s["player"]].get("ts")): latest[s["player"]] = s
for p, (line, odds) in picks.items():
    s = latest[p]
    f = {"slate_date": "2026-11-16", "sport": "NBA", "game": s.get("game"), "player": p, "player_id": s.get("player_id"),
         "market": "RA", "side": "Under", "line": line, "entry_odds": float(odds), "entry_odds_source": "manual",
         "model_prob": s.get("chance"), "stake": 2.0, "book": "draftkings", "is_real_bet": True,
         "category": B.default_category("NBA", from_model=True), "notes": "Reb+Ast; slip check Nov 16"}
    print("logged", B.add_bet(**f), p, s.get("game"), s.get("player_id"))
