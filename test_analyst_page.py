"""The Analyst Desk page, end to end on a patched board."""
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytz
from streamlit.testing.v1 import AppTest

import analyst as A
import analyst_ledger as AL
import best_bets_data as BBD
import line_history
import sports

PAGE = str(Path(__file__).parent / "views" / "39_Analyst_Desk.py")
ET = pytz.timezone("US/Eastern")


def _tomorrow_iso():
    d = (datetime.now(ET) + timedelta(days=1)).replace(hour=19, minute=30, second=0, microsecond=0, tzinfo=None)
    return ET.localize(d).astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _board(extra=True):
    when = _tomorrow_iso()
    plays = [{"Player": f"F{i}", "PlayerId": 100 + i, "Team": "BOS", "Game": "BOS @ NYK", "GameDate": when, "Market": "Points",
              "Side": "Over", "Line": 20.5, "ModelProb": 0.6, "Conviction": 1.4 + i * 0.01, "ConvictionSource": "model_typical",
              "TeamTrend": "steady", "Why": "w"} for i in range(12)]
    if extra:
        plays.append({"Player": "Gem Guy", "PlayerId": 7, "Team": "NYK", "Game": "BOS @ NYK", "GameDate": when, "Market": "Points",
                      "Side": "Over", "Line": 20.5, "ModelProb": 0.66, "Conviction": 1.3, "ConvictionSource": "book", "TeamTrend": "📈 Hot",
                      "TeamTrendRatio": 1.3, "RealPrice": -115, "RealPriceBook": "draftkings", "Why": "scoring more lately"})
    meta = [{"label": "BOS @ NYK", "game_date": when, "away_name": "BOS", "home_name": "NYK"}]
    return plays, meta


def _offers(plays, sport="NBA", books=("draftkings", "fanduel"), skip=(), point=None, prices=None):
    """Book offers posting every play at its own line at each of `books` (minus any player in `skip`)."""
    mmap = sports.get(sport).market_map
    out = []
    for p in plays:
        if p["Player"] in skip:
            continue
        prices_p = prices or {b: -115 + 5 * i for i, b in enumerate(books)}
        out.append({"market": mmap[p["Market"]], "player": p["Player"], "point": point if point is not None else p["Line"],
                    "over": dict(prices_p), "under": {b: +100 for b in books}})
    return out


