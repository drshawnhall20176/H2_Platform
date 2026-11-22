"""Nov 12: International Hoops, the Game Labs and the Tennis Lab log ticked games like Home and My Coach."""
import hoops_games_page as HG
import todays_best as TB

G = {"sport": "EUROLEAGUE", "game_id": "g1", "kickoff": "2026-11-12T19:30:00+00:00", "home": "Real Madrid",
     "away": "KK Crvena zvezda", "home_spread": -6.0, "edge": -4.4, "spread_price": -110, "model_p": 0.55,
     "model_margin": 1.6, "model_total": 174.7, "line_total": 176.5, "best_home": -250, "best_away": 200,
     "over_price": -110, "under_price": -105}


def test_tick_item_takes_the_models_side_of_each_market():
    sp = HG.tick_item(G, "Spread")
    assert sp["pick"] == "KK Crvena zvezda +6" and sp["bet_side"] == "away" and sp["bet_line"] == 6.0 and sp["price"] == -109   # Nov 20: the away side's own (estimated) price
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
    assert "gl:EUROLEAGUE:g1" in rows[0]["notes"] and rows[0]["stake"] == 2.0
    # Nov 17: a ⚪ No edge game's chance is untested, so it isn't logged as the model's probability
    item = HG.tick_item(G, "Spread")
    assert (rows[0]["model_prob"] is not None) == bool(item["best_tested"])
    assert rows[1]["market"] == "Moneyline" and rows[1]["entry_odds"] == -250


def test_college_football_game_lines_settle_from_finals_and_log_as_ncaaf():
    import intl_picks as IP
    p = {"sport": "NCAAF", "game_id": "g1", "home": "Notre Dame", "away": "Boston College", "kickoff": "2026-11-14T20:30:00Z",
         "final_home": 38.0, "final_away": 10.0, "result": None}
    f = IP.bet_fields(p, "Total", "under", 51.5, -110, 1.0, False)
    assert f["sport"] == "NCAAF"
    assert IP.bet_result(f, p) == "win"
    sp = IP.bet_fields(p, "Spread", "away", 16.5, -110, 1.0, False)
    assert IP.bet_result(sp, p) == "loss"
    ml = IP.bet_fields(p, "Moneyline", "home", None, -500, 1.0, False)
    assert IP.bet_result(ml, p) == "win"


# Nov 18: tick any side, not only the model's -- the other team, either side of the spread, Over or Under
F = {"sport": "EUROCUP", "game_id": "f1", "kickoff": "2026-11-18T19:30:00+00:00", "home": "Tortona", "away": "Trento",
     "model_p": 0.66, "model_margin": 4.9, "model_total": 161.3}


def test_any_side_can_be_ticked_at_the_book_line():
    it = HG.side_item(G, "Spread", "home")
    assert it["pick"] == "Real Madrid -6" and it["bet_line"] == -6.0 and it["price"] == -110
    ml = HG.side_item(G, "Moneyline", "away")
    assert ml["pick"] == "KK Crvena zvezda moneyline" and ml["price"] == 200 and abs(ml["chance"] - 0.45) < 1e-9
    assert HG.side_item(G, "Total", "over")["price"] == -110


def test_a_fair_only_league_starts_at_the_fair_line_with_no_price():
    sp = HG.side_item(F, "Spread", "home")
    assert sp["pick"] == "Tortona -5" and sp["bet_line"] == -5.0 and sp["price"] is None
    assert HG.side_item(F, "Spread", "away")["bet_line"] == 5.0
    assert HG.side_item(F, "Total", "under")["bet_line"] == 161.5
    assert HG.side_item(F, "Moneyline", "away")["pick"] == "Trento moneyline"
    got = HG.ticked_items([F, G], [(0, "✓ Away ML"), (1, "✓ Under"), (5, "✓ Over"), (0, "nope")])
    assert [x["pick"] for x in got] == ["Trento moneyline", "Under 176.5 (KK Crvena zvezda @ Real Madrid)"]


def test_an_alt_line_relabels_and_rescored():
    import log_ui as LU
    it = HG.side_item(F, "Spread", "home")
    alt = LU.relined(it, -4.5)
    assert alt["pick"] == "Tortona -4.5" and alt["bet_line"] == -4.5 and alt["chance"] > it["chance"]
    assert LU.relined(it, -5.0) is it and LU.relined(HG.side_item(F, "Moneyline", "home"), 3) ["bet_line"] is None
    rows = TB.bet_rows([dict(alt, price=-250)], 3.0, True, "eurocup-games", "2026-11-18")
    assert rows[0]["line"] == -4.5 and rows[0]["side"] == "Tortona" and "EUROCUP:f1" in rows[0]["notes"]


def test_book_tick_columns_sit_next_to_what_they_bet():
    import pandas as pd
    df = HG.with_book_ticks(pd.DataFrame([{"Game": "x", "The model says": "y", "Why": "z"}]), [G], after="The model says")
    cols = list(df.columns)
    assert cols.index("✓ Home spread") == cols.index("Book spread") + 1 and cols[-1] == "Why"
    assert df.loc[0, "Book ML"] == "Real Madrid -250 / +200"


