"""
test_schedule_board.py — offline unit tests for schedule_board.py's grouping/sorting logic.

Deliberately does NOT test todays_schedule() end to end (that function makes real network calls
through each sport's own engine) -- tests group_games() directly with synthetic game dicts shaped
exactly like _mlb_games/_basketball_games/_ncaaf_games/_nfl_games actually build them, same
fixture-based convention every other test file in this project already uses.

    python test_schedule_board.py     # or: pytest test_schedule_board.py
"""

from datetime import datetime
from unittest.mock import patch

import pytz

import schedule_board as SB
import nfl_engine
import mlb_engine

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


# ----------------------------------------------------------------- NCAAMB (added directly on request)
def test_ncaamb_is_in_supported_sports():
    # Regression guard for the real, direct request this closes: NCAAMB used to be deliberately
    # excluded (see this module's own docstring for the real "no verified conference table"
    # reasoning) -- it's back in scope now, using the SAME honest "Other" bucket every sport
    # already falls back to when a team isn't in a real reference table, not a fabricated mapping.
    assert "NCAAMB" in SB.SUPPORTED_SPORTS
    print("✓ NCAAMB is in SUPPORTED_SPORTS, added directly on request")


def test_ncaamb_games_land_in_other_with_the_same_rich_rendering():
    # THE real point of this addition: NCAAMB gets the exact same visual treatment (colored box,
    # grid-aligned rows, status badges -- see components.todays_schedule_board) as every other
    # sport, honestly grouped under "Other" rather than fabricated conferences, since no
    # verified 350+-team Division I conference table exists on this platform yet.
    games = [{"home": "Duke", "away": "North Carolina", "dt": _dt(19), "time_known": True,
             "venue": None, "home_logo": None, "away_logo": None, "status": "scheduled",
             "home_lineup_confirmed": None, "away_lineup_confirmed": None}]
    result = SB.group_games("NCAAMB", games)
    assert result["grouped"] == {}   # no real conference table -- nothing lands in a named group
    assert len(result["other"]) == 1
    assert result["other"][0]["home"] == "Duke"
    assert result["has_divisions"] is False
    print("✓ NCAAMB games land in the real 'Other' bucket (no fabricated conference table), "
         "which already gets the exact same rich rendering as a real conference section")


def test_ncaamb_dispatches_through_basketball_games():
    # Confirms the real fetch dispatch actually reaches NCAAMB, not just that group_games alone
    # can handle NCAAMB-shaped rows if handed some by hand.
    from pathlib import Path
    src = Path(__file__).parent.joinpath("schedule_board.py").read_text()
    assert '_basketball_games(date_str, "ncaamb_engine")' in src, (
        "todays_schedule must actually dispatch NCAAMB through _basketball_games, not just list it in SUPPORTED_SPORTS")
    print("✓ todays_schedule genuinely dispatches NCAAMB through _basketball_games (same real fetch NBA/WNBA already use)")


def test_espn_cdn_logo_builds_expected_url():
    assert SB._espn_cdn_logo("nfl", "KC") == "https://a.espncdn.com/i/teamlogos/nfl/500/kc.png"
    assert SB._espn_cdn_logo("nba", "BOS") == "https://a.espncdn.com/i/teamlogos/nba/500/bos.png"
    print("✓ _espn_cdn_logo builds the confirmed ESPN CDN URL pattern, lowercased")


def test_espn_cdn_logo_none_safe():
    assert SB._espn_cdn_logo("nfl", None) is None
    assert SB._espn_cdn_logo("nfl", "") is None
    print("✓ _espn_cdn_logo returns None for a missing abbreviation, never crashes or guesses")


# ----------------------------------------------------------------- _categorize_status
def test_categorize_status_mlb_detailed_states():
    assert SB._categorize_status("Scheduled") == "scheduled"
    assert SB._categorize_status("Pre-Game") == "scheduled"
    assert SB._categorize_status("Warmup") == "scheduled"
    assert SB._categorize_status("In Progress") == "in-progress"
    assert SB._categorize_status("Final") == "finished"
    assert SB._categorize_status("Game Over") == "finished"
    assert SB._categorize_status("Postponed") == "delayed"
    assert SB._categorize_status("Delayed Start") == "delayed"
    assert SB._categorize_status("Delayed: Rain") == "delayed"
    assert SB._categorize_status("Suspended") == "delayed"
    assert SB._categorize_status("Cancelled") == "canceled"
    print("✓ _categorize_status correctly maps every real MLB detailedState value seen in this "
         "codebase to one of the 5 categories")


