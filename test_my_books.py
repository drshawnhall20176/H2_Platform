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


def test_every_page_selector_starts_at_my_book_and_writes_back(monkeypatch):
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
    at.selectbox(key="best_bets_book_selector").set_value("FanDuel").run()
    assert not at.exception and at.session_state["my_book"] == "fanduel"


def test_pickem_board_is_in_the_commercial_layout():
    import nav_layout as NL
    assert NL.commercial_section("Pick'em Board") == NL.TODAY and NL.label("Pick'em Board") == "Pick'em"
