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
    assert [t.label for t in at.tabs] == ["🏅 Leg ranking", "📊 Hit distribution", "🌪️ Stress tests", "🔎 Drop a leg", "🔁 Repeat play"]
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


# =========================================================================== build 206
import book_menu as BM
import slip_suggest as SS
from datetime import timezone


def _radio(at, prefix):
    return [r for r in at.radio if r.label.startswith(prefix)][0]


def _btn(at, text):
    return [b for b in at.button if text in b.label]


def _menu_event_json(market):
    """A DraftKings response for one market of one game, players from the synthetic board."""
    def outs(key):
        if key == "h2h":
            return [{"name": "New York Knicks", "price": -140}, {"name": "Boston Celtics", "price": 120}]
        if key == "spreads":
            return [{"name": "New York Knicks", "price": -110, "point": -2.5}, {"name": "Boston Celtics", "price": -110, "point": 2.5}]
        if key == "totals":
            return [{"name": "Over", "price": -110, "point": 221.5}, {"name": "Under", "price": -110, "point": 221.5}]
        if key == "player_points":
            return [{"name": "Over", "description": "Jayson Tatum", "price": -115, "point": 27.5},
                    {"name": "Under", "description": "Jayson Tatum", "price": -105, "point": 27.5},
                    {"name": "Over", "description": "Jalen Brunson", "price": -110, "point": 24.5},
                    {"name": "Under", "description": "Jalen Brunson", "price": -110, "point": 24.5}]
        return []
    o = outs(market)
    return {"id": "EVT1", "home_team": "New York Knicks", "away_team": "Boston Celtics",
            "commence_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "bookmakers": [{"key": "draftkings", "markets": [{"key": market, "outcomes": o}]}] if o else []}


@pytest.fixture
def menu_api(monkeypatch):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(O, "fetch_events", lambda *a, **k: [{"id": "EVT1", "home_team": "New York Knicks",
                                                              "away_team": "Boston Celtics", "commence_time": now}])
    seen = []

    def fake_get(path, params):
        seen.append((path, dict(params)))
        return _menu_event_json(params["markets"]), {"remaining": "480"}
    monkeypatch.setattr(O, "_get", fake_get)
    return seen


def _open_menu(at):
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    _radio(at, "Where do legs come from").set_value("📖 Full book menu")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


# ---- suggested tickets -------------------------------------------------------
def test_suggestions_render_singles_and_parlays_and_load_into_the_slip(patched):
    at = _app("DraftKings", legs=False)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    store = at.session_state["slip_lab_ticket_store"]
    assert store, "the synthetic slate has +EV legs, so there must be suggested tickets"
    for tk in store.values():
        assert tk["mode"] == "parlay" and tk["ev_indep"] > 0 and tk["p_all"] is not None
        assert all(SS.is_model_priced(l) and l["at_book"] for l in tk["legs"])
    assert at.session_state["slip_lab_single_store"]["likely"]
    assert any("Most likely to hit" in m.value for m in at.markdown) and any("Best value" in m.value for m in at.markdown)
    load = _btn(at, "Load into slip")
    assert load
    ids_of_first = [l["id"] for l in store["t0"]["legs"]]
    load[0].click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert [l["id"] for l in at.session_state["slip_lab_legs"]] == ids_of_first
    assert at.session_state["slip_lab_mode"] == "parlay"
    assert any("Loaded the" in s.value for s in at.success)
    assert not any("Add legs from the pool" in i.value for i in at.info)          # the slip is now populated


def test_loading_singles_sets_singles_mode_and_stakes(patched):
    at = _app("DraftKings", legs=False)
    at.run()
    btn = _btn(at, "as a singles slip")
    assert btn
    btn[0].click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["slip_lab_mode"] == "singles"
    loaded = at.session_state["slip_lab_legs"]
    assert loaded and all(l["stake"] > 0 for l in loaded)


def test_loading_a_ticket_clears_a_stale_result_and_typed_parlay_price(patched):
    at = _run_test(_app("DraftKings"))
    assert at.session_state["slip_lab_result"] is not None
    at.session_state["slip_lab_parlay_price"] = 350
    _btn(at, "Load into slip")[0].click()
    at.run()
    assert not at.exception
    assert at.session_state["slip_lab_result"] is None
    assert at.session_state["slip_lab_parlay_price"] == 0


def test_pickem_suggestions_are_entries_only_never_singles(patched):
    at = _app("PrizePicks", legs=False)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["slip_lab_single_store"] == {"likely": [], "value": []}
    assert not _btn(at, "as a singles slip")
    modes = {t["mode"] for t in at.session_state["slip_lab_ticket_store"].values()}
    assert modes <= {"power", "flex"}


def test_bet365_explains_there_is_nothing_to_rank(patched):
    at = _app("Bet365", legs=False)
    at.run()
    assert not at.exception
    assert any("nothing to rank" in i.value for i in at.info)


def test_suggestions_ignore_market_only_legs(patched):
    at = _app("DraftKings", legs=False)
    at.run()
    for tk in at.session_state["slip_lab_ticket_store"].values():
        assert not any(l.get("p_source") in ("market", "implied") for l in tk["legs"])


# ---- leg ranking tab ---------------------------------------------------------
def test_leg_ranking_tab_names_the_strongest_and_weakest_leg(patched):
    at = _run_test(_app("DraftKings"))
    texts = [m.value for m in list(at.success) + list(at.warning) + list(at.info)]
    assert any("Strongest leg" in t for t in texts) and any("Weakest leg" in t for t in texts)
    res = at.session_state["slip_lab_result"]["res"]
    sc = SS.leg_scorecard(at.session_state["slip_lab_legs"])
    assert len(sc) == res["k"] == 3
    strongest = sc[0]["label"]
    assert any(strongest in t for t in texts if "Strongest leg" in t)


# ---- prefilled logging widget ---------------------------------------------------
def test_quick_log_opens_on_the_tested_slip(patched):
    at = _run_test(_app("DraftKings"))
    ss = at.session_state
    assert ss["slip_lab_ql_picks"] == [0, 1, 2]
    assert ss["slip_lab_ql_mode_parlay"] is True and ss["slip_lab_ql_mode_singles"] is False
    assert ss["slip_lab_ql_p_stake_pick"] == 10.0 and ss["slip_lab_ql_p_stake_10.0"] == 10.0


def test_quick_log_prefill_for_singles_uses_the_average_stake(patched):
    at = _app("DraftKings")
    for i, l in enumerate(at.session_state["slip_lab_legs"]):
        l["stake"] = [5.0, 10.0, 15.0][i]
    at = _run_test(at, "singles")
    ss = at.session_state
    assert ss["slip_lab_ql_mode_singles"] is True and ss["slip_lab_ql_mode_parlay"] is False
    assert ss["slip_lab_ql_s_stake_pick"] == 10.0


def test_prefill_does_not_overwrite_a_stake_the_user_typed_for_logging(patched):
    at = _run_test(_app("DraftKings"))
    at.session_state["slip_lab_ql_p_stake_pick"] = 25.0
    at.run()
    assert at.session_state["slip_lab_ql_p_stake_pick"] == 25.0          # same slip -> left alone


# ---- full book menu -------------------------------------------------------------
def test_menu_is_unavailable_for_pickem_and_manual_books(patched):
    for book in ("PrizePicks", "Bet365"):
        at = _app(book, legs=False)
        _open_menu(at)
        assert any("full menu is available for sportsbooks" in i.value for i in at.info), book


def test_fetching_the_menu_costs_one_request_per_game_and_market_at_one_book(patched, menu_api):
    at = _open_menu(_app("DraftKings", legs=False))
    assert any("up to **" in c.value and "Odds API credits" in c.value for c in at.caption)     # estimate shown first
    assert menu_api == []                                                                    # nothing fetched until pressed
    _btn(at, "Fetch menu")[0].click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    markets = [q["markets"] for _, q in menu_api]
    assert sorted(markets) == sorted(BM.all_keys(BM.catalog("basketball_nba", sports.get("NBA").markets),
                                                 ["Game lines", "Team totals"]))
    assert all(q["bookmakers"] == "draftkings" and "regions" not in q for _, q in menu_api)
    menu = at.session_state["slip_lab_menu"]
    assert menu["ctx"][2] == "draftkings" and menu["quotes"] and menu["remaining"] == "480"
    assert any("Menu fetched" in c.value and "480 credits remaining" in c.value for c in at.caption)


def test_menu_legs_show_team_and_game_markets_and_match_the_model(patched, menu_api):
    at = _open_menu(_app("DraftKings", legs=False))
    at.multiselect(key="slip_lab_menu_groups").set_value(["Game lines", "Player props — main"])
    at.run()
    _btn(at, "Fetch menu")[0].click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    menu = at.session_state["slip_lab_menu"]
    sp = sports.get("NBA")
    norm = sp.projections.normalize_name
    pool = SL.build_leg_pool(_plays(), _offers(), "draftkings", sp.market_map, norm)
    info = BM.board_player_info(pool, norm)
    labels = BM.label_events(menu["events"], menu["quotes"], info, norm)
    legs = BM.attach_model(BM.build_menu_legs(menu["quotes"], labels, "draftkings", market_map=sp.market_map, info=info,
                                              normalize_name=norm), BM.model_index(pool, sp.market_map, norm), norm)
    kinds = {l["kind"] for l in legs}
    assert {"moneyline", "spread", "total", "player"} <= kinds
    tatum = [l for l in legs if l["player"] == "Jayson Tatum" and l["side"] == "Over"][0]
    assert tatum["p"] == 0.58 and tatum["p_source"] == "model"              # the board's number, not the book's
    ml = [l for l in legs if l["kind"] == "moneyline"][0]
    assert ml["game"] == "BOS @ NYK"                                       # tied to the board's own game label
    # the page rendered the menu table without error and offers the "Basis" explanation
    assert any("Basis" in c.value for c in at.caption)


def test_a_menu_slip_pressure_tests_and_says_the_market_legs_have_no_edge(patched, menu_api):
    at = _app("DraftKings", legs=False)
    sp = sports.get("NBA")
    norm = sp.projections.normalize_name
    quotes = BM.parse_menu_event(_menu_event_json("h2h"), "draftkings") + BM.parse_menu_event(_menu_event_json("spreads"), "draftkings")
    pool = SL.build_leg_pool(_plays(), _offers(), "draftkings", sp.market_map, norm)
    info = BM.board_player_info(pool, norm)
    labels = BM.label_events({"EVT1": {"id": "EVT1", "home": "New York Knicks", "away": "Boston Celtics"}}, quotes, info, norm)
    legs = BM.build_menu_legs(quotes, labels, "draftkings", market_map=sp.market_map, info=info, normalize_name=norm)
    ml = [l for l in legs if l["kind"] == "moneyline" and l["team"] == "NYK" or l["kind"] == "moneyline" and l["player"] == "New York Knicks"][:1]
    sprd = [l for l in legs if l["kind"] == "spread" and l["player"] == "New York Knicks"][:1]
    board = [l for l in pool if l["side"] == "Over"][:1]
    assert ml and sprd and board
    at.session_state["slip_lab_ctx"] = ("NBA", _date())
    at.session_state["slip_lab_legs"] = [dict(l, stake=10.0) for l in ml + sprd + board]
    at.session_state["slip_lab_ver"] = 1
    at.session_state["slip_lab_book_seen"] = "draftkings"
    at = _run_test(at)
    res = at.session_state["slip_lab_result"]["res"]
    assert res["k"] == 3 and res["n_market_prob"] == 2
    texts = [m.value for m in list(at.success) + list(at.warning) + list(at.error) + list(at.info)]
    assert any("2 of 3 legs use the book's own probability" in t for t in texts)
    calls = patched
    plays = calls[-1][0][0]
    team_plays = [p for p in plays if p["Player"] is None]
    assert len(team_plays) == 2 and {p["Market"] for p in team_plays} == {"Moneyline", "Spread"}


def test_switching_book_strips_the_price_from_menu_legs(patched):
    at = _app("DraftKings")
    legs = at.session_state["slip_lab_legs"]
    legs[0] = dict(legs[0], source="menu", p_source="market")
    at.session_state["slip_lab_book_seen"] = "draftkings"
    at.session_state["slip_lab_book_selector"] = "FanDuel"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    first = at.session_state["slip_lab_legs"][0]
    assert first["price"] is None and first["at_book"] is False


def test_menu_fetch_failures_are_reported_not_fatal(patched, monkeypatch):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(O, "fetch_events", lambda *a, **k: [{"id": "EVT1", "home_team": "H", "away_team": "A", "commence_time": now}])

    def boom(path, params):
        if params["markets"] == "h2h":
            raise O.OddsAPIError("HTTP 500: kaboom")
        return _menu_event_json(params["markets"]), {"remaining": "9"}
    monkeypatch.setattr(O, "_get", boom)
    at = _open_menu(_app("DraftKings", legs=False))
    _btn(at, "Fetch menu")[0].click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert [e["market"] for e in at.session_state["slip_lab_menu"]["errors"]] == ["h2h"]
    assert any("1 request(s) failed" in e.label for e in at.expander)


def test_quota_exhaustion_stops_the_fetch_and_says_so(patched, monkeypatch):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(O, "fetch_events", lambda *a, **k: [{"id": "EVT1", "home_team": "H", "away_team": "A", "commence_time": now}])
    monkeypatch.setattr(O, "_get", lambda p, q: (_ for _ in ()).throw(O.OddsAPIError("429 — out of quota for this period.")))
    at = _open_menu(_app("DraftKings", legs=False))
    _btn(at, "Fetch menu")[0].click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("fetch stopped early" in e.value and "quota" in e.value for e in at.error)


def test_a_large_fetch_needs_an_explicit_credit_confirmation(patched, monkeypatch):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(O, "fetch_events", lambda *a, **k: [
        {"id": f"EVT{i}", "home_team": f"H{i}", "away_team": f"A{i}", "commence_time": now} for i in range(5)])
    calls = []
    monkeypatch.setattr(O, "_get", lambda p, q: (calls.append(q), ({"id": "x", "bookmakers": []}, {}))[1])
    at = _open_menu(_app("DraftKings", legs=False))
    at.multiselect(key="slip_lab_menu_games").set_value([o for o in at.multiselect(key="slip_lab_menu_games").options])
    at.multiselect(key="slip_lab_menu_groups").set_value(list(BM.catalog("basketball_nba", sports.get("NBA").markets)))
    at.run()
    assert any("may use up to" in c.label for c in at.checkbox)
    assert _btn(at, "Fetch menu")[0].disabled and calls == []
    at.checkbox(key="slip_lab_menu_confirm").check()
    at.run()
    assert not _btn(at, "Fetch menu")[0].disabled


# =========================================================================== time slot / game filter
def _dated_plays():
    plays = _plays()
    when = {"BOS @ NYK": "2099-01-01T18:05:00Z",      # 1:05 PM ET  -> Afternoon
            "DEN @ LAL": "2099-01-02T01:30:00Z"}      # 8:30 PM ET  -> Late
    for pl in plays:
        pl["GameDate"] = when[pl["Game"]]
    return plays


def _sel(at, label):
    return [s for s in at.selectbox if s.label == label][0]


def _dated_app(monkeypatch, patched):
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (_dated_plays(), [], ["draftkings"]))
    return _app(legs=False)