def test_categorize_status_espn_state_fallback():
    # No specific text, only ESPN's coarse pre/in/post state -- the fallback path.
    assert SB._categorize_status(None, "pre") == "scheduled"
    assert SB._categorize_status(None, "in") == "in-progress"
    assert SB._categorize_status(None, "post") == "finished"
    print("✓ _categorize_status falls back to ESPN's coarse state when there's no more specific text")


def test_categorize_status_text_overrides_state():
    # Regression guard for the real, stated reason text is checked FIRST: a rain delay mid-game
    # can leave ESPN's own state at "in" while the description says "Delayed".
    assert SB._categorize_status("Delayed", "in") == "delayed"
    assert SB._categorize_status("Postponed", "pre") == "delayed"
    print("✓ specific status text overrides the coarse pre/in/post state when they disagree")


def test_categorize_status_unknown_defaults_to_scheduled_not_crash():
    assert SB._categorize_status(None, None) == "scheduled"
    assert SB._categorize_status("", "") == "scheduled"
    assert SB._categorize_status("Some Unrecognized Future Status") == "scheduled"
    print("✓ _categorize_status never crashes on missing/unrecognized input, defaults honestly "
         "to scheduled")


def test_todays_schedule_returns_none_for_unsupported_sport():
    # UFC is the one remaining, deliberate exclusion -- individual bouts, not team matchups,
    # already served by its own UFC Fight Card page. NCAAMB is NOT tested here anymore: it was
    # excluded before, added directly on request (see this module's own docstring for the real
    # reasoning), and now has its own dedicated tests below confirming it actually works.
    assert SB.todays_schedule("UFC", "2026-08-01") is None
    print("✓ todays_schedule returns None for UFC (individual bouts, not team matchups -- "
         "UFC Fight Card already IS its own schedule) -- the caller's signal to simply not "
         "render the section")


# ----------------------------------------------------------------- per-sport status/lineup wiring
def test_mlb_games_wires_real_status_and_lineup_confirmation(monkeypatch):
    import mlb_engine as E
    fake_schedule = [{
        "gamePk": 12345, "gameNumber": 1, "game_date": "2026-08-01T23:10:00Z",
        "status": "In Progress", "venue_name": "Yankee Stadium", "venue_id": 1,
        "home_name": "New York Yankees", "away_name": "Boston Red Sox",
        "home_id": 147, "away_id": 111, "home_pitcher_id": None, "away_pitcher_id": None,
        "home_score": None, "away_score": None,
    }]
    monkeypatch.setattr(E, "get_schedule", lambda date_str: fake_schedule)
    monkeypatch.setattr(E, "get_lineup_status", lambda game_pk, home_id, away_id: (True, False))

    games = SB._mlb_games("2026-08-01")
    assert len(games) == 1
    g = games[0]
    assert g["status"] == "in-progress"
    assert g["home_lineup_confirmed"] is True
    assert g["away_lineup_confirmed"] is False
    print("✓ _mlb_games wires real status and independently-decided lineup confirmation per side")


def test_nfl_games_status_finished_only_when_both_scores_present(monkeypatch):
    import nfl_engine as E
    fake_schedule = [
        {"game_id": "g1", "week": 1, "game_date": "2026-09-08", "home_team": "KC", "away_team": "BUF",
         "home_score": 24, "away_score": 20, "home_rest": 7, "away_rest": 7},
        {"game_id": "g2", "week": 1, "game_date": "2026-09-08", "home_team": "SF", "away_team": "SEA",
         "home_score": None, "away_score": None, "home_rest": 7, "away_rest": 7},
    ]
    monkeypatch.setattr(E, "get_schedule", lambda season: fake_schedule)
    monkeypatch.setattr(E, "_infer_season", lambda date_str: 2026)
    monkeypatch.setattr(E, "_resolve_week", lambda schedule, date_str: 1)

    games = SB._nfl_games("2026-09-08")
    by_home = {g["home"]: g for g in games}
    assert by_home["KC"]["status"] == "finished"
    assert by_home["SF"]["status"] == "scheduled"
    print("✓ NFL games only report 'finished' when a real final score is present, 'scheduled' "
         "otherwise -- never a fabricated in-progress/delayed")


