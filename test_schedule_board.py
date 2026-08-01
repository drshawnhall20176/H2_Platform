"""
test_schedule_board.py — offline unit tests for schedule_board.py's grouping/sorting logic.

Deliberately does NOT test todays_schedule() end to end (that function makes real network calls
through each sport's own engine) -- tests group_games() directly with synthetic game dicts shaped
exactly like _mlb_games/_basketball_games/_ncaaf_games/_nfl_games actually build them, same
fixture-based convention every other test file in this project already uses.

    python test_schedule_board.py     # or: pytest test_schedule_board.py
"""

from datetime import datetime

import pytz

import schedule_board as SB

_ET = pytz.timezone("US/Eastern")


def _dt(hour, minute=0):
    return _ET.localize(datetime(2026, 8, 1, hour, minute))


def test_mlb_games_grouped_by_league_and_division():
    games = [
        {"home": "New York Yankees", "away": "Boston Red Sox", "dt": _dt(19), "time_known": True, "venue": None},
        {"home": "Los Angeles Dodgers", "away": "San Diego Padres", "dt": _dt(22), "time_known": True, "venue": None},
    ]
    result = SB.group_games("MLB", games)
    assert result["has_divisions"] is True
    assert result["other"] == []
    assert "AL" in result["grouped"] and "East" in result["grouped"]["AL"]
    assert "NL" in result["grouped"] and "West" in result["grouped"]["NL"]
    assert result["grouped"]["AL"]["East"][0]["home"] == "New York Yankees"
    print("✓ MLB games group correctly by league then division")


def test_games_sorted_chronologically_within_a_group():
    # Same division (AL East) on purpose -- confirms real chronological sort, not fetch order.
    games = [
        {"home": "New York Yankees", "away": "Boston Red Sox", "dt": _dt(22), "time_known": True, "venue": None},
        {"home": "Baltimore Orioles", "away": "Tampa Bay Rays", "dt": _dt(13), "time_known": True, "venue": None},
        {"home": "Toronto Blue Jays", "away": "Boston Red Sox", "dt": _dt(19), "time_known": True, "venue": None},
    ]
    result = SB.group_games("MLB", games)
    order = [g["home"] for g in result["grouped"]["AL"]["East"]]
    assert order == ["Baltimore Orioles", "Toronto Blue Jays", "New York Yankees"]
    print("✓ Games within a group sort chronologically by real start time, earliest first")


def test_unmapped_team_falls_into_other_not_dropped():
    # FAILS SAFE, per league_structure.py's own stated contract -- a team not in the table must
    # never silently disappear from the schedule.
    games = [{"home": "Some Future Expansion Team", "away": "New York Yankees",
             "dt": _dt(19), "time_known": True, "venue": None}]
    result = SB.group_games("MLB", games)
    assert result["grouped"] == {}
    assert len(result["other"]) == 1
    assert result["other"][0]["home"] == "Some Future Expansion Team"
    print("✓ An unmapped home team lands in 'other', never silently dropped")


def test_nba_games_grouped_with_la_clippers_naming_quirk():
    # Regression guard for the one real naming quirk league_structure.py's own docstring flags --
    # ESPN's displayName is "LA Clippers", not "Los Angeles Clippers".
    games = [{"home": "LA Clippers", "away": "Boston Celtics", "dt": _dt(22), "time_known": True, "venue": None}]
    result = SB.group_games("NBA", games)
    assert result["other"] == []
    assert result["grouped"]["Western"]["Pacific"][0]["home"] == "LA Clippers"
    print("✓ 'LA Clippers' (ESPN's real naming) resolves correctly, not silently unmapped")


def test_wnba_has_no_division_level():
    games = [{"home": "Las Vegas Aces", "away": "Chicago Sky", "dt": _dt(22), "time_known": True, "venue": None}]
    result = SB.group_games("WNBA", games)
    assert result["has_divisions"] is False
    assert result["grouped"]["West"][None][0]["home"] == "Las Vegas Aces"
    print("✓ WNBA groups by conference only, no division sub-level (matches real WNBA structure)")


def test_nfl_games_grouped_by_conference_and_division():
    games = [{"home": "KC", "away": "BUF", "dt": None, "time_known": False, "venue": None}]
    result = SB.group_games("NFL", games)
    assert result["has_divisions"] is True
    assert result["grouped"]["AFC"]["West"][0]["home"] == "KC"
    print("✓ NFL games group correctly by conference then division, even with no known kickoff time")


def test_games_with_unknown_time_sort_after_known_times():
    # NFL-shaped: dt=None (time not known). Must not crash comparing None to a real datetime,
    # and must land after every game whose real time IS known within the same group.
    games = [
        {"home": "KC", "away": "BUF", "dt": None, "time_known": False, "venue": None},
        {"home": "LV", "away": "DEN", "dt": _dt(16), "time_known": True, "venue": None},
    ]
    result = SB.group_games("NFL", games)
    order = [g["home"] for g in result["grouped"]["AFC"]["West"]]
    assert order == ["LV", "KC"]
    print("✓ Games with an unknown start time sort after games with a known one, no crash")


def test_ncaaf_groups_by_conference_directly_from_the_game_row():
    # NCAAF is the one sport with no lookup table at all -- conference comes straight off the
    # game row (_home_conference), confirming that path actually works end to end.
    games = [{"home": "Georgia", "away": "Alabama", "dt": _dt(15, 30), "time_known": True,
             "venue": "Sanford Stadium", "_home_conference": "SEC"}]
    result = SB.group_games("NCAAF", games)
    assert result["has_divisions"] is False
    assert result["grouped"]["SEC"][None][0]["home"] == "Georgia"
    print("✓ NCAAF groups by conference read directly off the schedule row, no lookup table needed")


def test_ncaaf_game_with_no_conference_on_row_falls_into_other():
    games = [{"home": "Some FCS Team", "away": "Georgia", "dt": _dt(15, 30), "time_known": True,
             "venue": None, "_home_conference": None}]
    result = SB.group_games("NCAAF", games)
    assert result["grouped"] == {}
    assert len(result["other"]) == 1
    print("✓ An NCAAF game with no conference on its own row falls into 'other', not dropped")


def test_espn_cdn_logo_builds_expected_url():
    assert SB._espn_cdn_logo("nfl", "KC") == "https://a.espncdn.com/i/teamlogos/nfl/500/kc.png"
    assert SB._espn_cdn_logo("nba", "BOS") == "https://a.espncdn.com/i/teamlogos/nba/500/bos.png"
    print("✓ _espn_cdn_logo builds the confirmed ESPN CDN URL pattern, lowercased")


def test_espn_cdn_logo_none_safe():
    assert SB._espn_cdn_logo("nfl", None) is None
    assert SB._espn_cdn_logo("nfl", "") is None
    print("✓ _espn_cdn_logo returns None for a missing abbreviation, never crashes or guesses")


def test_todays_schedule_returns_none_for_unsupported_sport():
    assert SB.todays_schedule("NCAAMB", "2026-08-01") is None
    assert SB.todays_schedule("UFC", "2026-08-01") is None
    print("✓ todays_schedule returns None for sports outside SUPPORTED_SPORTS (NCAAMB, UFC) -- "
         "the caller's signal to simply not render the section")


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
