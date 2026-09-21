"""test_book_menu.py — full book menu: catalog, parsing, no-vig grouping, game/team mapping,
model matching and the isolated per-market fetch (all offline; the API is faked)."""

import pytest

import book_menu as BM
import odds_api as O
import projections as P
import slip_lab as SL
import slip_sim as SIM

NORM = P.normalize_name
MMAP = {"Points": "player_points", "Pass Yards": "player_pass_yds"}


# --------------------------------------------------------------------------- catalog
def test_catalog_for_a_known_sport_has_game_and_player_groups_with_model_markets_first():
    groups = BM.catalog("americanfootball_nfl", ["player_pass_yds", "player_rush_yds"])
    assert {"Game lines", "Alternate lines", "Team totals", "Player props — main",
            "Player props — alternate lines", "Player props — specials"} <= set(groups)
    assert groups["Player props — main"][:2] == ["player_pass_yds", "player_rush_yds"]
    assert len(groups["Player props — main"]) == len(set(groups["Player props — main"]))   # no duplicates
    assert groups["Game lines"] == ["h2h", "spreads", "totals"]


def test_every_registered_sport_gets_a_catalog_and_an_unknown_one_gets_the_universal_lines():
    import sports
    checked = 0
    for s in sports.REGISTRY.values():
        if s.has_projections:
            g = BM.catalog(s.odds_sport_key, s.markets)
            assert "Game lines" in g and g["Player props — main"], s.key
            assert set(s.markets) <= set(g["Player props — main"]), s.key      # the model's own markets are all in the menu
            checked += 1
    assert checked >= 6
    assert BM.catalog("golf_pga_championship") == {"Game lines": ["h2h", "spreads", "totals"]}


def test_market_kinds():
    k = BM.market_kind
    assert k("h2h") == k("h2h_h1") == k("h2h_3_way") == k("h2h_1st_5_innings") == "moneyline"
    assert k("spreads") == k("alternate_spreads") == k("spreads_q1") == "spread"
    assert k("totals") == k("alternate_totals") == k("totals_p1") == "total"
    assert k("team_totals") == k("alternate_team_totals") == "team_total"
    assert k("player_points") == k("batter_hits") == k("pitcher_outs") == "player"
    assert k("futures_winner") == "other"


def test_market_titles_reuse_the_boards_display_names_and_describe_periods_and_alts():
    t = lambda key: BM.market_title(key, MMAP)
    assert t("player_points") == "Points" and t("player_pass_yds") == "Pass Yards"
    assert t("spreads") == t("alternate_spreads") == "Spread"          # same bet -> same leg id
    assert t("totals_h1") == "1H Game Total" and t("h2h_q1") == "1Q Moneyline"
    assert t("totals_1st_5_innings") == "First 5 Game Total"
    assert t("team_totals") == "Team Total"
    assert t("player_rush_yds_alternate") == "Rush Yards (alt)"
    assert t("batter_rbis") == "Batter RBIs" and "alt" in t("pitcher_strikeouts_alternate")
    assert t("player_anytime_td") == "Anytime TD"


def test_estimate_cost_is_events_times_markets():
    assert BM.estimate_cost(14, 40) == 560 and BM.estimate_cost(0, 5) == 0 and BM.estimate_cost(-2, 5) == 0
    groups = BM.catalog("americanfootball_nfl")
    keys = BM.all_keys(groups, ["Game lines", "Alternate lines"])
    assert keys == ["h2h", "spreads", "totals", "alternate_spreads", "alternate_totals"]
    assert BM.all_keys(groups, ["Game lines", "Game lines"]) == ["h2h", "spreads", "totals"]


