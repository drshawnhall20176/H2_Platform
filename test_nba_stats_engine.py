"""
test_nba_stats_engine.py — offline tests for nba_stats_engine.py (mocked requests, no network).

    python test_nba_stats_engine.py     # or: pytest test_nba_stats_engine.py
"""

from unittest.mock import patch

import nba_stats_engine as E


def _real_shaped_response():
    """A response matching the DOCUMENTED resultSets/GameHeader/LineScore shape -- the best real
    evidence available for what ScoreboardV3 should return (confirmed "100% backward compatible"
    with ScoreboardV2's own documented shape), used here to confirm the parsing LOGIC itself is
    internally correct. This is NOT a confirmed live capture -- see nba_stats_engine.py's own
    docstring for the honest reason why one isn't available yet."""
    return {
        "resultSets": [
            {"name": "GameHeader",
             "headers": ["GAME_DATE_EST", "GAME_ID", "GAME_STATUS_TEXT", "HOME_TEAM_ID", "VISITOR_TEAM_ID"],
             "rowSet": [["2026-08-05", "1022600123", "7:00 pm ET", 1611661319, 1611661320]]},
            {"name": "LineScore",
             "headers": ["GAME_ID", "TEAM_ID", "TEAM_CITY_NAME", "TEAM_NICKNAME", "TEAM_ABBREVIATION"],
             "rowSet": [
                 ["1022600123", 1611661319, "New York", "Liberty", "NYL"],
                 ["1022600123", 1611661320, "Seattle", "Storm", "SEA"],
             ]},
        ]
    }


def test_get_schedule_parses_the_documented_shape(monkeypatch):
    monkeypatch.setattr(E, "_get_json", lambda url, params: _real_shaped_response())
    games = E.get_schedule("2026-08-05", E.LEAGUE_ID_WNBA)
    assert len(games) == 1
    g = games[0]
    assert g["home_id"] == 1611661319 and g["away_id"] == 1611661320
    assert g["home_name"] == "New York Liberty" and g["away_name"] == "Seattle Storm"
    assert g["home_abbr"] == "NYL" and g["away_abbr"] == "SEA"
    assert g["game_date"] == "2026-08-05"
    assert g["home_logo"] is None and g["away_logo"] is None   # honest gap, not a guessed URL
    print("✓ get_schedule correctly parses the documented resultSets/GameHeader/LineScore shape")


def test_get_schedule_sends_the_real_expected_params(monkeypatch):
    captured = {}

    def fake_get_json(url, params):
        captured["url"] = url
        captured["params"] = params
        return _real_shaped_response()

    monkeypatch.setattr(E, "_get_json", fake_get_json)
    E.get_schedule("2026-08-05", E.LEAGUE_ID_WNBA)
    assert captured["url"] == "https://stats.nba.com/stats/scoreboardv3"
    assert captured["params"] == {"GameDate": "08/05/2026", "LeagueID": "10", "DayOffset": "0"}
    print("✓ get_schedule calls the real ScoreboardV3 endpoint with the correctly-formatted real date and league_id")


def test_get_schedule_returns_empty_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(E, "_get_json", lambda url, params: None)
    assert E.get_schedule("2026-08-05", E.LEAGUE_ID_WNBA) == []
    print("✓ get_schedule returns a real, honest empty list on a real fetch failure, never crashes")


def test_get_schedule_defensive_fallback_on_an_unexpected_real_shape(monkeypatch, caplog):
    # THE real, deliberate defensive case this module's own docstring is built around: if the
    # real, live response doesn't match the documented shape, this must not crash, and must log
    # real, actionable evidence (the actual top-level keys received) rather than fail silently.
    monkeypatch.setattr(E, "_get_json", lambda url, params: {"some_other_real_shape": True})
    with caplog.at_level("ERROR"):
        games = E.get_schedule("2026-08-05", E.LEAGUE_ID_WNBA)
    assert games == []
    assert any("real top-level keys were" in r.message for r in caplog.records), (
        "expected a real, diagnostic error log naming the actual unexpected keys received")
    print("✓ get_schedule fails soft (empty list) on an unexpected real shape, with a real diagnostic log naming the actual keys")


def test_get_schedule_skips_a_game_missing_one_side_of_line_score(monkeypatch):
    # A real GameHeader row with no matching real LineScore row for one side (a genuine partial-
    # data case) must be honestly skipped, not shown with a guessed/blank team.
    resp = {
        "resultSets": [
            {"name": "GameHeader",
             "headers": ["GAME_DATE_EST", "GAME_ID", "GAME_STATUS_TEXT", "HOME_TEAM_ID", "VISITOR_TEAM_ID"],
             "rowSet": [["2026-08-05", "1022600123", "7:00 pm ET", 1611661319, 1611661320]]},
            {"name": "LineScore",
             "headers": ["GAME_ID", "TEAM_ID", "TEAM_CITY_NAME", "TEAM_NICKNAME", "TEAM_ABBREVIATION"],
             "rowSet": [["1022600123", 1611661319, "New York", "Liberty", "NYL"]]},   # away side missing
        ]
    }
    monkeypatch.setattr(E, "_get_json", lambda url, params: resp)
    games = E.get_schedule("2026-08-05", E.LEAGUE_ID_WNBA)
    assert games == []
    print("✓ get_schedule honestly skips a game with a genuinely missing LineScore side, rather than guessing")


def test_league_id_constants_match_the_real_documented_values():
    # Real, confirmed values from py_ball's own documentation: '00' is NBA, '10' is WNBA.
    assert E.LEAGUE_ID_NBA == "00"
    assert E.LEAGUE_ID_WNBA == "10"
    print("✓ LEAGUE_ID_NBA/LEAGUE_ID_WNBA match the real, documented stats.nba.com values")


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