def test_game_lines_board_logs_pick_winner_or_money_from_their_own_tick_boxes():
    """Nov 20 (owner): the game-lines board (sport desk and every Game Lab) had a tick for the Pick only."""
    import game_lines_table as GLT
    src = open("Home.py").read()
    assert '"✓ Pick"' in src and '"✓ Winner"' in src and '"✓ Money"' in src and "GLT.line_items" in src
    full = {"sport": "NCAAMB", "home": "Duke", "away": "Army", "home_spread": -8.5, "spread_price": -110,
            "best_home": -400, "best_away": 320, "model_p": 0.8, "model_margin": 9.0}
    row = {"winner": "Duke", "price": -400, "_full": full, "money_market": "Spread", "money_side": "away",
           "money_line": 8.5, "money_price": -108, "money_pick": "Army +8.5", "money": True}
    items = GLT.line_items([row], [(0, "✓ Winner"), (0, "✓ Money")])
    assert items[0]["pick"] == "Duke moneyline" and items[0]["price"] == -400 and items[0]["bet_market"] == "Moneyline"
    assert items[1]["pick"] == "Army +8.5" and items[1]["bet_line"] == 8.5 and items[1]["price"] == -108
    assert items[1]["bet_side"] == "away" and items[1]["note"] == "💰 Money pick"


def test_board_frame_puts_the_bets_left_and_results_only_on_past_days():
    import game_lines_table as GLT
    rows = [{"time": "7:00 PM", "sport": "NCAAMB", "game": "Army @ Duke", "winner": "Duke", "chance": 0.8, "price": -400,
             "best": "Army +8.5", "money_pick": "Duke -8.5", "money_price": -105, "money_score": 0.07, "money": False,
             "final": "Army 60 – Duke 75", "money_result": "win", "best_result": "loss", "winner_result": "win",
             "league": "NCAAMB"}]
    today = list(GLT.frame(rows, past=False).columns)
    assert today[:6] == ["Time", "Game", "✓ Money", "Money pick", "Money score", "✓ Pick"]
    assert "Final" not in today and "Sport" not in today
    past = list(GLT.frame(rows, past=True, show_sport=True).columns)
    assert past[:7] == ["Time", "Sport", "Game", "Final", "Money result", "Pick result", "Winner result"]


def test_select_all_ticks_every_row():
    """Nov 20 (owner): a select-all box on every ticked-row table."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string("""
import pandas as pd, streamlit as st, log_ui as LU, components as C
C.is_owner = lambda: True
rows = LU.selectable(pd.DataFrame({"Pick": ["a", "b", "c"]}), "t_sel")
st.write(f"picked={rows}")
""").run()
    assert "picked=[]" in " ".join(m.value for m in at.markdown)
    at.checkbox(key="t_sel__all").check().run()
    assert "picked=[0, 1, 2]" in " ".join(m.value for m in at.markdown)


def test_tracking_only_logs_picks_without_a_price(monkeypatch):
    """Nov 20 (owner): pick'em-only picks have no price; tracking-only logging records them at -110."""
    from streamlit.testing.v1 import AppTest
    import todays_best as TB
    got = {}

    def fake_log(its, mode, stake, pstake, podds, real, tag, date_str):
        got["its"], got["real"] = its, real
        return {"singles": its, "ticket": None, "skipped": 0}
    monkeypatch.setattr(TB, "log_selection", fake_log)
    at = AppTest.from_string("""
import streamlit as st, log_ui as LU, components as C
C.is_owner = lambda: True
LU.panel([{"sport": "NCAAMB", "pick": "A Rebounds Under 6.5", "player": "A", "side": "Under", "line": 6.5,
           "market": "Rebounds", "price": None}], "t_log", "2026-11-20")
""").run()
    at.checkbox(key="t_log_real").uncheck().run()
    at.button(key="t_log_go").click().run()
    assert got["its"][0]["price"] == -110 and got["real"] is False


def test_tick_grid_select_all_per_column():
    """Nov 20 (owner): a select-all box for each tick column."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string("""
import pandas as pd, streamlit as st, log_ui as LU, components as C
C.is_owner = lambda: True
df = pd.DataFrame({"Game": ["a", "b", "c"], "✓ Money": [False] * 3, "✓ Pick": [False] * 3})
st.write(f"ticks={LU.tick_grid(df, ['✓ Money', '✓ Pick'], 'g')}")
""").run()
    assert "ticks=[]" in " ".join(m.value for m in at.markdown)
    at.checkbox(key="g__all_✓ Money").check().run()
    assert "ticks=[(0, '✓ Money'), (1, '✓ Money'), (2, '✓ Money')]" in " ".join(m.value for m in at.markdown)


def test_the_book_columns_star_the_models_side():
    """Nov 22 (owner): the preferred pick in the multi-column tick table."""
    import pandas as pd
    import hoops_games_page as HG
    g = {"home": "Nebraska", "away": "Butler", "home_spread": -12.5, "model_margin": 19.0, "line_total": 140.5,
         "model_total": 136.0, "model_p": 0.90, "fair_home": 0.86, "best_home": -900, "best_away": 600}
    df = HG.with_book_ticks(pd.DataFrame([{"Game": "x", "Gap (pts)": 6.5}]), [g], after="Gap (pts)")
    assert df.loc[0, "Book spread"] == "⭐ Home: Nebraska -12.5"
    assert df.loc[0, "Book total"] == "140.5 · ⭐ Under" and df.loc[0, "Book ML"].endswith("· ⭐ Home")
    g2 = dict(g, model_margin=8.0, model_total=150.0, model_p=0.80)
    df2 = HG.with_book_ticks(pd.DataFrame([{"Game": "x", "Gap (pts)": 4.5}]), [g2], after="Gap (pts)")
    assert df2.loc[0, "Book spread"] == "⭐ Away: Butler +12.5" and df2.loc[0, "Book total"].endswith("⭐ Over")
    assert df2.loc[0, "Book ML"].endswith("⭐ Away")