# --------------------------------------------------------------------------- an event fixture
def ev_json(book="draftkings"):
    def m(key, outs):
        return {"key": key, "outcomes": outs}
    return {"id": "E1", "home_team": "Dallas Cowboys", "away_team": "New York Giants",
            "commence_time": "2026-09-21T17:00:00Z", "bookmakers": [
        {"key": "fanduel", "markets": [m("h2h", [{"name": "Dallas Cowboys", "price": -999}])]},   # other book: ignored
        {"key": book, "markets": [
            m("h2h", [{"name": "Dallas Cowboys", "price": -150}, {"name": "New York Giants", "price": 130}]),
            m("spreads", [{"name": "Dallas Cowboys", "price": -110, "point": -3.5},
                          {"name": "New York Giants", "price": -110, "point": 3.5}]),
            m("totals", [{"name": "Over", "price": -110, "point": 44.5}, {"name": "Under", "price": -110, "point": 44.5}]),
            m("team_totals", [{"name": "Over", "description": "Dallas Cowboys", "price": -115, "point": 24.5},
                              {"name": "Under", "description": "Dallas Cowboys", "price": -105, "point": 24.5}]),
            m("player_pass_yds", [{"name": "Over", "description": "Dak Prescott", "price": -115, "point": 251.5},
                                  {"name": "Under", "description": "Dak Prescott", "price": -105, "point": 251.5}]),
            m("player_reception_yds_alternate", [{"name": "Over", "description": "CeeDee Lamb", "price": 110, "point": 100.5},
                                                 {"name": "Over", "description": "CeeDee Lamb", "price": -160, "point": 70.5}]),
            m("player_anytime_td", [{"name": "Yes", "description": "CeeDee Lamb", "price": -140}]),
            m("player_pass_tds", [{"name": "Over", "description": "Dak Prescott", "price": None, "point": 1.5},
                                  {"name": "Over", "description": "Dak Prescott", "price": 0, "point": 2.5}]),
        ]}]}


INFO = {NORM("Dak Prescott"): {"game": "NYG @ DAL", "team": "DAL"},
        NORM("CeeDee Lamb"): {"game": "NYG @ DAL", "team": "DAL"}}


def menu_legs(book="draftkings"):
    quotes = BM.parse_menu_event(ev_json(book), book)
    events = {"E1": {"id": "E1", "home": "Dallas Cowboys", "away": "New York Giants", "commence": "2026-09-21T17:00:00Z"}}
    labels = BM.label_events(events, quotes, INFO, NORM)
    return BM.build_menu_legs(quotes, labels, book, market_map=MMAP, info=INFO, normalize_name=NORM), labels


def find(legs, **kw):
    hits = [l for l in legs if all(l.get(k) == v for k, v in kw.items())]
    assert len(hits) == 1, (kw, [(l["market"], l["player"], l["side"], l["line"]) for l in legs])
    return hits[0]


# --------------------------------------------------------------------------- parsing
def test_parse_keeps_only_the_chosen_book_and_drops_priceless_or_zero_price_outcomes():
    q = BM.parse_menu_event(ev_json(), "draftkings")
    assert {x["market"] for x in q} == {"h2h", "spreads", "totals", "team_totals", "player_pass_yds",
                                        "player_reception_yds_alternate", "player_anytime_td"}
    assert all(x["price"] != -999 for x in q)                          # FanDuel's row is not in DraftKings' menu
    assert {x["kind"] for x in q} == {"moneyline", "spread", "total", "team_total", "player"}
    assert BM.parse_menu_event(ev_json(), "fanduel")[0]["price"] == -999


def test_legacy_caesars_spelling_resolves_to_the_real_key():
    ev = ev_json("williamhill_us")
    assert BM.parse_menu_event(ev, "caesars")


# --------------------------------------------------------------------------- legs / no-vig
def test_moneyline_is_devigged_across_both_teams_and_labelled_with_the_boards_team():
    legs, _ = menu_legs()
    dal, nyg = find(legs, market="Moneyline", player="Dallas Cowboys"), find(legs, market="Moneyline", player="New York Giants")
    assert dal["p"] + nyg["p"] == pytest.approx(1.0, abs=2e-4)
    assert dal["p"] > 0.5 > nyg["p"]
    assert dal["side"] == "Win" and dal["kind"] == "moneyline" and dal["line"] is None
    assert dal["team"] == "DAL" and nyg["team"] == "NYG"                # mapped to the board's spelling by position
    assert dal["game"] == "NYG @ DAL" and dal["p_source"] == "market" and dal["p_mkt"] == dal["p"]
    assert dal["price"] == -150 and dal["at_book"] and dal["source"] == "menu"


def test_spread_pairs_by_absolute_point_and_keeps_the_signed_line():
    legs, _ = menu_legs()
    dal, nyg = find(legs, market="Spread", player="Dallas Cowboys"), find(legs, market="Spread", player="New York Giants")
    assert dal["line"] == -3.5 and nyg["line"] == 3.5 and dal["side"] == "Cover"
    assert dal["p"] == pytest.approx(0.5) and nyg["p"] == pytest.approx(0.5)
    assert dal["kind"] == nyg["kind"] == "spread"


