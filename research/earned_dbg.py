import sys
sys.path.insert(0, ".")
import todays_best as TB, props_money as PM, best_bets_data as BBD
D = "2026-11-21"
for k in ("NCAAMB", "NHL"):
    got = TB.load_props(k, D) or {}
    print("ED", k, got.get("at"))
    for r in got.get("rows") or []:
        print("ED  row", r.get("pick"), "earned" in r, r.get("earned"), r.get("chance"), r.get("price"), r.get("pickem_only"))
    sb = BBD.saved_board(k, D, BBD.O.DEFAULT_BOOK, now=0)
    plays = (sb or [[]])[0]
    print("ED  board plays", len(plays))
    for p in plays[:3]:
        print("ED  play", p.get("Player"), p.get("Market"), p.get("Side"), p.get("ModelRaw"), p.get("MarketProb"), p.get("Pickem"), PM.play_earned(k, p))