def _pool_rows(at):
    """The leg-pool table's players, read back from the page's own filtered list."""
    return {df.value.iloc[i]["Player"] for df in at.dataframe for i in range(len(df.value))
            if "Player" in df.value.columns and "Add" in df.value.columns}


def test_time_slot_and_game_filters_appear_and_default_to_everything(monkeypatch, patched):
    at = _dated_app(monkeypatch, patched)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    slot, game = _sel(at, "Time slot"), _sel(at, "Game")
    assert slot.options == ["All slate", "Afternoon", "Late"]
    assert slot.value == "All slate" and game.value == "All games in this slot"
    # chronological, each with its real Eastern start time
    assert game.options == ["All games in this slot", "1:05 PM ET — BOS @ NYK", "8:30 PM ET — DEN @ LAL"]


def test_picking_a_time_slot_narrows_the_game_list_and_the_suggestions(monkeypatch, patched):
    at = _dated_app(monkeypatch, patched)
    at.run()
    _sel(at, "Time slot").set_value("Late")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert _sel(at, "Game").options == ["All games in this slot", "8:30 PM ET — DEN @ LAL"]
    assert any("Late" in c.value and "time slot" in c.value for c in at.caption)
    for t in at.session_state["slip_lab_ticket_store"].values():
        assert {l["game"] for l in t["legs"]} <= {"DEN @ LAL"}
    singles = at.session_state["slip_lab_single_store"]
    for row in singles["likely"] + singles["value"]:
        assert row["leg"]["game"] == "DEN @ LAL"