def test_game_total_and_team_total_legs():
    legs, _ = menu_legs()
    over = find(legs, market="Game Total", side="Over")
    assert over["player"] == "NYG @ DAL" and over["line"] == 44.5 and over["kind"] == "total" and over["team"] is None
    assert over["p"] == pytest.approx(0.5)
    tt = find(legs, market="Team Total", side="Over")
    assert tt["player"] == "Dallas Cowboys" and tt["team"] == "DAL" and tt["kind"] == "team_total"
    assert tt["p"] == pytest.approx(SL.O.devig_two_way(-115, -105), abs=1e-3)


def test_player_prop_two_sided_uses_no_vig_and_carries_the_board_team():
    legs, _ = menu_legs()
    over = find(legs, market="Pass Yards", side="Over")
    under = find(legs, market="Pass Yards", side="Under")
    assert over["p"] + under["p"] == pytest.approx(1.0, abs=2e-4)
    assert over["team"] == "DAL" and over["kind"] == "player" and over["market_key"] == "player_pass_yds"
    assert over["id"] == SL.leg_id("Dak Prescott", "Pass Yards", "Over", 251.5)          # the board leg's own id


def test_one_sided_legs_are_flagged_implied_and_never_claim_a_no_vig_probability():
    legs, _ = menu_legs()
    alt = [l for l in legs if l["market_key"] == "player_reception_yds_alternate"]
    assert len(alt) == 2 and all(l["p_source"] == "implied" and l["p_mkt"] is None for l in alt)
    assert {l["line"] for l in alt} == {100.5, 70.5}
    by_line = {l["line"]: l for l in alt}
    assert by_line[100.5]["p"] == pytest.approx(O.implied_prob(110), abs=1e-3)
    assert by_line[70.5]["p"] == pytest.approx(O.implied_prob(-160), abs=1e-3)
    atd = [l for l in legs if l["market_key"] == "player_anytime_td"]
    assert len(atd) == 1 and atd[0]["side"] == "Yes" and atd[0]["line"] is None and atd[0]["p_source"] == "implied"
    assert atd[0]["id"].endswith("|-")


def test_market_derived_legs_carry_no_edge_and_generous_evidence():
    """A de-vigged leg's EV is minus the book's margin (never positive); a one-sided (implied) leg's is exactly 0."""
    legs, _ = menu_legs()
    for l in legs:
        if l["p_source"] == "market":
            assert -8.0 < l["ev_pct"] <= 0.05, l
        else:
            assert abs(l["ev_pct"]) < 0.06, l
        assert l["n_eff"] == BM.MENU_N_EFF and l["line_source"] == "menu"


def test_a_priceless_outcome_never_becomes_a_leg():
    legs, _ = menu_legs()
    assert not [l for l in legs if l["market_key"] == "player_pass_tds"]


def test_oversized_group_is_not_mis_devigged():
    probs, devigged = BM._group_probs([-110, -110, -110, -110])
    assert devigged is False and probs[0] == pytest.approx(O.implied_prob(-110))
    probs, devigged = BM._group_probs([-110, -110])
    assert devigged and sum(probs) == pytest.approx(1.0)
    probs, devigged = BM._group_probs([-110, 250, 300])                   # 3-way (draw) devigs
    assert devigged and sum(probs) == pytest.approx(1.0)


def test_outcome_named_for_the_player_is_treated_as_a_yes_leg():
    ev = {"id": "E1", "home_team": "H", "away_team": "A", "bookmakers": [{"key": "draftkings", "markets": [
        {"key": "player_goal_scorer_anytime", "outcomes": [{"name": "Auston Matthews", "price": 130}]}]}]}
    q = BM.parse_menu_event(ev, "draftkings")
    labels = {"E1": {"game": "A @ H", "away": "A", "home": "H", "away_team": "A", "home_team": "H"}}
    (l,) = BM.build_menu_legs(q, labels, "draftkings")
    assert l["player"] == "Auston Matthews" and l["side"] == "Yes" and l["line"] is None


def test_draw_becomes_a_non_team_leg():
    ev = {"id": "E1", "home_team": "H", "away_team": "A", "bookmakers": [{"key": "draftkings", "markets": [
        {"key": "h2h_3_way", "outcomes": [{"name": "H", "price": -120}, {"name": "A", "price": 300},
                                          {"name": "Draw", "price": 240}]}]}]}
    labels = {"E1": {"game": "A @ H", "away": "A", "home": "H", "away_team": "A", "home_team": "H"}}
    legs = BM.build_menu_legs(BM.parse_menu_event(ev, "draftkings"), labels, "draftkings")
    assert sum(l["p"] for l in legs) == pytest.approx(1.0, abs=1e-3)
    draw = [l for l in legs if l["player"] == "Draw"][0]
    assert draw["kind"] == "other" and draw["team"] is None