@pytest.fixture
def desk(monkeypatch, tmp_path):
    import streamlit as st
    st.cache_data.clear()
    plays, meta = _board()
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, meta, ["draftkings"]))
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: _offers(plays))
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "KEY")
    monkeypatch.setattr(line_history, "line_series", lambda *a, **k: [])
    monkeypatch.setattr(AL, "DB_PATH", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(sports.get("NBA").engine, "get_player_results", lambda d: {}, raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def run():
        at = AppTest.from_file(PAGE, default_timeout=60)
        at.session_state["sport"] = "NBA"
        at.run()
        return at
    run.db = str(tmp_path / "ledger.db")
    return run


def texts(at):
    return [m.value for m in at.markdown] + [c.value for c in at.caption] + [s.value for s in at.subheader] + [i.value for i in at.info] + [w.value for w in at.warning]


def test_the_desk_reads_the_slate_names_the_gem_and_locks_the_call(desk):
    at = desk()
    assert not at.exception, [e.value for e in at.exception]
    assert [t.label for t in at.tabs] == ["🎙️ The Desk", "💎 Hidden gems", "🧭 Every angle", "📡 Locked calls & share", "🧾 Proof"]
    joined = " ".join(texts(at))
    assert "NBA" in at.subheader[0].value or "NBA" in joined
    assert "hidden-gem candidate" in joined and "Gem Guy" in joined and "model 66% vs market 51%" in joined
    assert "1 new call(s) locked to the record" in joined
    gems = at.dataframe[0].value
    assert list(gems["Player"]) == ["Gem Guy"] and gems["Gem"].iloc[0] == "💎"
    (row,) = AL.fetch_calls(db_path=desk.db)
    assert row["player"] == "Gem Guy" and row["gem"] and row["angles"] == ["market_gap", "team_surge"]


def test_reopening_the_page_does_not_lock_the_same_call_twice(desk):
    desk()
    at = desk()
    assert len(AL.fetch_calls(db_path=desk.db)) == 1
    assert "locked to the record" not in " ".join(texts(at))


def test_earlier_days_are_graded_on_the_next_visit_and_the_proof_tab_shows_it(desk, monkeypatch):
    old = {"key": "k", "sport": "NBA", "date": "2026-09-30", "player": "Old Timer", "player_id": 55, "team": "BOS", "game": "BOS @ NYK",
           "game_date": "2026-09-30", "market": "Points", "side": "Over", "line": 20.5, "model_prob": 0.62, "conviction": 1.3,
           "price": None, "price_book": None, "why": "", "score": 1.0, "gem": True, "chalk": False, "cautions": [],
           "angles": [{"angle": "market_gap"}, {"angle": "team_surge"}]}
    AL.record_calls([old], "2026-09-30", None, desk.db)
    monkeypatch.setattr(sports.get("NBA").engine, "get_player_results", lambda d: {55: {"pts": 31}}, raising=False)
    at = desk()
    assert not at.exception, [e.value for e in at.exception]
    assert "Graded 1 call(s) from 2026-09-30" in " ".join(texts(at))
    board = [d.value for d in at.dataframe if "Angle" in d.value.columns][0]
    assert board.loc[board["Angle"] == "All published calls", "Graded"].iloc[0] == 1
    assert board.loc[board["Angle"] == "Hidden gems (2+ angles, not chalk)", "Hit rate"].iloc[0] == 1.0
    assert "Collecting data (1/30)" in set(board["Status"])


def test_with_no_record_yet_the_proof_tab_says_so_honestly(desk):
    at = desk()
    assert any("No calls have been graded yet" in i.value for i in at.info)


def test_a_slate_with_nothing_to_say_says_so(desk, monkeypatch):
    plays, meta = _board(extra=False)
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, meta, ["draftkings"]))
    at = desk()
    assert not at.exception, [e.value for e in at.exception]
    assert "no play had a single angle" in " ".join(texts(at))
    assert any("No play has cleared the hidden-gem bar" in i.value for i in at.info)
    assert AL.fetch_calls(db_path=desk.db) == []


def test_missing_odds_are_said_out_loud(desk, monkeypatch):
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: None)
    assert "no Odds API key is configured" in " ".join(texts(desk()))
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "KEY")

    def boom(*a, **k):
        raise RuntimeError("quota")
    monkeypatch.setattr(BBD, "fetch_generic_offers", boom)
    assert "the odds fetch failed (quota)" in " ".join(texts(desk()))