def test_picking_a_game_limits_the_pool_to_that_game(monkeypatch, patched):
    at = _dated_app(monkeypatch, patched)
    at.run()
    _sel(at, "Game").set_value("1:05 PM ET — BOS @ NYK")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("time slot" not in c.value and "Narrowed to" in c.value and "BOS @ NYK" in c.value for c in at.caption)
    assert at.session_state["slip_lab_ticket_store"], "the BOS @ NYK legs alone should still make tickets"
    for t in at.session_state["slip_lab_ticket_store"].values():
        assert {l["game"] for l in t["legs"]} <= {"BOS @ NYK"}


def test_a_slot_with_no_matching_legs_says_so_instead_of_breaking(monkeypatch, patched):
    at = _dated_app(monkeypatch, patched)
    at.run()
    _sel(at, "Time slot").set_value("Afternoon")
    at.run()
    _sel(at, "Time slot").set_value("Late")           # the game selected below no longer exists in the new slot
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert _sel(at, "Game").value == "All games in this slot"


# =========================================================================== build 208: filters at the top, single-game
def _one_game_plays():
    """Four different players in BOS @ NYK (enough for a 3- or 4-leg ticket from one game) and one in DEN @ LAL."""
    rows = [("Jayson Tatum", "Points", 27.5, 0.60, "BOS @ NYK"), ("Jalen Brunson", "Points", 26.5, 0.61, "BOS @ NYK"),
            ("Josh Hart", "Rebounds", 8.5, 0.59, "BOS @ NYK"), ("Derrick White", "Assists", 5.5, 0.60, "BOS @ NYK"),
            ("Nikola Jokic", "Assists", 8.5, 0.57, "DEN @ LAL"), ("Austin Reaves", "Points", 18.5, 0.58, "DEN @ LAL")]
    plays = [{"Player": n, "PlayerId": i, "Team": "T", "Game": g, "Opp": "X", "Market": m, "Side": "Over", "Line": ln,
              "ModelProb": p, "Fair": -130, "Conviction": 1.2, "Why": "w",
              "GameDate": "2099-01-01T18:05:00Z" if g == "BOS @ NYK" else "2099-01-02T01:30:00Z",
              "_stat_key": "pts", "_game_log": [{"pts": v} for v in (30, 20, 28, 31, 25, 22, 27, 26)]}
             for i, (n, m, ln, p, g) in enumerate(rows)]
    mk = {"Points": "player_points", "Rebounds": "player_rebounds", "Assists": "player_assists"}
    offers = [{"market": mk[pl["Market"]], "player": pl["Player"], "point": pl["Line"], "event_id":
               "EVT1" if pl["Game"] == "BOS @ NYK" else "EVT2",
               "over": {"draftkings": 105, "fanduel": 100}, "under": {"draftkings": -125, "fanduel": -120}}
              for pl in plays]
    return plays, offers


