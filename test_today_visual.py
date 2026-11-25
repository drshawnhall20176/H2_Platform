"""Nov 25: the game card and the clickable Today cards -- commercial preview only."""
import game_card as GC
import today_visual as TV
from test_customer_pages import RECS, _p



import pytest as _pytest_today


@_pytest_today.fixture(autouse=True)
def _no_schedule_calls(monkeypatch):
    """Nov 25: Today asks each sport's schedule which sports have games -- never the network in tests."""
    import customer_today as _CT
    monkeypatch.setattr(_CT, "has_games", lambda key, day: False)

def _game(sport="NCAAMB", home="Duke Blue Devils", away="Army Black Knights", kickoff="2026-11-25T00:00:00Z", **kw):
    full = {"home": home, "away": away, "home_spread": -12.5, "line_total": 141.5, "model_margin": 11.0,
            "model_total": 139.0, "kickoff": kickoff, "game_id": "g1"}
    full.update(kw)
    return {"sport": sport, "league": sport, "game": f"{away} @ {home}", "time": "7:00 PM", "winner": home,
            "chance": 0.84, "price": -900, "best": f"{away} +12.5", "best_chance": 0.55, "best_price": -110,
            "best_tested": False, "spread_txt": f"{home} -12.5", "total_txt": "141.5",
            "model_txt": f"{home} by 11.0, total 139.0", "_rec": {"sport": sport, "home": home, "away": away,
                                                                  "kickoff": kickoff},
            "_full": full}


def test_scores_split_a_margin_and_total():
    assert GC.scores(11, 139) == {"home": 75.0, "away": 64.0}
    assert GC.scores(None, 139) is None and GC.scores("x", 1) is None


def test_build_reads_the_board_row(monkeypatch):
    import game_previews as GP
    monkeypatch.setattr(GP, "blowout", lambda lg, p: "🟨 44%")
    monkeypatch.setattr(GP, "_last", lambda lg, p: "Duke won 1 of 1")
    g = GC.build(_game())
    assert g["model"] == {"home": 75.0, "away": 64.0} and g["market"] == {"home": 77.0, "away": 64.5}
    assert abs(g["gap"] - 1.5) < 1e-9 and g["blowout_pct"] == 0.44 and g["last"] == "Duke won 1 of 1"
    assert g["spread"] == "Duke Blue Devils -12.5" and g["winner"] == "Duke Blue Devils"
    assert g["money_pick"] is None                                         # no 💰 flag, no money pick shown


def test_build_never_breaks_on_a_thin_row():
    g = GC.build({"sport": "NBA", "game": "A @ B"})
    assert g["game"] == "A @ B" and g["model"] is None and g["gap"] is None
    html = GC.header_html(g) + GC.meters_html(g)
    assert "—" in html


def test_meters_mark_the_close_gap_zone():
    html = GC.meters_html({"gap": 1.5, "blowout_pct": 0.7, "win_chance": 0.8, "winner": "X"})
    assert "1.5 pts apart" in html and "70%" in html and "80%" in html and "X" in html


def test_props_match_their_game_by_team_names():
    w = _game()
    rows = [dict(_p("NCAAMB", "Flagg Points Over 20.5", 0.6), game="Army @ Duke", player="Flagg"),
            dict(_p("NCAAMB", "Someone Else", 0.6), game="UNC @ Kentucky", player="Else"),
            dict(_p("NBA", "Wrong sport", 0.6), game="Army @ Duke")]
    # last names: "knights" / "devils" -- the short string has neither, so it doesn't match
    assert TV.props_in_game(rows, w) == []
    rows[0]["game"] = "Army Black Knights @ Duke Blue Devils"
    assert [r["pick"] for r in TV.props_in_game(rows, w)] == ["Flagg Points Over 20.5"]
    assert TV.same_game("Black Knights at Blue Devils", "Duke Blue Devils", "Army Black Knights")


def test_games_are_earliest_first_and_started_ones_last():
    a = _game(home="H1", away="A1", kickoff="2099-01-01T02:00:00Z")
    b = _game(home="H2", away="A2", kickoff="2099-01-01T00:00:00Z")
    c = _game(home="H3", away="A3", kickoff="2000-01-01T00:00:00Z")        # long started
    assert [w["_rec"]["home"] for w in TV.games_for([a, b, c], "NCAAMB")] == ["H2", "H1", "H3"]


def test_sport_cards_props_then_lines_and_the_row_is_found_again():
    import pick_records as PR
    rows = [dict(_p("NBA", "A Assists Over 5.5", 0.61), player="A")]
    cards = TV.sport_cards("NBA", rows, [], "2026-11-25", records_for=RECS.get)
    assert [c["pick"] for c in cards] == ["A Assists Over 5.5"] and cards[0]["kind"] == "Prop"
    assert TV.prop_row_for(rows, cards[0]) is rows[0]
    html = TV.pick_card_html(cards[0])
    assert "A Assists Over 5.5" in html and "61%" in html