def test_a_ledger_that_cannot_be_written_is_flagged_not_hidden(desk, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(AL, "record_calls", boom)
    at = desk()
    assert not at.exception
    assert "not being tracked" in " ".join(texts(at))


def test_ai_commentary_is_offered_only_with_a_key_and_failures_are_explained(desk, monkeypatch):
    assert not desk().toggle                                                              # no key, no toggle
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    at = desk()
    assert [t.label for t in at.toggle] == ["Write it up in the analyst's voice (AI)"]

    def fail(facts, key, model=None, **k):
        raise RuntimeError("the Anthropic API answered 401: invalid x-api-key")
    monkeypatch.setattr(A, "llm_commentary", fail)
    at.toggle[0].set_value(True).run()
    assert any("AI write-up isn't available — the Anthropic API answered 401" in w.value for w in at.warning)
    assert at.subheader                                                                    # standard commentary still shown

    seen = {}
    monkeypatch.setattr(A, "llm_commentary", lambda facts, key, model=None, **k: seen.update(f=facts, m=model) or "Good evening, folks.")
    monkeypatch.setenv("ANALYST_MODEL", "model-x")
    at2 = desk()
    at2.toggle[0].set_value(True).run()
    assert "Good evening, folks." in " ".join(texts(at2)) and seen["m"] == "model-x"
    assert seen["f"]["calls"][0]["play"].startswith("Gem Guy Over 20.5 Points")


def test_football_shows_the_picked_dates_games_and_the_week_on_request(desk, monkeypatch):
    when_today = ET.localize((datetime.now(ET)).replace(hour=23, minute=30, second=0, microsecond=0, tzinfo=None)).astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    when_later = ET.localize((datetime.now(ET) + timedelta(days=2)).replace(hour=20, minute=15, second=0, microsecond=0, tzinfo=None)).astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def play(name, pid, game, when):
        return {"Player": name, "PlayerId": pid, "Team": "T", "Game": game, "GameDate": when, "Market": "Pass Yards", "Side": "Over", "Line": 250.5,
                "ModelProb": 0.66, "Conviction": 1.3, "ConvictionSource": "book", "TeamTrend": "\U0001F4C8 Hot", "TeamTrendRatio": 1.3, "Why": "w"}
    plays = [play("Today Guy", 1, "AAA @ BBB", when_today), play("Later Guy", 2, "CCC @ DDD", when_later)]
    meta = [{"label": "AAA @ BBB", "game_date": when_today}, {"label": "CCC @ DDD", "game_date": when_later}]
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, meta, ["draftkings"]))
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: _offers(plays, "NFL"))
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["sport"] = "NFL"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    radio = [r for r in at.radio if r.label == "Games shown"][0]
    assert radio.value == "Selected date"
    assert list(at.dataframe[0].value["Player"]) == ["Today Guy"]
    radio.set_value("This week").run()
    assert sorted(at.dataframe[0].value["Player"]) == ["Later Guy", "Today Guy"]


# ------------------------------------------------------------------ games grouped by slot and start time
def _today_iso(hour, minute=0):
    d = datetime.now(ET).replace(hour=hour, minute=minute, second=0, microsecond=0, tzinfo=None)
    return ET.localize(d).astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _three_game_board():
    games = [("LAT @ NYK", _today_iso(21, 0)), ("AFT @ BOS", _today_iso(13, 0)), ("EVE @ CHI", _today_iso(19, 30)), ("QUI @ DEN", _today_iso(14, 0))]
    plays = []
    for i, (g, when) in enumerate(games[:3]):                   # QUI @ DEN has no play with an angle (and no plays at all)
        plays.append({"Player": f"Gem{i}", "PlayerId": 10 + i, "Team": "T", "Game": g, "GameDate": when, "Market": "Points", "Side": "Over",
                      "Line": 20.5, "ModelProb": 0.66, "Conviction": 1.3, "ConvictionSource": "book", "TeamTrend": "📈 Hot",
                      "TeamTrendRatio": 1.3, "Why": "w"})
    meta = [{"label": g, "game_date": when, "away_name": g.split(" @ ")[0], "home_name": g.split(" @ ")[1]} for g, when in games]
    return plays, meta


def _run_slots(monkeypatch, sport):
    import streamlit as st
    st.cache_data.clear()
    plays, meta = _three_game_board()
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, meta, ["draftkings"]))
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: _offers(plays, sport))
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "KEY")
    monkeypatch.setattr(line_history, "line_series", lambda *a, **k: [])
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["sport"] = sport
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


@pytest.fixture
def isolated_ledger(monkeypatch, tmp_path):
    monkeypatch.setattr(AL, "DB_PATH", str(tmp_path / "ledger.db"))


@pytest.mark.parametrize("sport", ["NBA", "NCAAMB"])
def test_games_are_grouped_under_slot_headers_in_start_order_for_basketball(monkeypatch, isolated_ledger, sport):
    at = _run_slots(monkeypatch, sport)
    heads = [m.value for m in at.markdown if m.value.startswith("##### ")]
    assert heads == ["##### Afternoon games (before 5 PM ET)", "##### Evening games (5–8 PM ET)", "##### Late games (8 PM ET and after)"]
    labels = [e.label for e in at.expander if " · " not in e.label and " @ " in e.label]
    assert labels == ["1:00 PM ET — AFT @ BOS", "2:00 PM ET — QUI @ DEN", "7:30 PM ET — EVE @ CHI", "9:00 PM ET — LAT @ NYK"]
    quiet = [e for e in at.expander if e.label.endswith("QUI @ DEN")][0]
    assert "No play clears an angle here." in " ".join(m.value for m in quiet.markdown)