@pytest.fixture
def one_game_slate(monkeypatch):
    plays, offers = _one_game_plays()
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, [], ["draftkings"]))
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: offers)
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "KEY")
    monkeypatch.setattr(quick_log, "render_quick_log", lambda *a, **k: None)


def _slider(at, label):
    return [s for s in at.select_slider if s.label == label][0]


def _sizes(at):
    return {t["k"] for t in at.session_state["slip_lab_ticket_store"].values()}


def test_with_every_game_in_play_the_per_game_cap_still_applies(one_game_slate):
    at = _app(legs=False)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert _slider(at, "Max legs from one game").disabled is False
    for t in at.session_state["slip_lab_ticket_store"].values():
        per = {}
        for l in t["legs"]:
            per[l["game"]] = per.get(l["game"], 0) + 1
        assert max(per.values()) <= 2


def test_selecting_one_game_removes_the_per_game_cap(one_game_slate):
    at = _app(legs=False)
    at.run()
    _sel(at, "Game").set_value("1:05 PM ET — BOS @ NYK")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert _slider(at, "Max legs from one game").disabled is True
    assert max(_sizes(at)) >= 3, "with four BOS @ NYK players and no cap, a 3+ leg ticket must be possible"
    for t in at.session_state["slip_lab_ticket_store"].values():
        assert {l["game"] for l in t["legs"]} == {"BOS @ NYK"}
    assert any("no limit on legs from the same game" in c.value for c in at.caption)


