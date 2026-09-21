"""
test_slip_lab_page.py — renders views/37_Slip_Lab.py end to end with Streamlit's AppTest, the loaders
monkeypatched to a small synthetic NBA slate (no network). Covers each kind of book (sportsbook,
pick'em, manual), each payout mode, the pressure-test button, and the lock-in hand-off.
"""

from datetime import datetime
from pathlib import Path

import pytest
import pytz
from streamlit.testing.v1 import AppTest

import best_bets_data as BBD
import odds_api as O
import quick_log
import slip_lab as SL
import sports

PAGE = str(Path(__file__).parent / "views" / "37_Slip_Lab.py")


def _plays():
    rows = [("Jayson Tatum", "Points", 27.5, 0.58, "BOS @ NYK"), ("Jayson Tatum", "Rebounds", 8.5, 0.55, "BOS @ NYK"),
            ("Jalen Brunson", "Points", 26.5, 0.60, "BOS @ NYK"), ("Nikola Jokic", "Assists", 8.5, 0.57, "DEN @ LAL")]
    return [{"Player": n, "PlayerId": i, "Team": "T", "Game": g, "Opp": "X", "Market": m, "Side": "Over", "Line": ln,
             "ModelProb": p, "Fair": -130, "Conviction": 1.2, "Why": "w", "GameDate": None,
             "_stat_key": "pts", "_game_log": [{"pts": v} for v in (30, 20, 28, 31, 25, 22)]}
            for i, (n, m, ln, p, g) in enumerate(rows)]


def _offers():
    def off(player, market, point):
        return {"market": market, "player": player, "point": point,
                "over": {"draftkings": -115, "fanduel": -110, "hardrockbet": -120},
                "under": {"draftkings": -105, "fanduel": -110, "hardrockbet": 100},
                "pickem": {"prizepicks": {"over": {"price": None}, "under": {"price": None}},
                           "pick6": {"over": {"price": None}, "under": {"price": None}}}}
    return [off("Jayson Tatum", "player_points", 27.5), off("Jayson Tatum", "player_rebounds", 8.5),
            off("Jalen Brunson", "player_points", 26.5), off("Nikola Jokic", "player_assists", 8.5)]


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (_plays(), [], ["draftkings"]))
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: _offers())
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "KEY")
    calls = []
    monkeypatch.setattr(quick_log, "render_quick_log", lambda *a, **k: calls.append((a, k)))
    return calls


def _date():
    return datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")


def _app(book_label="DraftKings", *, sport="NBA", legs=True, audience=None):
    at = AppTest.from_file(PAGE, default_timeout=90)
    at.session_state["sport"] = sport
    if audience:
        at.secrets["AUDIENCE"] = audience
    if legs:
        sp = sports.get("NBA")
        pool = SL.build_leg_pool(_plays(), _offers(), "draftkings", sp.market_map, sp.projections.normalize_name)
        at.session_state["slip_lab_ctx"] = ("NBA", _date())
        at.session_state["slip_lab_legs"] = [dict(l, stake=10.0) for l in pool if l["side"] == "Over"][:3]
        at.session_state["slip_lab_ver"] = 1
        at.session_state["slip_lab_book_seen"] = "x"
    at.session_state["slip_lab_book_selector"] = book_label
    return at


def _run_test(at, mode=None):
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    if mode:
        [r for r in at.radio if r.label.startswith("How does")][0].set_value(mode)
        at.run()
        assert not at.exception, [e.value for e in at.exception]
    [b for b in at.button if "Run pressure" in b.label][0].click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_empty_slip_shows_pool_and_prompt_without_errors(patched):
    at = _app(legs=False)
    at.run()
    assert not at.exception
    assert any("Add legs from the pool" in i.value for i in at.info)
    assert any(b.label.startswith("➕ Add checked legs") for b in at.button)


@pytest.mark.parametrize("book,mode", [
    ("DraftKings", None), ("DraftKings", "singles"), ("Hard Rock Bet", None), ("FanDuel", None),
    ("PrizePicks", "power"), ("PrizePicks", "flex"), ("DK Pick6", "pick6"),
])
def test_pressure_test_runs_for_every_book_and_mode(patched, book, mode):
    at = _run_test(_app(book), mode)
    assert [t.label for t in at.tabs] == ["📊 Hit distribution", "🌪️ Stress tests", "🔎 Leg by leg", "🔁 Repeat play"]
    assert at.session_state["slip_lab_result"]["res"]["k"] == 3
    verdicts = [m.value for m in list(at.success) + list(at.warning) + list(at.error)]
    assert verdicts, "the plain-language verdict should render"


def test_results_are_tied_to_the_exact_slip_that_was_tested(patched):
    at = _run_test(_app("DraftKings"))
    stored = at.session_state["slip_lab_result"]
    legs = at.session_state["slip_lab_legs"]
    legs[0]["p"] = 0.9                                   # change a probability after testing
    at.run()
    assert any("slip has changed since the last test" in w.value for w in at.warning)
    assert not at.tabs                                   # stale results are hidden, not shown as current
    assert stored["res"]["k"] == 3


def test_bet365_is_manual_legs_have_no_price_until_typed(patched):
    at = _app("Bet365")
    at.run()
    assert not at.exception
    assert any("typed in by hand" in c.value for c in at.caption)
    assert any("Every leg needs a price" in i.value for i in at.info)       # board legs carry no Bet365 price
    for l in at.session_state["slip_lab_legs"]:
        l["price"] = -110.0
    at.run()
    assert not at.exception