def test_time_slot_and_game_filters_narrow_the_whole_page(monkeypatch, isolated_ledger):
    at = _run_slots(monkeypatch, "NBA")
    slot = [s for s in at.selectbox if s.label == "Time slot"][0]
    assert slot.options == ["All slate", "Afternoon", "Evening", "Late"]
    slot.set_value("Late").run()
    assert not at.exception
    assert list(at.dataframe[0].value["Player"]) == ["Gem0"]
    assert list(at.dataframe[0].value["Slot"]) == ["Late"] and list(at.dataframe[0].value["Time"]) == ["9:00 PM ET"]
    game = [s for s in at.selectbox if s.label == "Game"][0]
    assert game.options == ["All games in this slot", "9:00 PM ET — LAT @ NYK"]
    heads = [m.value for m in at.markdown if m.value.startswith("##### ")]
    assert heads == ["##### Late games (8 PM ET and after)"]
    # the record is the whole slate no matter what is being looked at
    assert {r["game"] for r in AL.fetch_calls(db_path=AL.DB_PATH)} <= {"LAT @ NYK", "AFT @ BOS", "EVE @ CHI"}


def test_one_game_can_be_picked_and_the_table_order_follows_the_choice(monkeypatch, isolated_ledger):
    at = _run_slots(monkeypatch, "NBA")
    assert list(at.dataframe[0].value["Time"]) == ["1:00 PM ET", "7:30 PM ET", "9:00 PM ET"]          # start time is the default order
    [r for r in at.radio if r.label == "Order by"][0].set_value("Strongest first").run()
    assert sorted(at.dataframe[0].value["Time"]) == ["1:00 PM ET", "7:30 PM ET", "9:00 PM ET"]
    game = [s for s in at.selectbox if s.label == "Game"][0]
    game.set_value("7:30 PM ET — EVE @ CHI").run()
    assert list(at.dataframe[0].value["Game"]) == ["EVE @ CHI"]


def test_a_game_missing_from_the_slate_meta_still_gets_its_time_from_its_plays(monkeypatch, isolated_ledger):
    import streamlit as st
    st.cache_data.clear()
    plays, _meta = _three_game_board()
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, [], ["draftkings"]))
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: [])
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "KEY")
    monkeypatch.setattr(line_history, "line_series", lambda *a, **k: [])
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["sport"] = "NBA"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert [s for s in at.selectbox if s.label == "Time slot"][0].options == ["All slate", "Afternoon", "Evening", "Late"]
    assert [m.value for m in at.markdown if m.value.startswith("##### ")] == [
        "##### Afternoon games (before 5 PM ET)", "##### Evening games (5–8 PM ET)", "##### Late games (8 PM ET and after)"]


# ------------------------------------------------------------------ sportsbook: suggestions follow the selected book's real lines
def _desk_with(monkeypatch, tmp_path, offers, plays_meta=None):
    import streamlit as st
    st.cache_data.clear()
    plays, meta = plays_meta or _board()
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, meta, ["draftkings", "fanduel"]))
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: offers)
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "KEY")
    monkeypatch.setattr(line_history, "line_series", lambda *a, **k: [])
    monkeypatch.setattr(AL, "DB_PATH", str(tmp_path / "ledger.db"))
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["sport"] = "NBA"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_the_page_has_a_sportsbook_selector_listing_the_books_that_posted_lines(monkeypatch, tmp_path):
    plays, meta = _board()
    at = _desk_with(monkeypatch, tmp_path, _offers(plays))
    book = [s for s in at.selectbox if s.label == "📖 Sportsbook"][0]
    assert set(book.options) == {"DraftKings", "FanDuel"} and book.value == "DraftKings"


