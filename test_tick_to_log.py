"""Nov 12: International Hoops, the Game Labs and the Tennis Lab log ticked games like Home and My Coach."""
import hoops_games_page as HG
import todays_best as TB

G = {"sport": "EUROLEAGUE", "game_id": "g1", "kickoff": "2026-11-12T19:30:00+00:00", "home": "Real Madrid",
     "away": "KK Crvena zvezda", "home_spread": -6.0, "edge": -4.4, "spread_price": -110, "model_p": 0.55,
     "model_margin": 1.6, "model_total": 174.7, "line_total": 176.5, "best_home": -250, "best_away": 200,
     "over_price": -110, "under_price": -105}


def test_tick_item_takes_the_models_side_of_each_market():
    sp = HG.tick_item(G, "Spread")
    assert sp["pick"] == "KK Crvena zvezda +6" and sp["bet_side"] == "away" and sp["bet_line"] == 6.0 and sp["price"] == -110
    ml = HG.tick_item(G, "Moneyline")
    assert ml["pick"] == "Real Madrid moneyline" and ml["price"] == -250 and ml["bet_line"] is None
    tot = HG.tick_item(G, "Total")
    assert tot["bet_side"] == "under" and tot["price"] == -105 and tot["bet_line"] == 176.5
    assert HG.tick_item(dict(G, line_total=None), "Total") is None


def test_ticked_games_become_gradeable_bet_log_rows():
    rows = TB.bet_rows([HG.tick_item(G, "Spread"), HG.tick_item(G, "Moneyline")], 2.0, True, "euroleague-games",
                       "2026-11-12")
    assert len(rows) == 2
    assert rows[0]["market"] == "Spread" and rows[0]["line"] == 6.0 and rows[0]["side"] == "KK Crvena zvezda"
    assert "gl:EUROLEAGUE:g1" in rows[0]["notes"] and rows[0]["stake"] == 2.0 and rows[0]["model_prob"] is not None
    assert rows[1]["market"] == "Moneyline" and rows[1]["entry_odds"] == -250
