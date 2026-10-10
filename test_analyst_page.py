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


@pytest.fixture
def desk(monkeypatch, tmp_path):
    import streamlit as st
    st.cache_data.clear()
    plays, meta = _board()
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, meta, ["draftkings"]))
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: [])
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
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["sport"] = "NFL"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    radio = [r for r in at.radio if r.label == "Games shown"][0]
    assert radio.value == "Selected date"
    assert list(at.dataframe[0].value["Player"]) == ["Today Guy"]
    radio.set_value("This week").run()
    assert sorted(at.dataframe[0].value["Player"]) == ["Later Guy", "Today Guy"]
