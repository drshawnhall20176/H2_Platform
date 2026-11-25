"""Nov 25: the game card and the clickable Today cards -- commercial preview only."""
import game_card as GC
import today_visual as TV
from test_customer_pages import RECS, _p


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