# --------------------------------------------------------------------------- game / team labels
def test_label_events_uses_the_boards_game_label_by_majority_vote():
    quotes = BM.parse_menu_event(ev_json(), "draftkings")
    events = {"E1": {"id": "E1", "home": "Dallas Cowboys", "away": "New York Giants", "commence": None}}
    lab = BM.label_events(events, quotes, INFO, NORM)["E1"]
    assert lab["game"] == "NYG @ DAL" and lab["away_team"] == "NYG" and lab["home_team"] == "DAL"


def test_label_events_falls_back_to_the_apis_names_when_no_player_is_known():
    quotes = BM.parse_menu_event(ev_json(), "draftkings")
    events = {"E1": {"id": "E1", "home": "Dallas Cowboys", "away": "New York Giants", "commence": None}}
    lab = BM.label_events(events, quotes, {}, NORM)["E1"]
    assert lab["game"] == "New York Giants @ Dallas Cowboys" and lab["home_team"] == "Dallas Cowboys"


def test_label_events_strips_the_doubleheader_suffix_before_splitting_teams():
    quotes = BM.parse_menu_event(ev_json(), "draftkings")
    info = {NORM("Dak Prescott"): {"game": "Mets @ Braves (Game 2)", "team": "Braves"}}
    lab = BM.label_events({"E1": {"id": "E1", "home": "h", "away": "a"}}, quotes, info, NORM)["E1"]
    assert lab["game"] == "Mets @ Braves (Game 2)" and lab["away_team"] == "Mets" and lab["home_team"] == "Braves"


def test_a_team_only_menu_is_still_tied_to_the_boards_game_through_the_boards_offers():
    """Only game lines were fetched (no player quotes), but the board's own offers carry the event id."""
    quotes = [q for q in BM.parse_menu_event(ev_json(), "draftkings") if q["kind"] != "player"]
    events = {"E1": {"id": "E1", "home": "Dallas Cowboys", "away": "New York Giants"}}
    assert BM.label_events(events, quotes, INFO, NORM)["E1"]["game"] == "New York Giants @ Dallas Cowboys"
    offers = [{"player": "Dak Prescott", "event_id": "E1"}, {"player": "Nobody Known", "event_id": "E1"},
              {"player": "CeeDee Lamb", "event_id": "OTHER"}, {"player": "x"}]
    lab = BM.label_events(events, quotes, INFO, NORM, offers=offers)["E1"]
    assert lab["game"] == "NYG @ DAL" and lab["home_team"] == "DAL" and lab["away_team"] == "NYG"


def test_menu_legs_share_a_game_string_with_board_legs_so_correlation_applies():
    legs, _ = menu_legs()
    board_leg = {"player": "Dak Prescott", "game": "NYG @ DAL", "side": "Over", "team": "DAL", "p": 0.5}
    ml = find(legs, market="Moneyline", player="Dallas Cowboys")
    R = SIM.correlation_matrix([ml, board_leg])
    assert R[0, 1] == pytest.approx(SIM.RHO_MARGIN_PLAYER)             # same game, same team


# --------------------------------------------------------------------------- model matching
def test_attach_model_swaps_in_the_models_probability_only_for_matching_player_legs():
    legs, _ = menu_legs()
    board = SL.manual_leg(player="Dak Prescott", market="Pass Yards", side="Over", line=251.5, p=0.61, price=-115,
                          game="NYG @ DAL", team="DAL", n_eff=12, book="draftkings")
    board["source"] = "board"
    idx = BM.model_index([board], MMAP, NORM)
    before = [dict(l) for l in legs]
    out = BM.attach_model(legs, idx, NORM)
    assert legs == before                                            # inputs not mutated
    m = find(out, market="Pass Yards", side="Over")
    assert m["p"] == 0.61 and m["p_source"] == "model" and m["n_eff"] == 12
    assert m["ev_pct"] == pytest.approx((0.61 * O.american_to_decimal(-115) - 1) * 100, abs=0.01)
    assert m["edge"] == pytest.approx(0.61 - m["p_mkt"], abs=1e-3)
    u = find(out, market="Pass Yards", side="Under")
    assert u["p_source"] == "market"                                 # the model priced only the Over here
    assert find(out, market="Moneyline", player="Dallas Cowboys")["p_source"] == "market"