def test_a_play_the_selected_book_does_not_post_is_not_suggested_or_locked(monkeypatch, tmp_path):
    plays, meta = _board()
    at = _desk_with(monkeypatch, tmp_path, _offers(plays, books=("fanduel",)) + _offers([p for p in plays if p["Player"] != "Gem Guy"], books=("draftkings",)))
    joined = " ".join(texts(at))
    assert "Gem Guy" not in str(at.dataframe[0].value) and any("No play has cleared the hidden-gem bar" in i.value for i in at.info)
    assert "nothing I can take at DraftKings" in joined and "1 isn't posted at DraftKings at all" in joined
    assert "a quiet read" not in joined                                          # withheld by the book is not "quiet"
    assert AL.fetch_calls(db_path=str(tmp_path / "ledger.db")) == []                            # nothing unbettable is locked
    default_table = [d.value for d in at.dataframe if "At book" in d.value.columns]
    assert not default_table or "Gem Guy" not in set(default_table[0]["Player"])            # unticked: only what DraftKings posts
    # still reachable, clearly labelled, on request
    [c for c in at.checkbox if c.key == "analyst_show_off"][0].set_value(True).run()
    table = [d.value for d in at.dataframe if "At book" in d.value.columns][0]
    row = table[table["Player"] == "Gem Guy"].iloc[0]
    assert row["At book"] == "Not posted at DraftKings (at FanDuel)" and row["Book price"] is None            # no price at DK


def test_a_book_that_only_posts_a_different_line_is_called_out_not_suggested(monkeypatch, tmp_path):
    plays, meta = _board()
    only_other = [o for o in _offers(plays, books=("draftkings",)) if o["player"] != "Gem Guy"] + \
                 _offers([p for p in plays if p["Player"] == "Gem Guy"], books=("draftkings",), point=21.5)
    at = _desk_with(monkeypatch, tmp_path, only_other)
    assert "Gem Guy" not in str(at.dataframe[0].value)
    [c for c in at.checkbox if c.key == "analyst_show_off"][0].set_value(True).run()
    table = [d.value for d in at.dataframe if "At book" in d.value.columns][0]
    assert table[table["Player"] == "Gem Guy"].iloc[0]["At book"] == "DraftKings posts 21.5 instead"


def test_the_price_shown_is_the_selected_books_not_the_best_price(monkeypatch, tmp_path):
    plays, meta = _board()
    offers = _offers(plays, prices={"draftkings": -130, "fanduel": +105})
    at = _desk_with(monkeypatch, tmp_path, offers)
    assert at.dataframe[0].value["Book price"].iloc[0] == -130
    assert AL.fetch_calls(db_path=str(tmp_path / "ledger.db"))[0]["price"] == -130
    book = [s for s in at.selectbox if s.label == "📖 Sportsbook"][0]
    book.set_value("FanDuel").run()
    assert not at.exception
    assert at.dataframe[0].value["Book price"].iloc[0] == 105


def test_with_no_props_posted_the_desk_makes_no_line_specific_suggestion(monkeypatch, tmp_path):
    at = _desk_with(monkeypatch, tmp_path, [])
    joined = " ".join(texts(at))
    assert "DraftKings has no player props posted for this slate yet" in joined
    assert any("No play has cleared the hidden-gem bar" in i.value for i in at.info)
    assert AL.fetch_calls(db_path=str(tmp_path / "ledger.db")) == []
    [c for c in at.checkbox if c.key == "analyst_show_off"][0].set_value(True).run()
    table = [d.value for d in at.dataframe if "At book" in d.value.columns][0]
    assert set(table["At book"]) == {"No props posted yet"} and len(table) >= 1


def _with_event(offers, eid="ev1", home="New York Knicks", away="Boston Celtics"):
    return [dict(o, event_id=eid, home_team=home, away_team=away) for o in offers]


