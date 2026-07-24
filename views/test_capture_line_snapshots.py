"""
test_capture_line_snapshots.py — offline tests for capture_line_snapshots.py.

No network, no real database — odds_api/line_history/sports calls are monkeypatched, and
line_history.record_snapshot is tested for real against a temp SQLite file (not mocked out), so
these tests exercise the actual de-duplication logic end to end, not just the wiring around it.

    python test_capture_line_snapshots.py    # or: pytest test_capture_line_snapshots.py
"""

import os
import tempfile
from datetime import datetime, timedelta, timezone

import capture_line_snapshots as CLS
import odds_api as O
import line_history as LH
import sports


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------- capture_for_sport
def test_capture_for_sport_uses_that_sports_own_odds_key_and_markets(monkeypatch):
    # Same class of bug capture_closing_lines.py's own tests guard against: this must NOT
    # silently default to MLB's odds_sport_key/markets.
    calls = {"fetch_events_sport": None, "fetch_props_sport": None, "fetch_props_markets": None}

    def fake_fetch_events(api_key, sport=O.SPORT):
        calls["fetch_events_sport"] = sport
        return [{"id": "evt1", "commence_time": _iso(datetime.now(timezone.utc) + timedelta(hours=3)),
                "home_team": "Team B", "away_team": "Team A"}]

    def fake_fetch_event_props(event_id, api_key, markets, regions="us", sport=O.SPORT):
        calls["fetch_props_sport"] = sport
        calls["fetch_props_markets"] = markets
        return {"bookmakers": []}, {}

    monkeypatch.setattr(O, "fetch_events", fake_fetch_events)
    monkeypatch.setattr(O, "fetch_event_props", fake_fetch_event_props)

    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(LH, "DB_PATH", os.path.join(tmp, "line_history.db"))
        CLS.capture_for_sport("WNBA", "fake_key")

    assert calls["fetch_events_sport"] == "basketball_wnba"
    assert calls["fetch_props_sport"] == "basketball_wnba"
    assert calls["fetch_props_markets"] == sports.get("WNBA").markets
    print("✓ capture_for_sport uses WNBA's own odds_sport_key and full markets list, not MLB's")


def test_capture_for_sport_no_markets_skips_fetch(monkeypatch):
    called = {"fetch": False}
    monkeypatch.setattr(O, "fetch_events", lambda api_key, sport=O.SPORT: called.__setitem__("fetch", True) or [])
    report = CLS.capture_for_sport("NCAAF", "fake_key")   # placeholder sport, empty markets
    assert called["fetch"] is False
    assert report == {"events_checked": 0, "live_events": 0, "offers_seen": 0, "snapshots_recorded": 0}
    print("✓ capture_for_sport skips the fetch entirely for a sport with no markets configured yet")


def test_capture_for_sport_records_real_offers_and_builds_game_label(monkeypatch):
    fake_events = [{"id": "evt1", "commence_time": _iso(datetime.now(timezone.utc) + timedelta(hours=3)),
                    "home_team": "Lynx", "away_team": "Aces"}]
    fake_offers_json = {"bookmakers": [
        {"key": "fanduel", "markets": [
            {"key": "player_points", "outcomes": [
                {"description": "Star Player", "name": "Over", "point": 15.5, "price": -110},
                {"description": "Star Player", "name": "Under", "point": 15.5, "price": -110},
            ]},
        ]},
    ]}
    monkeypatch.setattr(O, "fetch_events", lambda api_key, sport=O.SPORT: fake_events)
    monkeypatch.setattr(O, "fetch_event_props",
                        lambda event_id, api_key, markets, regions="us", sport=O.SPORT: (fake_offers_json, {}))

    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(LH, "DB_PATH", os.path.join(tmp, "line_history.db"))
        report = CLS.capture_for_sport("WNBA", "fake_key")
        series = LH.line_series("WNBA", "Star Player", "player_points")

    assert report["offers_seen"] == 2         # over + under
    assert report["snapshots_recorded"] == 2   # both new -> both written
    assert len(series) == 2
    assert series[0]["game"] == "Aces @ Lynx"   # away @ home, built from the event's own team names
    print("✓ capture_for_sport records real offers with a correctly-built game label")


def test_capture_for_sport_second_run_with_unchanged_lines_records_nothing_new(monkeypatch):
    # Exercises the actual de-duplication end to end: running capture_for_sport TWICE with
    # identical offers should record snapshots the first time, and correctly record NOTHING new
    # the second time — the whole point of line_history.py's de-dup logic, at the integration level.
    fake_events = [{"id": "evt1", "commence_time": _iso(datetime.now(timezone.utc) + timedelta(hours=3)),
                    "home_team": "Lynx", "away_team": "Aces"}]
    fake_offers_json = {"bookmakers": [
        {"key": "fanduel", "markets": [
            {"key": "player_points", "outcomes": [
                {"description": "Star Player", "name": "Over", "point": 15.5, "price": -110},
            ]},
        ]},
    ]}
    monkeypatch.setattr(O, "fetch_events", lambda api_key, sport=O.SPORT: fake_events)
    monkeypatch.setattr(O, "fetch_event_props",
                        lambda event_id, api_key, markets, regions="us", sport=O.SPORT: (fake_offers_json, {}))

    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(LH, "DB_PATH", os.path.join(tmp, "line_history.db"))
        first = CLS.capture_for_sport("WNBA", "fake_key")
        second = CLS.capture_for_sport("WNBA", "fake_key")

    assert first["snapshots_recorded"] == 1
    assert second["snapshots_recorded"] == 0   # same line/price -> correctly skipped, not re-recorded
    assert second["offers_seen"] == 1          # still SAW the offer, just didn't need to store it again
    print("✓ a second capture with unchanged lines correctly records zero new snapshots")


# ----------------------------------------------------------------- main()
def test_main_captures_every_enabled_sport(monkeypatch):
    # Genuinely different from capture_closing_lines.py's main(): that one only processes sports
    # with OPEN BETS. This one processes every ENABLED sport regardless of whether anyone has bet
    # anything — it's tracking the whole market, not just your own positions.
    monkeypatch.setattr("os.environ", {"ODDS_API_KEY": "fake", "DATABASE_URL": "postgres://fake"})

    seen_sports = []

    def fake_capture_for_sport(sport_key, api_key):
        seen_sports.append(sport_key)
        return {"events_checked": 0, "live_events": 0, "offers_seen": 0, "snapshots_recorded": 0}

    monkeypatch.setattr(CLS, "capture_for_sport", fake_capture_for_sport)
    CLS.main()

    assert set(seen_sports) == {s.key for s in sports.enabled_sports()}
    print("✓ main() captures every enabled sport, not just sports with open bets")


def test_main_refuses_without_odds_api_key(monkeypatch):
    monkeypatch.setattr("os.environ", {})
    assert CLS.main() == 1


def test_main_refuses_without_database_url(monkeypatch):
    monkeypatch.setattr("os.environ", {"ODDS_API_KEY": "fake"})
    monkeypatch.setattr(LH, "USING_POSTGRES", False)
    assert CLS.main() == 1


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
