"""
test_media_room_page.py — renders views/21_Media_Room.py end to end with Streamlit's AppTest on a
synthetic NFL week (network-free): a Sunday slate + one Monday-night game. Covers the reported gap —
the page must focus on the date's game(s), not the whole week, and discuss sportsbook promotions.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import media_focus as MF
import nfl_engine
import nfl_projections

PAGE = str(Path(__file__).parent / "views" / "21_Media_Room.py")
MNF = "2026-10-06T00:15:00+00:00"
SUN = "2026-10-04T17:00:00+00:00"


def _p(name, team, game, gd, market, prob, conv, rec_yds=0, rec=0, rush_yds=0, car=0, pid="x"):
    log = [{"receiving_yards": rec_yds, "receptions": rec, "rushing_yards": rush_yds, "carries": car}] * 4
    return {"Player": name, "PlayerId": pid or name, "Team": team, "Game": game, "Opp": "OPP", "GameDate": gd,
            "Market": market, "Side": "Over", "Line": 0.5, "ModelProb": prob, "Fair": 140, "Conviction": conv,
            "Why": "recent form", "Position": "WR", "RealPrice": None, "PriceSource": "model_fair",
            "_game_log": log}


def _plays():
    mnf = "ATL @ NO"
    return [_p("Drake London", "ATL", mnf, MNF, "Anytime TD", .45, 1.5, rec_yds=70, rec=6),
            _p("Alvin Kamara", "NO", mnf, MNF, "Anytime TD", .52, 1.7, rush_yds=45, car=11, rec_yds=20, rec=4),
            _p("Bijan Robinson", "ATL", mnf, MNF, "Anytime TD", .50, 1.6, rush_yds=70, car=14),
            _p("Kirk Cousins", "ATL", mnf, MNF, "Pass Attempts", .6, 1.4),
            _p("Josh Allen", "BUF", "KC @ BUF", SUN, "Anytime TD", .40, 1.9, rush_yds=30, car=6),
            _p("Travis Kelce", "KC", "KC @ BUF", SUN, "Anytime TD", .48, 1.8, rec_yds=60, rec=6)]


def _meta():
    return [{"label": "KC @ BUF", "game_date": SUN}, {"label": "ATL @ NO", "game_date": MNF}]


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(nfl_engine, "build_slate", lambda d: ([], _meta()))
    monkeypatch.setattr(nfl_projections, "build_best_bets", lambda rows, *a, **k: _plays())
    monkeypatch.setattr(MF, "today_eastern", lambda: __import__("datetime").date(2026, 10, 5))


def _app():
    at = AppTest.from_file(PAGE, default_timeout=90)
    at.session_state["sport"] = "NFL"
    return at


def _text(at):
    return " ".join([m.value for m in at.markdown] + [c.value for c in at.caption] + [c.value for c in at.code])


def test_monday_night_focuses_on_the_single_game_not_the_whole_week(patched):
    at = _app()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    t = _text(at)
    assert "Monday night — one game on the ticket: Falcons at Saints" in t
    assert "Kirk Cousins" in t and "Alvin Kamara" in t
    assert "Josh Allen" not in t and "Travis Kelce" not in t          # Sunday's game excluded
    assert not at.selectbox or all("Focus" != s.label for s in at.selectbox)   # single game: no picker


def test_promotion_section_recommends_td_scorers_for_king_of_the_end_zone(patched):
    at = _app()
    at.run()
    t = _text(at)
    assert "DraftKings — King of the End Zone" in t
    assert "confirm" in t.lower()                                      # honesty about unverified terms
    promo_block = t.split("Who we like for it")[1]
    assert "Drake London" in promo_block and "yds/touch" in promo_block
    on_screen_promo = promo_block.split("Copy for the show")[0]
    assert "Kirk Cousins" not in on_screen_promo                       # Pass Attempts isn't a TD-promo market
    copy = at.code[-1].value
    assert "💰 Sportsbook promotions" in copy and "Who we like" in copy


def test_multi_game_day_offers_a_picker_and_breakdown_and_focus_filters(patched, monkeypatch):
    monkeypatch.setattr(MF, "today_eastern", lambda: __import__("datetime").date(2026, 10, 4))
    meta = _meta() + [{"label": "DAL @ NYG", "game_date": "2026-10-04T20:25:00+00:00"}]
    plays = _plays() + [_p("CeeDee Lamb", "DAL", "DAL @ NYG", "2026-10-04T20:25:00+00:00",
                           "Anytime TD", .44, 1.6, rec_yds=80, rec=7)]
    monkeypatch.setattr(nfl_engine, "build_slate", lambda d: ([], meta))
    monkeypatch.setattr(nfl_projections, "build_best_bets", lambda rows, *a, **k: plays)
    at = _app()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    t = _text(at)
    assert "Sunday afternoon — 2 games on the ticket" in t
    assert "Josh Allen" in t and "CeeDee Lamb" in t and "Drake London" not in t   # Monday's game excluded
    assert "Chiefs at Bills" in t and "Cowboys at Giants" in t                    # per-game sections
    focus = [s for s in at.selectbox if s.label == "Focus"][0]
    focus.set_value([o for o in focus.options if o.startswith("Cowboys at Giants")][0])
    at.run()
    assert not at.exception
    t2 = _text(at)
    assert "CeeDee Lamb" in t2 and "Josh Allen" not in t2


def test_no_games_on_date_explains_where_games_are(patched, monkeypatch):
    monkeypatch.setattr(MF, "today_eastern", lambda: __import__("datetime").date(2026, 10, 7))
    at = _app()
    at.run()
    assert not at.exception
    assert any("No games on this date" in i.value for i in at.info)
    assert any("2026-10-04" in c.value and "2026-10-05" in c.value for c in at.caption)


def test_owner_can_add_a_custom_promotion_and_gets_picks_for_it(patched):
    at = _app()
    at.run()
    [t for t in at.text_input if t.label == "Sportsbook"][0].set_value("FanDuel")
    [t for t in at.text_input if t.label == "Promotion name"][0].set_value("TD Boost")
    [s for s in at.selectbox if s.label.startswith("What kind")][0].set_value("anytime_td")
    [b for b in at.button if b.label == "Add promotion"][0].click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert [p["name"] for p in at.session_state["custom_promos"]] == ["TD Boost"]
    ms = [m for m in at.multiselect if m.label.startswith("Promotions running")][0]
    ms.set_value(ms.value + ["custom:fanduel:td boost"])
    at.run()
    assert "FanDuel — TD Boost" in _text(at)


def test_podcast_studio_builds_tonights_show_from_the_one_game(patched):
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "22_Podcast_Studio.py"), default_timeout=90)
    at.session_state["sport"] = "NFL"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    t = _text(at)
    assert "TONIGHT'S TICKET: Monday night — one game on the ticket: Falcons at Saints" in t
    assert "Josh Allen" not in t and "1 game tonight" in t