def test_ncaaf_games_status_uses_real_completed_field(monkeypatch):
    import ncaaf_engine as E
    fake_schedule = [
        {"id": 1, "week": 1, "start_date": "2026-08-30T19:00:00Z", "start_time_tbd": False,
         "completed": True, "venue": "Sanford Stadium", "home_team": "Georgia",
         "home_conference": "SEC", "away_team": "Alabama", "away_conference": "SEC"},
        {"id": 2, "week": 1, "start_date": "2026-08-30T23:00:00Z", "start_time_tbd": False,
         "completed": False, "venue": None, "home_team": "Ohio State",
         "home_conference": "Big Ten", "away_team": "Michigan", "away_conference": "Big Ten"},
    ]
    monkeypatch.setattr(E, "get_schedule", lambda season: fake_schedule)
    monkeypatch.setattr(E, "_infer_season", lambda date_str: 2026)
    monkeypatch.setattr(E, "_resolve_week", lambda schedule, date_str: 1)
    monkeypatch.setattr(E, "games_for_week", lambda schedule, week: schedule)

    games = SB._ncaaf_games_with_conference("2026-08-30")
    by_home = {g["home"]: g for g in games}
    assert by_home["Georgia"]["status"] == "finished"
    assert by_home["Ohio State"]["status"] == "scheduled"
    print("✓ NCAAF games use CFBD's own real 'completed' field for status, not a guess")


# ----------------------------------------------------------------- next_scheduled_date
def test_next_scheduled_date_nfl_scans_the_already_fetched_full_season():
    fake_schedule = [
        {"game_date": "2026-08-06", "home_team": "ARI", "away_team": "CAR"},
        {"game_date": "2026-08-13", "home_team": "CIN", "away_team": "DET"},
        {"game_date": "2026-08-13", "home_team": "PIT", "away_team": "GB"},
    ]
    with patch.object(nfl_engine, "_infer_season", return_value=2026), \
         patch.object(nfl_engine, "get_schedule", return_value=fake_schedule):
        result = SB.next_scheduled_date("NFL", "2026-08-05")
    assert result == "2026-08-06"
    print("✓ next_scheduled_date correctly finds the real next NFL date from the already-fetched season")


def test_next_scheduled_date_nfl_none_when_nothing_real_is_later_in_the_loaded_season():
    fake_schedule = [{"game_date": "2026-08-01", "home_team": "ARI", "away_team": "CAR"}]
    with patch.object(nfl_engine, "_infer_season", return_value=2026), \
         patch.object(nfl_engine, "get_schedule", return_value=fake_schedule):
        result = SB.next_scheduled_date("NFL", "2026-08-05")
    assert result is None
    print("✓ next_scheduled_date honestly returns None when nothing real is later in the currently loaded season")


def test_next_scheduled_date_mlb_scans_day_by_day_using_the_raw_lightweight_fetch():
    calls = []
    def fake_get_schedule(date_str):
        calls.append(date_str)
        return [{"game_id": 1}] if date_str == "2026-08-08" else []
    with patch.object(mlb_engine, "get_schedule", side_effect=fake_get_schedule):
        result = SB.next_scheduled_date("MLB", "2026-08-05")
    assert result == "2026-08-08"
    assert calls == ["2026-08-06", "2026-08-07", "2026-08-08"], (
        f"expected a real day-by-day scan stopping at the first real hit, got {calls}")
    print("✓ next_scheduled_date scans MLB day by day using the raw, lightweight get_schedule, stopping at the first real hit")


def test_next_scheduled_date_mlb_none_beyond_the_real_cap():
    with patch.object(mlb_engine, "get_schedule", return_value=[]):
        result = SB.next_scheduled_date("MLB", "2026-08-05", max_days_ahead=5)
    assert result is None
    print("✓ next_scheduled_date honestly gives up after max_days_ahead real days, rather than scanning forever")


def test_next_scheduled_date_returns_none_for_unsupported_sport():
    assert SB.next_scheduled_date("UFC", "2026-08-05") is None
    print("✓ next_scheduled_date returns None for a sport outside SUPPORTED_SPORTS, same as todays_schedule")


def test_next_scheduled_date_fails_soft_on_a_real_fetch_error():
    with patch.object(mlb_engine, "get_schedule", side_effect=RuntimeError("real API down")):
        result = SB.next_scheduled_date("MLB", "2026-08-05")
    assert result is None
    print("✓ next_scheduled_date fails soft (honest None) on a real fetch error, never crashes the page")


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