def test_today_page_shows_cards_only_in_the_commercial_preview(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import nav_layout as NL
    import pick_records as PR
    import streamlit as st
    import todays_best as TB
    st.cache_data.clear()
    monkeypatch.setattr(TB, "collect", lambda day, keys, past=False: {"rows": [dict(_p("NBA", "A Assists Over 5.5", 0.61),
                                                                                    player="A")], "props": {}})
    monkeypatch.setattr(TB, "winner_rows", lambda day, leagues=None, past=False: [dict(_game(sport="NBA", home="B", away="A"), best_tested=True)])
    monkeypatch.setattr(PR, "tag_records", lambda sp: RECS.get(sp, {}))
    monkeypatch.setattr(PR, "lean_records", lambda lg, days=30, recs=None: {})
    import sports
    monkeypatch.setattr(sports, "in_season", lambda k, day=None: k == "NBA")
    # preview off (the owner's live view): the tables, no card view at all
    at = AppTest.from_file("views/57_Today.py", default_timeout=60).run()
    assert not at.exception and len(at.dataframe) == 2
    assert not [b for b in at.button if b.key and b.key.startswith("tv_")]
    # preview on: cards with Open buttons, a game strip, no tables
    at = AppTest.from_file("views/57_Today.py", default_timeout=60)
    at.session_state[NL.PREVIEW_KEY] = True
    at.run()
    assert not at.exception
    keys = [b.key for b in at.button if b.key]
    assert "tv_card_NBA_0" in keys and "tv_game_NBA_0" in keys and not at.dataframe
    at.button(key="tv_game_NBA_0").click().run()                         # opens the game card pop-up
    assert not at.exception
    # Table in the preview: the tables come back
    at.segmented_control(key="today_view").set_value("Table").run()
    assert not at.exception and len(at.dataframe) == 2


def test_the_game_card_pop_up_draws_the_card(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import game_previews as GP
    monkeypatch.setattr(GP, "blowout", lambda lg, p: "🟩 20%")
    monkeypatch.setattr(GP, "_last", lambda lg, p: "—")

    def app():
        import today_visual as TV
        from test_today_visual import _game
        TV._game_dialog(_game(), [])
    at = AppTest.from_function(app, default_timeout=60).run()
    assert not at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "PROJECTED SCORE" in html and "Model vs market" in html and "Line pick" in html


def test_matchup_chip_in_words_not_letter_grades():
    import player_card as PC
    assert PC.matchup_chip(1.10, "G")["text"].startswith("Soft matchup · allows +10% to guards")
    assert PC.matchup_chip(1.04, "C")["tone"] == "soft" and "Leans soft" in PC.matchup_chip(1.04, "C")["text"]
    assert PC.matchup_chip(0.90, "F")["text"].startswith("Tough matchup · allows -10% to forwards")
    assert PC.matchup_chip(1.0, None)["tone"] == "even" and PC.matchup_chip(None) is None
    assert PC.matchup_chip(float("nan")) is None


def test_minutes_rows_oldest_left_and_saved_rows_carry_minutes():
    import player_card as PC
    rows = PC.minutes_rows([34.0, 30.5, None, 28.0])
    assert [r["Game"] for r in rows] == ["3 ago", "2 ago", "Last"] and rows[-1]["Minutes"] == 34.0
    c = PC.from_row({"player": "A", "side": "Over", "line": 20.5, "mins": [30, 31], "proj_min": 32.5,
                     "factor": 1.05, "slot": "G"})
    assert c["_mins"] == [30, 31] and c["_proj_min"] == 32.5 and c["_factor"] == 1.05 and c["_slot"] == "G"


def test_player_card_extras_only_when_asked(monkeypatch):
    from streamlit.testing.v1 import AppTest

    def app(extras):
        import player_card as PC
        PC.render({"Player": "A", "Side": "Over", "Line": 20.5, "Market": "Points", "_values": [22, 18, 25],
                   "_mins": [33, 30, 35], "_proj_min": 32, "_factor": 1.09, "_slot": "G"}, "NBA", extras=extras)
    on = AppTest.from_function(app, args=(True,), default_timeout=60).run()
    off = AppTest.from_function(app, args=(False,), default_timeout=60).run()
    assert not on.exception and not off.exception
    txt = lambda at: " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "Soft matchup" in txt(on) and "His minutes" in txt(on)
    assert "Soft matchup" not in txt(off) and "His minutes" not in txt(off)


def test_search_lists_each_player_pick_once():
    rows = [dict(_p("NBA", "A Points Over 20.5", 0.6), player="A", market="Points"),
            dict(_p("NBA", "A Points Over 20.5", 0.6), player="A", market="Points"),
            dict(_p("NBA", "A Assists Over 5.5", 0.6), player="A", market="Assists"),
            dict(_p("NBA", "line", 0.6), kind="Game line")]
    assert [r["pick"] for r in TV.search_options(rows)] == ["A Points Over 20.5", "A Assists Over 5.5"]


def test_favorites_show_first_on_today_in_the_preview(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import nav_layout as NL
    import pick_records as PR
    import sports
    import streamlit as st
    import todays_best as TB
    st.cache_data.clear()
    monkeypatch.setattr(TB, "collect", lambda day, keys, past=False: {"rows": [
        dict(_p("NBA", "A Assists Over 5.5", 0.61), player="A", market="Assists"),
        dict(_p("NBA", "Zed Points Over 9.5", 0.55), player="Zed", market="Points")], "props": {}})
    monkeypatch.setattr(TB, "winner_rows", lambda day, leagues=None, past=False: [_game(sport="NBA", home="B", away="A")])
    monkeypatch.setattr(PR, "tag_records", lambda sp: RECS.get(sp, {}))
    monkeypatch.setattr(PR, "lean_records", lambda lg, days=30, recs=None: {})
    monkeypatch.setattr(sports, "in_season", lambda k, day=None: k == "NBA")
    at = AppTest.from_file("views/57_Today.py", default_timeout=60)
    at.session_state[NL.PREVIEW_KEY] = True
    at.session_state[TV.FAV_KEY] = ["Zed"]
    at.run()
    assert not at.exception
    assert any("Your players tonight" in m.value for m in at.markdown)
    assert "tv_fav_0" in [b.key for b in at.button if b.key]
    at.selectbox(key="tv_search").set_value(0).run()                    # search opens the player card
    assert not at.exception


def test_a_pick_with_no_chance_says_what_it_is_not_a_dash():
    html = TV.pick_card_html({"pick": "Marquette +5.5", "chance": None, "price": "—", "bet": "🧪 Tracking",
                              "basis": "Line pick", "game": "Virginia @ Marquette", "time": "12:00 PM"})
    assert "Line pick" in html and ">—<" not in html


def test_player_card_names_the_opponent_from_the_game():
    import player_card as PC
    assert PC.opponent("Brooklyn Nets @ Milwaukee Bucks", "Milwaukee Bucks") == "Brooklyn Nets"
    assert PC.opponent("Brooklyn Nets @ Milwaukee Bucks", "Brooklyn Nets") == "Milwaukee Bucks"
    assert PC.opponent("A @ B", "C") is None and PC.opponent(None, "A") is None
    assert PC.from_row({"player": "K", "side": "Under", "game": "Brooklyn Nets @ Milwaukee Bucks",
                        "team": "Milwaukee Bucks"})["Opp"] == "Brooklyn Nets"


def test_the_read_explains_form_matchup_and_projection():
    import player_card as PC
    b = PC.read_bullets({"Side": "Under", "Line": 14.5, "Market": "Pts+Reb", "Projection": 11.71, "ModelProb": .57,
                         "_earned": .54, "_values": [13, 16, 19, 14], "_factor": 0.94, "_slot": "C",
                         "_mins": [22, 25], "_proj_min": 23,
                         "Why": "form 14.5, matchup -6%, projects 11.7 vs 14.5 · back-to-back"}, "🃏 Bet")
    txt = "\n".join(b)
    assert "Recent form 14.5 Pts+Reb" in txt and "newer games count more" in txt
    assert "allowed 6% less than the league average to centers" in txt and "down 6%" in txt
    assert "leans **Under**" in txt and "earned chance 54%" in txt and "ℹ️ back-to-back" in txt
    assert PC.read_bullets({}) == []


def test_a_tested_tag_with_an_earned_chance_below_break_even_is_tracking():
    import game_previews as GP
    assert abs(GP.break_even(-110) - 0.5238) < 1e-3 and GP.break_even(150) == 0.4 and GP.break_even(None) is None
    weak = {"earned": 0.50, "price": -111}
    strong = {"_earned": 0.58, "RealPrice": -110}
    assert GP.prop_bet("NBA", "🎟️ Parlay leg", weak, earned_rule=True) == GP.BET_TRACK
    assert GP.prop_bet("NBA", "🎟️ Parlay leg", strong, earned_rule=True) == GP.BET_YES
    assert GP.prop_bet("NBA", "🎟️ Parlay leg", weak, earned_rule=False) == GP.BET_YES     # the switch
    assert GP.prop_bet("NBA", "🎟️ Parlay leg", weak) == GP.BET_TRACK                      # Nov 25: on everywhere
    assert GP.prop_bet("NBA", "🎟️ Parlay leg", {"price": -110}, earned_rule=True) == GP.BET_YES   # no earned: as before
    import player_card as PC
    txt = "\n".join(PC.read_bullets({"Side": "Under", "Line": 22.5, "earned": 0.5, "price": -111,
                                     "_earned": 0.5, "RealPrice": -111}, GP.BET_TRACK))
    assert "Tracking, not a bet" in txt and "50%" in txt and "52.6%" in txt


def test_search_reads_the_full_saved_list_and_drops_the_repeated_name():
    r = dict(_p("NBA", "Tre Jones Pts+Reb+Ast Under 22.5", 0.6), player="Tre Jones", market="PRA")
    assert TV.pick_text(r) == "Pts+Reb+Ast Under 22.5"
    extra = dict(_p("NBA", "Aaron X Points Over 9.5", 0.55), player="Aaron X", market="Points")
    assert [player_of["player"] for player_of in TV.search_options([r, extra, r])] == ["Aaron X", "Tre Jones"]


def test_the_full_playable_list_is_saved_for_search(monkeypatch):
    import model_store as MS
    import todays_best as TB
    saved = {}
    monkeypatch.setattr(MS, "save_setting", lambda k, v: saved.__setitem__(k, v))
    monkeypatch.setattr(MS, "get_setting", lambda k, d=None: saved.get(k, d))
    monkeypatch.setattr(TB, "props_rows", lambda sp, plays, cap=True: [{"player": f"P{i}", "values": list(range(20)),
                                                                        "mins": list(range(20))}
                                                                       for i in range(3 if cap else 12)])
    TB.save_props("NBA", "2026-11-25", [{"Game": "A @ B"}])
    allrows = TB.load_all_props("NBA", "2026-11-25")
    assert len(allrows) == 12 and len(allrows[0]["values"]) == 10 and len(allrows[0]["mins"]) == 10
    assert TB.load_all_props("NHL", "2026-11-25") == []


def _soccer_row():
    return {"sport": "SOCCER", "league": "Premier League", "time": "3:00 PM", "game": "Chelsea vs Arsenal",
            "winner": "Arsenal", "chance": 0.52, "price": -120, "best": "Arsenal 52% (2-1)",
            "lean_detail": "market: Arsenal 55%", "_probs": {"home": 0.52, "draw": 0.26, "away": 0.22},
            "_market": {"home": 0.55, "draw": 0.25, "away": 0.20}, "_prices": {"home": -120, "draw": 260, "away": 380},
            "_xg": {"home": 1.8, "away": 0.9}, "_sharp": True,
            "_rec": {"home": "Arsenal", "away": "Chelsea", "kickoff": "2099-01-01T20:00:00Z"}}


def test_soccer_game_card_shows_three_results_model_vs_market():
    g = GC.build_soccer(_soccer_row(), [{"game": "Chelsea vs Arsenal", "pick": "Draw", "price": 260},
                                        {"game": "Other vs Game", "pick": "X"}])
    assert [x["name"] for x in g["results"]] == ["Arsenal", "Draw", "Chelsea"] and len(g["flags"]) == 1
    html = GC.soccer_html(g)
    assert "model 52%" in html and "market 55%" in html and "EXPECTED GOALS" in html and "Tracking" in html


def test_soccer_and_unknown_games_open_a_card_not_a_dead_end():
    from streamlit.testing.v1 import AppTest

    def app():
        import today_visual as TV
        from test_today_visual import _soccer_row
        import streamlit as st
        if st.session_state.get("which") == "basic":
            TV._basic_dialog({"sport": "TENNIS", "pick": "Sinner ML", "chance": 0.7, "price": "-250",
                              "game": "Sinner vs Alcaraz", "time": "9:00 AM", "bet": "Info only"})
        else:
            TV._game_dialog(_soccer_row(), [])
    at = AppTest.from_function(app, default_timeout=60).run()
    assert not at.exception and any("Model's most likely result" in m.value for m in at.markdown)
    at.session_state["which"] = "basic"
    at.run()
    assert not at.exception and any("Sinner ML" in m.value for m in at.markdown)
    assert "That game's card isn't on the saved board yet" not in open("today_visual.py").read()


def test_soccer_strip_uses_the_soccer_games():
    rows = TV.soccer_games("2026-11-25", loader=lambda d: [_soccer_row()])
    assert rows[0]["game"] == "Chelsea vs Arsenal"
    html = TV.game_tile_html(rows[0])
    assert "Market: Arsenal 55%" in html and "Arsenal 52% (2-1)" in html