def test_going_back_to_all_games_restores_the_cap(one_game_slate):
    at = _app(legs=False)
    at.run()
    _sel(at, "Game").set_value("1:05 PM ET — BOS @ NYK")
    at.run()
    _sel(at, "Game").set_value("All games in this slot")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert _slider(at, "Max legs from one game").disabled is False
    assert not any("no limit on legs from the same game" in c.value for c in at.caption)


def test_the_filters_sit_above_the_suggested_tickets(one_game_slate):
    at = _app(legs=False)
    at.run()
    order = [(getattr(e, "type", None), getattr(e, "label", None)) for e in at.main]     # document order of the widgets
    labels = [lbl for _, lbl in order if lbl]
    assert labels.index("Time slot") < labels.index("Game") < labels.index("Ticket sizes (legs)")
    assert labels.index("Game") < labels.index("Markets")


def test_a_game_filter_that_stops_existing_falls_back_to_all(one_game_slate):
    at = _app(legs=False)
    at.run()
    _sel(at, "Game").set_value("1:05 PM ET — BOS @ NYK")
    at.run()
    _sel(at, "Time slot").set_value("Late")                 # BOS @ NYK is an Afternoon game
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["slip_lab_game"] == "All games in this slot"
    assert _sel(at, "Game").options == ["All games in this slot", "8:30 PM ET — DEN @ LAL"]


