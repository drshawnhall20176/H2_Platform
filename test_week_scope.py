"""Games shown: Selected date / This week — the shared control and the pages that carry it."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import best_bets_data as BBD
import components as C
import sports

THU, SAT_EARLY, SAT_NIGHT, MON = "2026-10-09T00:15:00Z", "2026-10-10T16:00:00Z", "2026-10-11T02:00:00Z", "2026-10-13T00:15:00Z"
#                                  Thu 8:15 PM ET        Sat 12:00 PM ET        Sat 10:00 PM ET        Sun 8:15 PM ET
VIEWS = Path(__file__).parent / "views"


def _rows():
    return [{"GameLabel": "A @ B", "_game_date": THU, "Player": "p1"}, {"GameLabel": "C @ D", "_game_date": SAT_EARLY, "Player": "p2"},
            {"GameLabel": "E @ F", "_game_date": SAT_NIGHT, "Player": "p3"}, {"GameLabel": "G @ H", "_game_date": MON, "Player": "p4"}]


def _scope_script():
    import streamlit as st
    import components as C
    day = st.session_state["day"]
    sport = st.session_state["sport_key"]
    rows = st.session_state["rows"]
    kept = C.scope_rows(sport, sport, rows, day, key="t_scope")
    st.write("KEPT:" + ",".join(r["Player"] for r in kept))
    st.write("WEEK" if C.scope_is_week(sport) else "DAY")


def _run(sport="NFL", day="2026-10-10", pref=None, rows=None, choose=None):
    at = AppTest.from_function(_scope_script, default_timeout=30)
    at.session_state["day"], at.session_state["sport_key"], at.session_state["rows"] = day, sport, rows if rows is not None else _rows()
    if pref:
        at.session_state["_slate_scope_pref"] = pref
    at.run()
    if choose:
        [r for r in at.radio if r.label == "Games shown"][0].set_value(choose).run()
    return at


def kept(at):
    return [m.value for m in at.markdown if m.value.startswith("KEPT:")][0][5:].split(",")


def test_football_defaults_to_the_picked_dates_games_in_eastern_time():
    at = _run()
    assert not at.exception
    assert kept(at) == ["p2", "p3"]                        # Sat noon and Sat 10 PM ET (Sunday in UTC); Thursday and Monday are out
    radio = [r for r in at.radio if r.label == "Games shown"][0]
    assert radio.options == ["Selected date", "This week"] and radio.value == "Selected date"


def test_this_week_shows_every_game_and_the_choice_follows_the_user():
    at = _run(choose="This week")
    assert kept(at) == ["p1", "p2", "p3", "p4"] and "WEEK" in [m.value for m in at.markdown]
    assert at.session_state["_slate_scope_pref"] == "This week"
    again = _run(pref="This week")                          # another page, same session preference
    assert [r for r in again.radio if r.label == "Games shown"][0].value == "This week" and kept(again) == ["p1", "p2", "p3", "p4"]


def test_other_sports_have_no_switch_and_keep_everything():
    at = _run(sport="NBA")
    assert not at.radio and kept(at) == ["p1", "p2", "p3", "p4"] and "DAY" in [m.value for m in at.markdown]
    assert not _run(sport="MLB").radio


def test_a_date_with_no_games_says_so_and_offers_the_week():
    at = _run(day="2026-10-14")
    assert not at.exception and any("No NFL games kick off on 2026-10-14" in i.value and "This week" in i.value and "4 game(s)" in i.value
                                    for i in at.info)
    assert not any(m.value.startswith("KEPT:") for m in at.markdown)         # the page stopped
    week = _run(day="2026-10-14", choose="This week")
    assert kept(week) == ["p1", "p2", "p3", "p4"]


def test_unknown_game_dates_are_never_hidden():
    rows = _rows() + [{"GameLabel": "X @ Y", "_game_date": None, "Player": "p5"}]
    assert kept(_run(rows=rows)) == ["p2", "p3", "p5"]


def _meta_script():
    import streamlit as st
    import components as C
    meta = C.scope_meta("NCAAF", "NCAAF", st.session_state["meta"], st.session_state["day"], key="t_scope")
    st.write("META:" + ",".join(m["label"] for m in meta))
    plays, meta2 = C.scope_plays("NCAAF", "NCAAF", st.session_state["plays"], st.session_state["meta"], st.session_state["day"], key="t_scope2")
    st.write("PLAYS:" + ",".join(p["Player"] for p in plays) + "|" + ",".join(m["label"] for m in meta2))


def test_meta_and_play_pages_narrow_together():
    meta = [{"label": "A @ B", "game_date": THU}, {"label": "C @ D", "game_date": SAT_EARLY}]
    plays = [{"Game": "A @ B", "Player": "x"}, {"Game": "C @ D", "Player": "y"}, {"Game": "C @ D", "Player": "z"}]
    at = AppTest.from_function(_meta_script, default_timeout=30)
    at.session_state["meta"], at.session_state["plays"], at.session_state["day"] = meta, plays, "2026-10-10"
    at.run()
    assert not at.exception
    vals = [m.value for m in at.markdown]
    assert "META:C @ D" in vals and "PLAYS:y,z|C @ D" in vals
    # the two radios are separate widgets (different keys) but share the saved preference
    assert len([r for r in at.radio if r.label == "Games shown"]) == 2


def test_kickoff_labels_carry_the_weekday_only_in_the_week_list(monkeypatch):
    dt = sports.game_dt(SAT_EARLY)
    assert sports.kickoff_text(dt) == "12:00 PM ET" and sports.kickoff_text(dt, True) == "Sat 12:00 PM ET"

    def script():
        import streamlit as st
        import components as C
        import sports as S
        st.write("LABEL:" + C.kickoff_label(S.game_dt("2026-10-10T16:00:00Z"), "NFL"))
        st.write("MLB:" + C.kickoff_label(S.game_dt("2026-10-10T16:00:00Z"), "MLB"))
    at = AppTest.from_function(script, default_timeout=30)
    at.run()
    assert "LABEL:12:00 PM ET" in [m.value for m in at.markdown]
    at2 = AppTest.from_function(script, default_timeout=30)
    at2.session_state["_slate_scope_pref"] = "This week"
    at2.run()
    vals = [m.value for m in at2.markdown]
    assert "LABEL:Sat 12:00 PM ET" in vals and "MLB:12:00 PM ET" in vals          # only football lists span days


# ------------------------------------------------------------------ real pages
def _et_iso(days_from_today, hour, minute=0):
    from datetime import datetime, timedelta
    import pytz
    et = pytz.timezone("US/Eastern")
    day = (datetime.now(et) + timedelta(days=days_from_today)).replace(hour=hour, minute=minute, second=0, microsecond=0, tzinfo=None)
    return et.localize(day).astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _board():
    games = [("TB @ DAL", _et_iso(-2, 20, 15)), ("HOU @ IND", _et_iso(0, 13)), ("NE @ MIA", _et_iso(0, 20, 20)), ("SEA @ LAR", _et_iso(2, 20, 15))]
    plays = [{"Player": f"Pl{i}", "PlayerId": i, "Team": "T", "Game": g, "Opp": "X", "Market": "Pass Yards", "Side": "Over", "Line": 250.5,
              "ModelProb": 0.6, "Fair": -150, "Conviction": 1.5, "Why": "w", "GameDate": when, "_stat_key": "pass_yds", "TeamTrend": "steady",
              "_game_log": [{"pass_yds": v} for v in (260, 240, 280, 300, 220, 270)]} for i, (g, when) in enumerate(games)]
    meta = [{"label": g, "game_date": when, "away_name": g.split(" @ ")[0], "home_name": g.split(" @ ")[1]} for g, when in games]
    return plays, meta


@pytest.mark.parametrize("page", ["2_Graded_Picks.py", "3_Suggested_Parlays.py", "4_Speculative_Basket.py"])
def test_recommendation_pages_show_the_picked_date_then_the_week(monkeypatch, page):
    import streamlit as st
    st.cache_data.clear()
    plays, meta = _board()
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, meta, ["draftkings"]))
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: None)
    monkeypatch.setattr(sports, "has_started", lambda *a, **k: False)
    monkeypatch.setattr(st, "page_link", lambda *a, **k: None)
    import quick_log
    monkeypatch.setattr(quick_log, "render_quick_log", lambda *a, **k: None)
    at = AppTest.from_file(str(VIEWS / page), default_timeout=90)
    at.session_state["sport"] = "NFL"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    radio = [r for r in at.radio if r.label == "Games shown"][0]
    assert radio.options == ["Selected date", "This week"] and radio.value == "Selected date"
    games = [s for s in at.selectbox if s.label == "Game"][0]
    assert len(games.options) == 3 and not any("TB @ DAL" in o or "SEA @ LAR" in o for o in games.options)        # today's two games + "All games"
    assert not any(" — " in o and o.split(" — ")[0].split()[0] in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun") for o in games.options[1:])
    radio.set_value("This week").run()
    games = [s for s in at.selectbox if s.label == "Game"][0]
    assert len(games.options) == 5 and all(o.split(" — ")[0].split()[0] in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun") for o in games.options[1:])


def _patched_board(monkeypatch):
    import streamlit as st
    import quick_log
    st.cache_data.clear()
    plays, meta = _board()
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, meta, ["draftkings"]))
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: [])
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "KEY")
    monkeypatch.setattr(sports, "has_started", lambda *a, **k: False)
    monkeypatch.setattr(st, "page_link", lambda *a, **k: None)
    monkeypatch.setattr(quick_log, "render_quick_log", lambda *a, **k: None)


def test_slip_lab_shows_the_picked_dates_games_then_the_week_with_weekdays(monkeypatch):
    _patched_board(monkeypatch)
    at = AppTest.from_file(str(VIEWS / "37_Slip_Lab.py"), default_timeout=90)
    at.session_state["sport"] = "NFL"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    radio = [r for r in at.radio if r.label == "Games shown"][0]
    assert radio.value == "Selected date"
    game = [s for s in at.selectbox if s.label == "Game"][0]
    assert len(game.options) == 3                                                       # All + today's two games
    radio.set_value("This week").run()
    game = [s for s in at.selectbox if s.label == "Game"][0]
    labels = [game.format_func(o) if callable(getattr(game, "format_func", None)) else o for o in game.options]
    assert len(game.options) == 5 and any(l.startswith(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")) for l in labels[1:])


def test_best_bets_shows_the_picked_dates_games_then_the_week(monkeypatch):
    _patched_board(monkeypatch)
    monkeypatch.setattr(BBD, "render_book_selector", lambda *a, **k: "draftkings", raising=False)
    at = AppTest.from_file(str(VIEWS / "1_#U2b50_Best_Bets.py"), default_timeout=90)
    at.session_state["sport"] = "NFL"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    radio = [r for r in at.radio if r.label == "Games shown"][0]
    assert radio.value == "Selected date" and len([s for s in at.selectbox if s.label == "Game"][0].options) == 3
    radio.set_value("This week").run()
    assert len([s for s in at.selectbox if s.label == "Game"][0].options) == 5


def test_a_play_page_on_a_day_without_games_points_at_the_week(monkeypatch):
    import streamlit as st
    _patched_board(monkeypatch)
    plays, meta = _board()
    later = [m for m in meta if m["label"] in ("SEA @ LAR", "TB @ DAL")]                      # none of them is today
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: ([p for p in plays if p["Game"] in {m["label"] for m in later}], later, ["draftkings"]))
    at = AppTest.from_file(str(VIEWS / "2_Graded_Picks.py"), default_timeout=90)
    at.session_state["sport"] = "NFL"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("games kick off on" in i.value and "2 game(s)" in i.value and "This week" in i.value for i in at.info)
    [r for r in at.radio if r.label == "Games shown"][0].set_value("This week").run()
    assert len([s for s in at.selectbox if s.label == "Game"][0].options) == 3
