"""position_lines.py — which book line goes with which log column, and the best over / under price."""
import pytest

import odds_api as O
import position_lines as PL


def off(player, market, point, over=None, under=None):
    return {"player": player, "market": market, "point": point, "over": over or {}, "under": under or {}}


def test_names_match_across_punctuation_and_suffixes():
    assert PL.norm_name("D.J. Moore Jr.") == PL.norm_name("DJ Moore") == "dj moore"
    assert PL.norm_name("Amon-Ra St. Brown") == PL.norm_name("Amon-Ra St Brown") == "amonra st brown"
    assert PL.norm_name(None) == "" and PL.norm_name("Kenneth Walker III") == "kenneth walker"
    assert PL.norm_name("Ja'Marr Chase") == "jamarr chase"


def test_markets_for_the_shown_columns_are_distinct_and_skip_unmarketed_ones():
    cols = (("atd", "ATD"), ("td", "TD"), ("tgt_share", "SHARE"), ("rec", "REC"), ("rec_yds", "YDS"), ("tgt", "TGT"))
    assert PL.markets_for(cols) == ["player_anytime_td", "player_receptions", "player_reception_yds"]
    assert PL.markets_for(()) == []
    for key, market in PL.COLUMN_MARKETS.items():
        assert market.startswith("player_"), key


def test_match_event_finds_the_game_in_either_order_and_ignores_case():
    evs = [{"id": "1", "home_team": "Dallas Cowboys", "away_team": "Houston Texans"},
           {"id": "2", "home_team": "New York Giants", "away_team": "Dallas Cowboys"}]
    assert PL.match_event(evs, "dallas cowboys", "NEW YORK GIANTS")["id"] == "2"
    assert PL.match_event(evs, "Houston Texans", "Dallas Cowboys")["id"] == "1"
    assert PL.match_event(evs, "Dallas Cowboys", "Miami Dolphins") is None and PL.match_event(None, "a", "b") is None


def test_best_lines_picks_the_line_most_books_post_then_the_best_prices_on_it():
    offers = [off("Nico Collins", "player_reception_yds", 79.5, {"dk": -110, "fd": -105}, {"dk": -110, "fd": -115}),
              off("Nico Collins", "player_reception_yds", 74.5, {"mgm": -150}, {"mgm": 120}),
              off("Other Guy", "player_reception_yds", 10.5, {"dk": -110}, {"dk": -110})]
    b = PL.best_lines(offers, "Nico Collins", (("rec_yds", "YDS"),))["rec_yds"]
    assert b["point"] == 79.5 and b["books"] == 2 and b["over"] == ("fd", -105) and b["under"] == ("dk", -110)


def test_best_lines_tie_goes_to_the_more_balanced_line_then_the_lower_number():
    even = off("P", "player_receptions", 5.5, {"a": -110}, {"a": -110})
    skew = off("P", "player_receptions", 4.5, {"a": -190}, {"a": 150})
    assert PL.best_lines([skew, even], "P", (("rec", "REC"),))["rec"]["point"] == 5.5
    low, high = off("P", "player_receptions", 4.5, {"a": -110}, {"a": -110}), off("P", "player_receptions", 5.5, {"a": -110}, {"a": -110})
    assert PL.best_lines([high, low], "P", (("rec", "REC"),))["rec"]["point"] == 4.5


def test_yes_only_markets_have_an_over_but_no_under():
    b = PL.best_lines([off("Jake Ferguson", "player_anytime_td", 0.5, {"dk": 210, "fd": 230})], "jake ferguson", (("atd", "ATD"), ("td", "TD")))
    assert b["atd"]["over"] == ("fd", 230) and b["atd"]["under"] is None and b["td"] == b["atd"]


def test_columns_without_a_market_or_a_posted_line_are_absent():
    b = PL.best_lines([off("P", "player_receptions", 5.5, {"a": -110}, {"a": -110})], "P", (("tgt_share", "S"), ("rec", "R"), ("rec_yds", "Y")))
    assert list(b) == ["rec"] and PL.best_lines([], "P", (("rec", "R"),)) == {} and PL.best_lines(None, "P", (("rec", "R"),)) == {}


def test_lines_from_and_price_format():
    assert PL.lines_from({"rec": {"point": 5.5}, "rec_yds": {"point": 79.5}}) == {"rec": 5.5, "rec_yds": 79.5}
    assert [PL.fmt_price(x) for x in (294, -115, 0, "x", None)] == ["+294", "-115", "+0", "—", "—"]


def test_fetch_offers_returns_errors_instead_of_raising(monkeypatch):
    seen = {}

    def ok(event_id, key, markets, sport):
        seen.update(event_id=event_id, key=key, markets=markets, sport=sport)
        return {"id": event_id}, {}

    monkeypatch.setattr(O, "fetch_event_props", ok)
    monkeypatch.setattr(O, "parse_event_offers", lambda data, supported_markets: [{"market": supported_markets[0], "data": data}])
    offers, err = PL.fetch_offers("KEY", {"id": "e1", "_feed": "americanfootball_nfl"}, ["player_receptions"], "americanfootball_ncaaf")
    assert err is None and offers == [{"market": "player_receptions", "data": {"id": "e1"}}]
    assert seen == {"event_id": "e1", "key": "KEY", "markets": ["player_receptions"], "sport": "americanfootball_nfl"}   # the event's own feed wins

    def api_fail(*a, **k):
        raise O.OddsAPIError("quota used up")

    monkeypatch.setattr(O, "fetch_event_props", api_fail)
    assert PL.fetch_offers("KEY", {"id": "e1"}, ["m"], "s") == ([], "quota used up")

    def other_fail(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(O, "fetch_event_props", other_fail)
    assert PL.fetch_offers("KEY", {"id": "e1"}, ["m"], "s") == ([], "ValueError: boom")
