"""
test_capture_closing_lines.py — offline tests for capture_closing_lines.py's sport-aware logic.

No network, no database — odds_api/betlog/sports calls are monkeypatched. Focus is the actual bug
that was found and fixed: bets get grouped by sport and each sport's own odds_sport_key/market_map
are used, instead of everything silently going through MLB's.

    python test_capture_closing_lines.py    # or: pytest test_capture_closing_lines.py
"""

from datetime import datetime, timedelta, timezone

import capture_closing_lines as CCL
import odds_api as O
import sports


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------- not_started
def test_not_started_filters_to_future_events():
    now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    events = [
        {"id": "future", "commence_time": _iso(now + timedelta(hours=2))},
        {"id": "past", "commence_time": _iso(now - timedelta(hours=1))},
        {"id": "bad_date", "commence_time": "not-a-date"},
    ]
    live = CCL.not_started(events, now=now)
    assert [e["id"] for e in live] == ["future"]


# ----------------------------------------------------------------- capture_for_sport
def test_capture_for_sport_uses_that_sports_own_odds_key_and_market_map(monkeypatch):
    # The actual bug: this must NOT silently default to MLB's odds_sport_key/market_map.
    calls = {"fetch_events_sport": None, "fetch_props_sport": None, "parse_markets": None}

    def fake_fetch_events(api_key, sport=O.SPORT):
        calls["fetch_events_sport"] = sport
        return [{"id": "evt1", "commence_time": _iso(datetime.now(timezone.utc) + timedelta(hours=3))}]

    def fake_fetch_event_props(event_id, api_key, markets, regions="us", sport=O.SPORT):
        calls["fetch_props_sport"] = sport
        return {"bookmakers": []}, {}

    def fake_parse_event_offers(js, supported_markets=None):
        calls["parse_markets"] = supported_markets
        return []

    monkeypatch.setattr(O, "fetch_events", fake_fetch_events)
    monkeypatch.setattr(O, "fetch_event_props", fake_fetch_event_props)
    monkeypatch.setattr(O, "parse_event_offers", fake_parse_event_offers)

    wnba_bets = [{"id": 1, "market": "Points", "book": "fanduel", "side": "Over",
                 "line": 15.5, "player": "Star Player", "sport": "WNBA"}]
    CCL.capture_for_sport("WNBA", wnba_bets, "fake_key")

    assert calls["fetch_events_sport"] == "basketball_wnba"
    assert calls["fetch_props_sport"] == "basketball_wnba"
    assert calls["parse_markets"] == ["player_points"]
    print("✓ capture_for_sport uses WNBA's own odds_sport_key and market_map, not MLB's")


def test_capture_for_sport_no_recognizable_markets_skips_fetch(monkeypatch):
    # If a sport's bets use markets not in its market_map (shouldn't happen, but defensive),
    # no fetch should be attempted at all.
    called = {"fetch": False}
    monkeypatch.setattr(O, "fetch_events", lambda api_key, sport=O.SPORT: called.__setitem__("fetch", True) or [])
    bets = [{"id": 1, "market": "Not A Real Market", "book": "fanduel", "side": "Over", "sport": "WNBA"}]
    report = CCL.capture_for_sport("WNBA", bets, "fake_key")
    assert called["fetch"] is False
    assert report["no_match"] == [1]


# ----------------------------------------------------------------- main() sport grouping
def test_main_groups_open_bets_by_sport(monkeypatch):
    import betlog as B

    mlb_bet = {"id": 1, "sport": "MLB", "market": "Batter HR", "book": "fanduel", "side": "Over"}
    wnba_bet = {"id": 2, "sport": "WNBA", "market": "Points", "book": "fanduel", "side": "Over"}
    legacy_bet = {"id": 3, "market": "Batter HR", "book": "fanduel", "side": "Over"}   # no sport key -> MLB

    monkeypatch.setattr("os.environ", {"ODDS_API_KEY": "fake", "DATABASE_URL": "postgres://fake"})
    monkeypatch.setattr(B, "list_bets", lambda settled=None: [mlb_bet, wnba_bet, legacy_bet])
    monkeypatch.setattr(B, "update_bet", lambda *a, **k: None)

    seen_sports = []

    def fake_capture_for_sport(sport_key, sport_bets, api_key):
        seen_sports.append((sport_key, sorted(b["id"] for b in sport_bets)))
        return {"updates": {}, "no_book": [], "no_match": [], "events_checked": 0, "live_events": 0}

    monkeypatch.setattr(CCL, "capture_for_sport", fake_capture_for_sport)

    CCL.main()

    assert sorted(seen_sports) == [("MLB", [1, 3]), ("WNBA", [2])]
    print("✓ main() correctly groups open bets by sport (legacy no-sport rows default to MLB)")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}"); passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