def test_when_the_selected_book_has_nothing_up_for_the_game_the_page_says_so_and_who_does(monkeypatch, tmp_path):
    plays, meta = _board()
    fd_only = _with_event(_offers(plays, books=("fanduel",)))
    other_game = _with_event(_offers(plays[:2], books=("draftkings",)), eid="ev2", home="Miami Heat", away="Chicago Bulls")
    other_game = [dict(o, player=f"Elsewhere {i}") for i, o in enumerate(other_game)]     # DK's props are for a different game
    at = _desk_with(monkeypatch, tmp_path, fd_only + other_game)
    joined = " ".join(texts(at))
    assert "nothing I can take at DraftKings" in joined and "a quiet read" not in joined
    assert "DraftKings has no player props posted for BOS @ NYK." in joined
    assert "FanDuel 13" in joined and "pick one of them" in joined                          # 12 + Gem Guy, all at FanDuel
    assert "No play clears an angle here" not in joined                                      # the game isn't empty — the book is
    assert "angles, but they aren't available at DraftKings at the model's line" in joined or \
           "angles, but it isn't available at DraftKings at the model's line" in joined
    assert AL.fetch_calls(db_path=str(tmp_path / "ledger.db")) == []


def test_a_suffix_in_the_books_spelling_does_not_make_a_posted_prop_look_missing(monkeypatch, tmp_path):
    plays, meta = _board()
    offs = _offers(plays)
    for o in offs:
        if o["player"] == "Gem Guy":
            o["player"] = "Gem Guy Jr."                                                      # the book's spelling
    at = _desk_with(monkeypatch, tmp_path, offs)
    assert "nothing I can take" not in " ".join(texts(at))


def test_each_game_says_when_the_selected_book_has_nothing_up_for_it(monkeypatch, isolated_ledger):
    import streamlit as st
    st.cache_data.clear()
    plays, meta = _three_game_board()
    by = {p["Game"]: p for p in plays}
    offs = (_with_event(_offers([by["LAT @ NYK"]], books=("draftkings", "fanduel")), "e1", "NYK", "LAT")
            + _with_event(_offers([by["AFT @ BOS"]], books=("fanduel",)), "e2", "BOS", "AFT"))
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, meta, ["draftkings", "fanduel"]))
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: offs)
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "KEY")
    monkeypatch.setattr(line_history, "line_series", lambda *a, **k: [])
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["sport"] = "NBA"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    joined = " ".join(texts(at))
    assert "DraftKings has no player props posted for this game. Other books do (FanDuel 1)" in joined   # AFT @ BOS
    assert joined.count("DraftKings has no player props posted for this game") == 1                  # LAT @ NYK has DK props
    assert "nothing I can take" not in joined                                                          # one game does have a play


# ------------------------------------------------- Build 232: locked calls, closing line, Discord, Ask the Analyst
def _live(desk, monkeypatch):
    """The desk fixture, but with a mutable offers list so a later run can see the market move."""
    plays, _meta = _board()
    offers = _offers(plays)
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: offers)
    return offers


def _df_with(at, col):
    found = [d.value for d in at.dataframe if col in d.value.columns]
    return found[0] if found else None


def test_the_locked_calls_tab_shows_each_locked_call_against_the_books_current_price(desk, monkeypatch):
    offers = _live(desk, monkeypatch)
    at = desk()
    assert any("1 locked at DraftKings; 0 moved" in t for t in texts(at))
    t = _df_with(at, "Now")
    assert list(t["Player"]) == ["Gem Guy"] and t.iloc[0]["Now"] == "Unchanged" and t.iloc[0]["Locked price"] == -115
    for o in offers:                                           # the market moves: Gem Guy's over gets shorter
        if o["player"] == "Gem Guy":
            o["over"]["draftkings"] = -140
    at = desk()
    assert any("1 locked at DraftKings; 1 moved" in t for t in texts(at))
    assert _df_with(at, "Now").iloc[0]["Now"] == "Price -115 → -140 (toward the call)"
    offers[:] = [o for o in offers if o["player"] != "Gem Guy"]                                   # then he is pulled
    at = desk()
    assert _df_with(at, "Now").iloc[0]["Now"] == "Pulled — no longer posted"


