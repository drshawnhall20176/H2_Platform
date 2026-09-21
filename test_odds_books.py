"""
test_odds_books.py — the expanded book list (Hard Rock Bet, PrizePicks, DK Pick6, Bet365) in odds_api.

Offline: the network call (odds_api._get) is monkeypatched, and the live PrizePicks/Pick6 response
shape is exercised through fixtures because The Odds API isn't reachable from the build sandbox.
"""

import pytest

import odds_api as O
import projections as P


@pytest.fixture(autouse=True)
def _reset_rejections():
    O._BOOKMAKERS_REJECTED.update({"multipliers": False, "bookmakers": False})
    yield
    O._BOOKMAKERS_REJECTED.update({"multipliers": False, "bookmakers": False})


# --------------------------------------------------------------------------- registry
def test_all_requested_books_are_selectable():
    assert O.ALL_BOOKS["hardrockbet"] == "Hard Rock Bet"
    assert O.ALL_BOOKS["prizepicks"] == "PrizePicks"
    assert O.ALL_BOOKS["pick6"] == "DK Pick6"
    assert O.ALL_BOOKS["bet365"] == "Bet365"


def test_book_groups_do_not_overlap():
    assert not (set(O.US_BOOKS) & set(O.PICKEM_BOOKS))
    assert not (set(O.US_BOOKS) & set(O.MANUAL_BOOKS))
    assert not (set(O.PICKEM_BOOKS) & set(O.MANUAL_BOOKS))
    assert list(O.ALL_BOOKS) == list(O.US_BOOKS) + list(O.PICKEM_BOOKS) + list(O.MANUAL_BOOKS)


def test_fetch_list_stays_within_one_region_of_credits():
    """The API bills every 10 bookmakers as one region: the fetch list must stay <= 10 or every
    props call silently costs twice what the old regions='us' request did."""
    assert len(O.FETCH_BOOKMAKERS) <= 10
    assert "bet365" not in O.FETCH_BOOKMAKERS          # manual-only, no US prop feed
    assert {"hardrockbet", "prizepicks", "pick6"} <= set(O.FETCH_BOOKMAKERS)


def test_caesars_uses_the_key_the_api_actually_returns():
    assert "caesars" not in O.US_BOOKS
    assert O.US_BOOKS["williamhill_us"] == "Caesars"
    assert O.canonical_book("caesars") == "williamhill_us"
    assert O.canonical_book("  DraftKings ") == "draftkings"
    assert O.canonical_book(None) == ""


def test_book_kind_predicates():
    assert O.is_pickem_book("prizepicks") and O.is_pickem_book("pick6")
    assert not O.is_pickem_book("draftkings")
    assert O.is_manual_book("bet365") and not O.is_manual_book("prizepicks")
    assert O.book_label("prizepicks") == "PrizePicks"


# --------------------------------------------------------------------------- parsing
def _event(*bookmakers):
    return {"bookmakers": list(bookmakers)}


def _bm(key, market, outcomes):
    return {"key": key, "markets": [{"key": market, "outcomes": outcomes}]}


def _oc(name, player, point, price=None, **extra):
    d = {"name": name, "description": player, "point": point}
    if price is not None:
        d["price"] = price
    d.update(extra)
    return d


def test_sportsbook_and_pickem_land_in_separate_slots():
    ev = _event(
        _bm("draftkings", "player_points", [_oc("Over", "A Guy", 20.5, -115), _oc("Under", "A Guy", 20.5, -105)]),
        _bm("prizepicks", "player_points", [_oc("Over", "A Guy", 20.5, 100, multiplier=1.0),
                                            _oc("Under", "A Guy", 20.5, 100)]),
    )
    (off,) = O.parse_event_offers(ev, ["player_points"])
    assert off["over"] == {"draftkings": -115} and off["under"] == {"draftkings": -105}
    assert set(off["pickem"]) == {"prizepicks"}
    assert off["pickem"]["prizepicks"]["over"] == {"price": 100, "multiplier": 1.0}
    assert off["pickem"]["prizepicks"]["under"] == {"price": 100}


