"""Nov 25 (owner): one site-wide 'My sportsbook' and 'My pick'em app'."""
from streamlit.testing.v1 import AppTest


def test_the_book_and_app_default_and_follow_the_page_address():
    def app():
        import streamlit as st
        import my_books as MB
        st.write(f"book={MB.book()} app={MB.app()}")
        MB.sidebar()
    at = AppTest.from_function(app, default_timeout=60).run()
    assert not at.exception and "book=draftkings" in at.markdown[0].value
    at.sidebar.selectbox(key="_sb_my_book").set_value("fanduel").run()
    assert not at.exception and at.session_state["my_book"] == "fanduel"
    at.run()
    assert "book=fanduel" in at.markdown[0].value


def test_pick_pages_price_at_my_book_with_no_second_dropdown(monkeypatch):
    import best_bets_data as BBD
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "k")

    def app():
        import streamlit as st
        import best_bets_data as B
        B.get_odds_api_key = lambda: "k"
        st.write("picked=" + B.render_book_selector("best_bets", available_books=["draftkings", "fanduel", "betmgm"]))
    at = AppTest.from_function(app, default_timeout=60)
    at.session_state["my_book"] = "betmgm"
    at.run()
    assert not at.exception and "picked=betmgm" in at.markdown[0].value and not at.warning
    assert not at.selectbox                                    # Nov 25: no second sportsbook dropdown on the page
    assert at.session_state["best_bets_book_selector"] == "BetMGM"     # the Bet Log still reads the label
    at.session_state["my_book"] = "caesars_not_on_slate"
    at.run()
    assert "picked=draftkings" in at.markdown[0].value          # your book isn't on the slate: DraftKings


def test_pickem_board_is_in_the_commercial_layout():
    import nav_layout as NL
    assert NL.commercial_section("Pick'em Board") == NL.TODAY and NL.label("Pick'em Board") == "Pick'em"



def test_a_pick_page_can_switch_between_my_book_and_my_pickem_app(monkeypatch):
    def app():
        import streamlit as st
        import best_bets_data as B
        B.get_odds_api_key = lambda: "k"
        st.write("picked=" + B.render_book_selector("best_bets", available_books=["draftkings", "fanduel", "pick6"]))
    at = AppTest.from_function(app, default_timeout=60)
    at.session_state["my_book"] = "fanduel"
    at.session_state["my_pickem"] = "pick6"
    at.run()
    assert not at.exception and "picked=fanduel" in at.markdown[0].value
    at.button_group(key="best_bets_book_selector_mode").set_value("pick6").run()
    assert not at.exception and "picked=pick6" in at.markdown[0].value