def test_the_closing_line_check_fills_in_as_the_market_moves_after_the_lock(desk, monkeypatch):
    offers = _live(desk, monkeypatch)
    at = desk()
    assert _df_with(at, "Moved toward") is None or int(_df_with(at, "Moved toward").iloc[0]["Moved toward"]) == 0
    for o in offers:
        if o["player"] == "Gem Guy":
            o["over"]["draftkings"] = -140
    at = desk()
    clv = _df_with(at, "Moved toward")
    row = clv[clv["Angle"] == "All published calls"].iloc[0]
    assert row["Tracked"] == 1 and row["Moved toward"] == 1 and row["Moved away"] == 0
    (locked,) = AL.fetch_calls(db_path=desk.db)
    assert locked["price"] == -115 and locked["last_price"] == -140 and locked["line"] == 20.5          # the lock never moves


def test_the_closing_line_section_explains_itself_before_there_is_anything_to_show(monkeypatch, tmp_path):
    plays, meta = _board()
    at = _desk_with(monkeypatch, tmp_path, _offers(plays, books=("fanduel",)))                    # nothing can lock at DraftKings
    assert any("closing-line check" in m.value for m in at.markdown)
    assert _df_with(at, "Moved toward") is None and any("Once calls have been locked" in c.value for c in at.caption)


def test_the_locked_table_lists_only_todays_open_calls(desk, monkeypatch):
    _live(desk, monkeypatch)
    at = desk()
    base = ("INSERT INTO analyst_calls (logged_at, call_date, sport, player, market, side, line, price, price_book, angles, settled_at) "
            "VALUES ('t', '{d}', 'NBA', '{p}', 'Points', 'Over', 20.5, -110, 'draftkings', '[]', {s})")
    tomorrow = (datetime.now(ET) + timedelta(days=1)).strftime("%Y-%m-%d")
    today = datetime.now(ET).strftime("%Y-%m-%d")
    AL._run(desk.db, base.format(d=tomorrow, p="Tomorrow Guy", s="NULL"))
    AL._run(desk.db, base.format(d=today, p="Graded Guy", s="'t'"))
    at = desk()
    assert list(_df_with(at, "Now")["Player"]) == ["Gem Guy"]


def test_discord_posting_needs_a_webhook_and_posts_the_edited_text_once_asked(desk, monkeypatch):
    import analyst_tools as AT
    _live(desk, monkeypatch)
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    at = desk()
    btn = [b for b in at.button if b.key == "analyst_post_picks"][0]
    assert btn.disabled and any("add DISCORD_WEBHOOK_URL" in c.value for c in at.caption)
    box = [t for t in at.text_area if t.label.startswith("Today's picks")][0]
    assert "Gem Guy Over 20.5 Points" in box.value and box.value.endswith(AT.DISCLAIMER)

    sent = []
    monkeypatch.setattr(AT, "post_to_discord", lambda url, text, **k: sent.append((url, text)))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")
    at = desk()
    assert sent == []                                                      # nothing is posted just by viewing the page
    [t for t in at.text_area if t.label.startswith("Today's picks")][0].set_value("my edited picks").run()
    [b for b in at.button if b.key == "analyst_post_picks"][0].click().run()
    assert sent == [("https://discord.com/api/webhooks/1/abc", "my edited picks")]
    assert any("Posted to Discord." in s.value for s in at.success)


def test_a_discord_failure_is_shown_not_swallowed(desk, monkeypatch):
    import analyst_tools as AT
    _live(desk, monkeypatch)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")

    def bad(url, text, **k):
        raise RuntimeError("Discord answered 404 — the webhook link may have been deleted")
    monkeypatch.setattr(AT, "post_to_discord", bad)
    at = desk()
    [b for b in at.button if b.key == "analyst_post_picks"][0].click().run()
    assert any("Not posted — Discord answered 404" in e.value for e in at.error)