def test_pickem_book_warns_about_legs_it_does_not_post(patched, monkeypatch):
    offers = _offers()
    offers[0]["pickem"] = {}                                 # PrizePicks doesn't post Tatum points
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: offers)
    at = _app("PrizePicks")
    at.run()
    assert not at.exception
    assert any("doesn't post these" in w.value and "Tatum" in w.value for w in at.warning)


def test_book_with_no_lines_warns_but_does_not_crash(patched, monkeypatch):
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: [])
    at = _app("FanDuel", legs=False)
    at.run()
    assert not at.exception


def test_missing_api_key_still_renders_with_a_warning(patched, monkeypatch):
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: None)
    at = _app(legs=False)
    at.run()
    assert not at.exception
    assert any("No Odds API key" in w.value for w in at.warning)


def test_lock_in_uses_the_tested_prices_not_a_fresh_lookup(patched):
    calls = patched
    _run_test(_app("DraftKings"))
    args, kwargs = calls[-1]
    plays, date_str, sport_key = args
    assert sport_key == "NBA" and kwargs["key_prefix"] == "slip_lab"
    assert kwargs["offers"] is None                       # never substitute another book's price
    assert kwargs["is_parlay"] is True
    assert len(plays) == 3 and all(p["PriceSource"] == "book" and p["RealPrice"] == -115 for p in plays)


def test_lock_in_defaults_to_singles_for_a_singles_slip(patched):
    calls = patched
    _run_test(_app("DraftKings"), "singles")
    assert calls[-1][1]["is_parlay"] is False


def test_ufc_is_redirected(patched):
    at = _app(sport="UFC", legs=False)
    at.run()
    assert not at.exception
    assert any("doesn't apply to UFC" in i.value for i in at.info)


def test_non_owner_sessions_get_nothing(patched):
    at = _app(legs=False, audience="public")
    at.run()
    assert not at.exception
    assert any("owner tools" in i.value for i in at.info)
    assert not [b for b in at.button if "Add checked" in b.label]


def test_switching_book_reprices_the_legs_on_the_slip(patched):
    at = _app("Hard Rock Bet")
    at.run()
    assert not at.exception
    assert {l["price"] for l in at.session_state["slip_lab_legs"]} == {-120.0}
    at.session_state["slip_lab_book_selector"] = "FanDuel"
    at.run()
    assert {l["price"] for l in at.session_state["slip_lab_legs"]} == {-110.0}
    assert all(l["p"] in (0.58, 0.55, 0.6) for l in at.session_state["slip_lab_legs"])   # probabilities untouched


def test_mlb_path_loads_and_prices_home_run_yes_legs(monkeypatch):
    plays = [{"Player": "Aaron Judge", "PlayerId": 1, "Team": "NYY", "Game": "NYY @ BOS", "Opp": "X",
              "Market": "Batter HR", "Side": "Yes", "Line": None, "ModelProb": 0.22, "Fair": 355, "Conviction": 1.3,
              "Why": "w", "GameDate": None},
             {"Player": "Aaron Judge", "PlayerId": 1, "Team": "NYY", "Game": "NYY @ BOS", "Opp": "X",
              "Market": "Batter Total Bases", "Side": "Over", "Line": 1.5, "ModelProb": 0.55, "Fair": -122,
              "Conviction": 1.1, "Why": "w", "GameDate": None},
             {"Player": "Rafael Devers", "PlayerId": 2, "Team": "BOS", "Game": "NYY @ BOS", "Opp": "X",
              "Market": "Batter Total Bases", "Side": "Over", "Line": 1.5, "ModelProb": 0.50, "Fair": 100,
              "Conviction": 1.0, "Why": "w", "GameDate": None}]
    offers = [{"market": "batter_home_runs", "player": "Aaron Judge", "point": 0.5,
               "over": {"draftkings": 380, "fanduel": 400}, "under": {}},
              {"market": "batter_total_bases", "player": "Aaron Judge", "point": 1.5,
               "over": {"draftkings": -125, "fanduel": -120}, "under": {"draftkings": 100, "fanduel": 100}}]
    monkeypatch.setattr(BBD, "load_mlb_best_bets_board", lambda *a, **k: (plays, [], ["draftkings"]))
    monkeypatch.setattr(BBD, "fetch_mlb_real_lines", lambda *a, **k: ({}, offers, ["draftkings"]))
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "KEY")
    monkeypatch.setattr(quick_log, "render_quick_log", lambda *a, **k: None)
    at = AppTest.from_file(PAGE, default_timeout=90)
    at.session_state["sport"] = "MLB"
    at.session_state["slip_lab_book_selector"] = "DraftKings"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any(b.label.startswith("➕ Add checked legs") for b in at.button)
    # build the same pool the page did and check the HR leg is in it, priced at DraftKings
    sp = sports.get("MLB")
    pool = SL.build_leg_pool(plays, offers, "draftkings", sp.market_map, sp.projections.normalize_name,
                             single_line_markets=sp.single_line_markets)
    hr = [l for l in pool if l["market"] == "Batter HR"]
    assert len(hr) == 1 and hr[0]["side"] == "Yes" and hr[0]["price"] == 380
