"""Nov 17: log the owner's five NBA long shots ($1 singles, DraftKings) for the team challenge."""
import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, model_store as MS, props_engine as PE
picks = [("Derrick Jones Jr.", "Threes Made", 2.5, 479, 0.246, "Utah Jazz @ LA Clippers"),
         ("Grayson Allen", "Assists", 5.5, 452, 0.217, "Charlotte Hornets @ Los Angeles Lakers"),
         ("Karl-Anthony Towns", "Assists", 5.5, 518, 0.198, "New York Knicks @ Toronto Raptors"),
         ("Rudy Gobert", "RA", 17.5, 450, 0.201, "Portland Trail Blazers @ Minnesota Timberwolves"),
         ("Keldon Johnson", "Rebounds", 8.5, 572, 0.191, "Detroit Pistons @ San Antonio Spurs")]
snaps = MS.load_snapshots("NBA", ["2026-11-17"])
ids = {PE.norm_name(s.get("player")): s.get("player_id") for s in snaps}
for player, mk, line, odds, ch, game in picks:
    f = {"slate_date": "2026-11-17", "sport": "NBA", "game": game, "player": player,
         "player_id": ids.get(PE.norm_name(player)), "market": mk, "side": "Over", "line": line,
         "entry_odds": float(odds), "entry_odds_source": "manual", "stake": 1.0, "book": "draftkings",
         "is_real_bet": True, "model_prob": ch, "category": B.default_category("NBA", from_model=True),
         "notes": "long-shot; team challenge Nov 17 (one per game)"}
    print("logged", B.add_bet(**f), player, mk, line, odds, ids.get(PE.norm_name(player)))