def test_pickem_price_never_pollutes_devig_or_best_price():
    ev = _event(
        _bm("draftkings", "player_points", [_oc("Over", "A Guy", 20.5, -110), _oc("Under", "A Guy", 20.5, -110)]),
        _bm("prizepicks", "player_points", [_oc("Over", "A Guy", 20.5, 900), _oc("Under", "A Guy", 20.5, 900)]),
    )
    (off,) = O.parse_event_offers(ev, ["player_points"])
    assert "prizepicks" not in off["over"] and "prizepicks" not in off["under"]
    assert O.devig_two_way(off["over"]["draftkings"], off["under"]["draftkings"]) == 0.5


def test_pickem_outcomes_without_a_price_are_kept_and_more_less_are_understood():
    ev = _event(_bm("pick6", "player_points", [_oc("More", "A Guy", 18.5), _oc("Less", "A Guy", 18.5)]))
    (off,) = O.parse_event_offers(ev, ["player_points"])
    assert off["over"] == {} and off["under"] == {}
    assert set(off["pickem"]["pick6"]) == {"over", "under"}
    assert off["pickem"]["pick6"]["over"] == {"price": None}


def test_sportsbook_outcome_without_a_price_is_still_dropped():
    ev = _event(_bm("draftkings", "player_points", [_oc("Over", "A Guy", 20.5)]))
    assert O.parse_event_offers(ev, ["player_points"]) == []


def test_pickem_outcome_missing_player_or_point_or_side_is_skipped():
    ev = _event(_bm("prizepicks", "player_points", [
        {"name": "Over", "point": 5.5}, {"name": "Over", "description": "X"},
        _oc("Push", "X", 5.5)]))
    assert O.parse_event_offers(ev, ["player_points"]) == []


def test_legacy_caesars_key_in_a_response_is_canonicalized():
    ev = _event(_bm("caesars", "player_points", [_oc("Over", "A Guy", 20.5, -110), _oc("Under", "A Guy", 20.5, -110)]))
    (off,) = O.parse_event_offers(ev, ["player_points"])
    assert "williamhill_us" in off["over"]


def test_hard_rock_is_a_normal_sportsbook_in_offers():
    ev = _event(_bm("hardrockbet", "player_points", [_oc("Over", "A Guy", 20.5, -125), _oc("Under", "A Guy", 20.5, 105)]))
    (off,) = O.parse_event_offers(ev, ["player_points"])
    assert off["over"]["hardrockbet"] == -125
    assert O.books_in_offers([off]) == ["hardrockbet"]


def test_books_in_offers_lists_pickem_after_sportsbooks_in_display_order():
    offers = [{"over": {"fanduel": -110, "draftkings": -110}, "under": {"draftkings": -110},
               "pickem": {"pick6": {}, "prizepicks": {}}}]
    assert O.books_in_offers(offers) == ["draftkings", "fanduel", "prizepicks", "pick6"]


# --------------------------------------------------------------------------- lines & edges
def _offer(point, over=None, under=None, pickem=None):
    off = {"market": "player_points", "player": "A Guy", "point": point,
           "over": over or {}, "under": under or {}}
    if pickem:
        off["pickem"] = pickem
    return off


def test_market_lines_prefers_a_pickem_books_own_line():
    offers = [_offer(20.5, {"draftkings": -110}, {"draftkings": -110}),
              _offer(19.5, pickem={"prizepicks": {"over": {"price": None}}})]
    key = (P.normalize_name("A Guy"), "player_points")
    assert O.market_lines_for_slate(offers, preferred_book="prizepicks")[key] == 19.5
    # ... and a pick'em-only point never becomes the sportsbook fallback
    assert O.market_lines_for_slate(offers, preferred_book="draftkings")[key] == 20.5
    assert O.market_lines_for_slate(offers, preferred_book=None)[key] == 20.5


