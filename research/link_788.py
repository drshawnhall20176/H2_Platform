"""Nov 19: link bet #788 (Zalgiris Kaunas II @ Mazeikiai, Over 178.5) to its NKL game so it settles itself."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, model_store as MS, intl_picks as IP
p = next(p for p in MS.load_game_picks("NKL") if "algiris-2" in p["away"] and "ažeiki" in p["home"])
f = IP.bet_fields(dict(p, sport="NKL"), "Total", "over", 178.5, -115, 3.0, True)
ch = IP.fair_chance(dict(p, sport="NKL"), "Total", "over", 178.5)
B.update_bet(788, game=f["game"], sport=f["sport"], notes="DK slip 11/19," + f["notes"],
             model_prob=None if ch is None else round(ch, 4), category=f["category"])
b = next(b for b in B.list_bets() if int(b["id"]) == 788)
print("L7", {k: b.get(k) for k in ("id", "game", "market", "side", "line", "entry_odds", "model_prob", "notes", "sport")})
