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
    assert [t.label for t in at.tabs] == ["🎙️ The Desk", "💎 Hidden gems", "🧭 Every angle", "🧾 Proof"]
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