def test_market_lines_accepts_the_legacy_caesars_spelling():
    offers = [_offer(20.5, {"williamhill_us": -110, "draftkings": -110}, {"williamhill_us": -110}),
              _offer(21.5, {"draftkings": -110}, {"draftkings": -110})]
    key = (P.normalize_name("A Guy"), "player_points")
    assert O.market_lines_for_slate(offers, preferred_book="caesars")[key] == 20.5


def test_compute_edges_skips_pickem_only_offers():
    offers = [_offer(19.5, pickem={"prizepicks": {"over": {"price": None}}})]
    rows, stats = O.compute_edges({}, offers)
    assert rows == [] and stats["unmatched"] == 0 and stats["matched"] == 0


# --------------------------------------------------------------------------- fetch fallback chain
class _Recorder:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, path, params):
        self.calls.append(dict(params))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r, {"remaining": "1", "used": "1"}


def test_default_fetch_asks_for_every_book_and_multipliers(monkeypatch):
    rec = _Recorder([{"ok": 1}])
    monkeypatch.setattr(O, "_get", rec)
    O.fetch_event_props("evt", "KEY", ["player_points"])
    (params,) = rec.calls
    assert params["bookmakers"] == ",".join(O.FETCH_BOOKMAKERS)
    assert params["includeMultipliers"] == "true" and "regions" not in params


def test_fetch_retries_without_multipliers_then_without_bookmakers_and_remembers(monkeypatch):
    rec = _Recorder([O.OddsAPIError("HTTP 422: bad param"), O.OddsAPIError("HTTP 422: bad param"), {"ok": 1}])
    monkeypatch.setattr(O, "_get", rec)
    out, _ = O.fetch_event_props("evt", "KEY", ["player_points"])
    assert out == {"ok": 1}
    assert "includeMultipliers" in rec.calls[0]
    assert "includeMultipliers" not in rec.calls[1] and "bookmakers" in rec.calls[1]
    assert rec.calls[2]["regions"] == "us" and "bookmakers" not in rec.calls[2]
    assert O._BOOKMAKERS_REJECTED == {"multipliers": True, "bookmakers": True}
    # remembered: the next call goes straight to the plain regions request
    rec2 = _Recorder([{"ok": 2}])
    monkeypatch.setattr(O, "_get", rec2)
    O.fetch_event_props("evt2", "KEY", ["player_points"])
    assert len(rec2.calls) == 1 and rec2.calls[0]["regions"] == "us"


@pytest.mark.parametrize("msg", ["401 Unauthorized — check your API key.", "429 — out of quota for this period."])
def test_auth_and_quota_errors_are_not_retried(monkeypatch, msg):
    rec = _Recorder([O.OddsAPIError(msg)])
    monkeypatch.setattr(O, "_get", rec)
    with pytest.raises(O.OddsAPIError):
        O.fetch_event_props("evt", "KEY", ["player_points"])
    assert len(rec.calls) == 1
    assert O._BOOKMAKERS_REJECTED == {"multipliers": False, "bookmakers": False}


def test_explicit_regions_or_bookmakers_are_sent_exactly_as_given(monkeypatch):
    rec = _Recorder([{}, {}])
    monkeypatch.setattr(O, "_get", rec)
    O.fetch_event_props("e", "K", ["m"], regions="eu")
    O.fetch_event_props("e", "K", ["m"], bookmakers=["fanduel"])
    assert rec.calls[0]["regions"] == "eu" and "bookmakers" not in rec.calls[0]
    assert rec.calls[1]["bookmakers"] == "fanduel" and "regions" not in rec.calls[1]


def test_clv_capture_resolves_the_legacy_caesars_book():
    import clv_capture
    offers = [{"market": "player_points", "player": "A Guy", "point": 20.5,
               "over": {"williamhill_us": -118}, "under": {"williamhill_us": -102}}]
    bet = {"market": "Points", "player": "A Guy", "line": 20.5, "side": "Over", "book": "caesars"}
    assert clv_capture.bet_close_price(bet, offers, market_map={"Points": "player_points"}) == -118
    bet["book"] = "hardrockbet"      # a book with no posted price for this offer -> no match, not a crash
    assert clv_capture.bet_close_price(bet, offers, market_map={"Points": "player_points"}) is None