def test_nothing_is_offered_to_post_when_the_book_has_no_suggestion(monkeypatch, tmp_path):
    plays, meta = _board()
    at = _desk_with(monkeypatch, tmp_path, _offers(plays, books=("fanduel",)))                     # DraftKings posts nothing
    assert not [t for t in at.text_area if t.label.startswith("Today's picks")]
    assert any("Nothing to post" in i.value for i in at.info)


def test_a_graded_recap_can_be_previewed_and_posted(desk, monkeypatch):
    import analyst_tools as AT
    _live(desk, monkeypatch)
    at = desk()
    assert any("A graded recap appears here" in c.value for c in at.caption)                     # nothing graded yet
    AL._run(desk.db, "INSERT INTO analyst_calls (logged_at, call_date, sport, player, market, side, line, model_prob, hit, actual, settled_at, "
                     "angles, price_book) VALUES ('t','2026-01-02','NBA','Old Gem','Points','Over',20.5,0.6,1,25,'t','[]','draftkings')")
    sent = []
    monkeypatch.setattr(AT, "post_to_discord", lambda url, text, **k: sent.append(text))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")
    at = desk()
    box = [t for t in at.text_area if t.label.startswith("Graded recap")][0]
    assert "recap — NBA, 2026-01-02" in box.value and "✅ Old Gem Over 20.5 Points (actual 25)" in box.value
    [b for b in at.button if b.key == "analyst_post_recap"][0].click().run()
    assert len(sent) == 1 and "Old Gem" in sent[0]


def test_ask_the_analyst_answers_from_the_days_facts_and_explains_failures(desk, monkeypatch):
    _live(desk, monkeypatch)
    plays, meta = _board()
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, meta, ["draftkings", "fanduel"]))
    at = desk()
    assert not at.text_input and any("once ANTHROPIC_API_KEY is added" in c.value for c in at.caption)      # no key, no box
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    seen = {}

    def fake(payload, key, model=None, **k):
        seen.update(p=payload, k=k)
        return "The gem is Gem Guy."
    monkeypatch.setattr(A, "llm_commentary", fake)
    at = desk()
    [t for t in at.text_input if t.label == "Ask about this slate"][0].set_value("Who is the gem?")
    [b for b in at.button if b.label == "Ask"][0].click().run()
    assert "**You:** Who is the gem?" in " ".join(texts(at)) and "The gem is Gem Guy." in " ".join(texts(at))
    assert seen["p"]["question"] == "Who is the gem?" and seen["p"]["facts"]["sportsbook"] == "DraftKings"
    assert seen["p"]["facts"]["plays"][0]["play"].startswith("Gem Guy Over 20.5 Points")
    assert seen["k"]["system"].startswith("You are the on-air analyst for H2 Sports answering a question")

    def fail(payload, key, model=None, **k):
        raise RuntimeError("the Anthropic API answered 429")
    monkeypatch.setattr(A, "llm_commentary", fail)
    [t for t in at.text_input if t.label == "Ask about this slate"][0].set_value("And now?")
    [b for b in at.button if b.label == "Ask"][0].click().run()
    assert any("The analyst couldn't answer — the Anthropic API answered 429" in w.value for w in at.warning)
    assert "The gem is Gem Guy." in " ".join(texts(at))                                              # earlier answer is kept
    monkeypatch.setattr(A, "llm_commentary", lambda payload, key, model=None, **k: "Second answer.")
    [t for t in at.text_input if t.label == "Ask about this slate"][0].set_value("One more?")
    [b for b in at.button if b.label == "Ask"][0].click().run()
    shown = [m.value for m in at.markdown if m.value in ("Second answer.", "The gem is Gem Guy.")]
    assert shown == ["Second answer.", "The gem is Gem Guy."]                                        # newest first
    [s for s in at.selectbox if s.label == "📖 Sportsbook"][0].set_value("FanDuel").run()
    assert "Second answer." not in " ".join(texts(at))                                               # a different book is a different conversation