def test_model_index_ignores_menu_legs_and_unmapped_markets():
    a = SL.manual_leg(player="X", market="Points", side="Over", line=1.5, p=0.5, game="g")
    a["source"] = "menu"
    b = SL.manual_leg(player="Y", market="Mystery", side="Over", line=1.5, p=0.5, game="g")
    b["source"] = "board"
    assert BM.model_index([a, b], MMAP, NORM) == {}


# --------------------------------------------------------------------------- fetch
class FakeGet:
    def __init__(self, table=None, fail=None):
        self.table, self.fail, self.calls = table or {}, fail or {}, []

    def __call__(self, path, params):
        self.calls.append((path, dict(params)))
        eid = path.split("/")[3]
        mk = params["markets"]
        if (eid, mk) in self.fail:
            raise self.fail[(eid, mk)]
        return self.table.get((eid, mk), {"id": eid, "home_team": "H", "away_team": "A", "bookmakers": []}), {"remaining": "497"}


def test_fetch_makes_one_single_book_request_per_event_and_market():
    get = FakeGet()
    out = BM.fetch_menu("K", "americanfootball_nfl", ["e1", "e2"], ["h2h", "spreads", "totals"], "caesars", get=get)
    assert out["requests"] == 6 and len(get.calls) == 6
    assert {(p.split("/")[3], q["markets"]) for p, q in get.calls} == {(e, m) for e in ("e1", "e2") for m in ("h2h", "spreads", "totals")}
    assert all(q["bookmakers"] == "williamhill_us" and "regions" not in q for _, q in get.calls)
    assert out["remaining"] == "497" and out["aborted"] is None and out["errors"] == []


def test_fetch_parses_quotes_and_records_events():
    get = FakeGet({("E1", "h2h"): ev_json()})
    out = BM.fetch_menu("K", "americanfootball_nfl", ["E1"], ["h2h"], "draftkings", get=get)
    assert out["events"]["E1"] == {"id": "E1", "home": "Dallas Cowboys", "away": "New York Giants",
                                   "commence": "2026-09-21T17:00:00Z"}
    assert {q["market"] for q in out["quotes"]} >= {"h2h", "spreads"}


@pytest.mark.parametrize("msg", ['HTTP 422: {"error_code":"INVALID_MARKET"}', "HTTP 422: nope", "HTTP 404: no such event"])
def test_a_rejected_market_is_reported_as_unavailable_and_the_rest_still_load(msg):
    get = FakeGet({("E1", "totals"): ev_json()}, fail={("E1", "player_sacks"): O.OddsAPIError(msg)})
    out = BM.fetch_menu("K", "americanfootball_nfl", ["E1"], ["totals", "player_sacks"], "draftkings", get=get)
    assert out["unavailable"] == [("E1", "player_sacks")] and out["errors"] == []
    assert out["quotes"] and out["aborted"] is None


def test_other_failures_are_isolated_into_errors():
    get = FakeGet({("E1", "h2h"): ev_json()}, fail={("E1", "spreads"): O.OddsAPIError("HTTP 500: boom"),
                                                    ("E1", "totals"): RuntimeError("weird")})
    out = BM.fetch_menu("K", "nfl", ["E1"], ["h2h", "spreads", "totals"], "draftkings", get=get)
    assert {(e["market"], e["error"]) for e in out["errors"]} == {("spreads", "HTTP 500: boom"), ("totals", "weird")}
    assert out["quotes"]


@pytest.mark.parametrize("msg", ["401 Unauthorized — check your API key.", "429 — out of quota for this period."])
def test_auth_or_quota_failure_aborts_and_says_so(msg):
    get = FakeGet(fail={("E1", m): O.OddsAPIError(msg) for m in ("h2h", "spreads", "totals")})
    out = BM.fetch_menu("K", "nfl", ["E1"], ["h2h", "spreads", "totals"], "draftkings", get=get, max_workers=1)
    assert out["aborted"] == msg and out["quotes"] == [] and out["unavailable"] == []


def test_progress_callback_reaches_the_total():
    seen = []
    BM.fetch_menu("K", "nfl", ["a", "b"], ["h2h", "totals"], "draftkings", get=FakeGet(),
                  progress=lambda d, n: seen.append((d, n)))
    assert seen[-1] == (4, 4) and [d for d, _ in seen] == sorted(d for d, _ in seen)


def test_fetch_with_no_work_returns_an_empty_report():
    out = BM.fetch_menu("K", "nfl", [], ["h2h"], "draftkings", get=FakeGet())
    assert out["requests"] == 0 and out["quotes"] == [] and out["aborted"] is None
