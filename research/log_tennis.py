import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, model_store as MS, intl_picks as IP
recs = {r["game_id"]: r for r in MS.load_game_picks("TENNIS", ungraded=True)}
picks = [("c81851847baf5e3a479993ec167a8e2a", "away", 4.5, -110, 1 - 0.389),
         ("7ac3bf138012785e65835d1481524d5c", "away", 3.5, 100, 1 - 0.376)]
for gid, side, line, odds, mp in picks:
    f = IP.bet_fields(recs[gid], "Spread", side, line, odds, 3.0, True, model_prob=mp)
    f["book"] = "draftkings"
    print("logged", B.add_bet(**f), f["side"], f["market"], f["line"], f["entry_odds"], f["slate_date"], f["notes"])