def test_picking_a_game_preselects_just_that_game_in_the_menu_fetch(one_game_slate, menu_api, monkeypatch):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(O, "fetch_events", lambda *a, **k: [
        {"id": "EVT1", "home_team": "New York Knicks", "away_team": "Boston Celtics", "commence_time": now},
        {"id": "EVT2", "home_team": "Los Angeles Lakers", "away_team": "Denver Nuggets", "commence_time": now}])
    at = _app(legs=False)
    at.run()
    _sel(at, "Game").set_value("8:30 PM ET — DEN @ LAL")
    at.run()
    _radio(at, "Where do legs come from").set_value("📖 Full book menu")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    picked = at.multiselect(key="slip_lab_menu_games").value
    assert len(picked) == 1 and picked[0].startswith("Denver Nuggets @ Los Angeles Lakers")
    assert menu_api == []                                                    # choosing a game never spends credits
    _sel(at, "Game").set_value("All games in this slot")                    # back to All leaves the selection alone
    at.run()
    assert len(at.multiselect(key="slip_lab_menu_games").value) == 1


def test_in_the_full_menu_view_the_suggestions_still_follow_the_time_slot_and_game(one_game_slate, menu_api):
    at = _app(legs=False)
    at.run()
    _radio(at, "Where do legs come from").set_value("📖 Full book menu")
    at.run()
    _sel(at, "Game").set_value("8:30 PM ET — DEN @ LAL")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    tickets = at.session_state["slip_lab_ticket_store"].values()
    assert tickets and all({l["game"] for l in t["legs"]} == {"DEN @ LAL"} for t in tickets)
    assert any("Narrowed to" in c.value and "DEN @ LAL" in c.value for c in at.caption)
