"""
test_nfl_shared_cache.py — offline tests for nfl_shared_cache.py.

    python test_nfl_shared_cache.py     # or: pytest test_nfl_shared_cache.py
"""

from unittest.mock import patch

import nfl_shared_cache as NSC


def test_load_nfl_slate_cached_wraps_build_slate():
    fake_result = ([{"Player": "Test QB"}], [{"label": "Team A @ Team B"}])
    with patch.object(NSC.E, "build_slate", return_value=fake_result) as mock_build:
        result = NSC.load_nfl_slate_cached.__wrapped__("2026-09-08")
    mock_build.assert_called_once_with("2026-09-08", stats_date_str=None)
    assert result == fake_result
    print("✓ load_nfl_slate_cached correctly wraps nfl_engine.build_slate with date and stats_date_str passed through")


def test_load_nfl_slate_cached_is_genuinely_cached():
    assert hasattr(NSC.load_nfl_slate_cached, "__wrapped__"), (
        "load_nfl_slate_cached must genuinely be decorated by st.cache_data, not a plain, uncached function")
    print("✓ load_nfl_slate_cached is genuinely decorated by st.cache_data, not accidentally uncached")


def test_resolve_nfl_week_cached_wraps_the_real_chain():
    fake_schedule = [{"game_id": "1"}]
    with patch.object(NSC.E, "_infer_season", return_value=2026) as mock_infer, \
         patch.object(NSC.E, "get_schedule", return_value=fake_schedule) as mock_sched, \
         patch.object(NSC.E, "_resolve_week", return_value=5) as mock_week:
        result = NSC.resolve_nfl_week_cached.__wrapped__("2026-10-05")
    mock_infer.assert_called_once_with("2026-10-05")
    mock_sched.assert_called_once_with(2026)
    mock_week.assert_called_once_with(fake_schedule, "2026-10-05")
    assert result == (2026, 5)
    print("✓ resolve_nfl_week_cached correctly chains _infer_season -> get_schedule -> _resolve_week")


def test_resolve_nfl_week_cached_honest_none_when_season_unresolvable():
    with patch.object(NSC.E, "_infer_season", return_value=None), \
         patch.object(NSC.E, "get_schedule") as mock_sched:
        result = NSC.resolve_nfl_week_cached.__wrapped__("1999-01-01")
    mock_sched.assert_not_called()
    assert result == (None, None)
    print("✓ resolve_nfl_week_cached honestly returns (None, None) for an unresolvable date, without a real, wasted schedule fetch")


def test_resolve_nfl_week_cached_is_genuinely_cached():
    assert hasattr(NSC.resolve_nfl_week_cached, "__wrapped__"), (
        "resolve_nfl_week_cached must genuinely be decorated by st.cache_data, not a plain, uncached function")
    print("✓ resolve_nfl_week_cached is genuinely decorated by st.cache_data, not accidentally uncached")


def test_nfl_shared_cache_importable_without_streamlit():
    # Same real, confirmed pattern already proven for both statcast_data.py and
    # mlb_shared_cache.py -- applied here before NFL goes live, not after a real incident.
    import builtins
    import sys

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "streamlit" or name.startswith("streamlit."):
            raise ImportError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    saved_modules = {m: sys.modules[m] for m in list(sys.modules)
                     if "streamlit" in m or m == "nfl_shared_cache"}
    for m in saved_modules:
        del sys.modules[m]
    builtins.__import__ = _blocked_import
    try:
        import nfl_shared_cache as NSC_no_streamlit
        assert NSC_no_streamlit.st is None, "st must be honestly None when streamlit isn't installed, not crash the import"
        assert not hasattr(NSC_no_streamlit, "load_nfl_slate_cached"), (
            "load_nfl_slate_cached must not be defined at all without streamlit -- "
            "referencing st.cache_data without a real st would crash")
        assert not hasattr(NSC_no_streamlit, "resolve_nfl_week_cached"), (
            "resolve_nfl_week_cached must not be defined at all without streamlit either")
        assert NSC_no_streamlit.E is not None, "nfl_engine itself must still import cleanly, unaffected by this module's own streamlit dependency"
    finally:
        builtins.__import__ = real_import
        for m in list(sys.modules):
            if "streamlit" in m or m == "nfl_shared_cache":
                del sys.modules[m]
        for m, mod in saved_modules.items():
            sys.modules[m] = mod
    print("✓ nfl_shared_cache is safely importable without streamlit, correctly omitting the cached function rather than crashing")


def test_build_slate_prior_season_baseline_uses_999_not_current_week():
    """BUILT DIRECTLY FROM A REAL LIVE LOG: this test exists because build_slate was confirmed
    to return 0 players with the baseline toggle active, with this exact diagnostic line:
    'season 2026 week 1, 16 game(s) -> 0 player(s) cleared rotation floor (using 2025 stats
    as baseline)'. Root cause: player_recent_games was called with before_week=1 (from the
    2026 schedule), but the weekly data was 2025. Games before week 1 of ANY season = empty.
    Fix: before_week=999 when stats_season != season, so all of last season's games are
    included. player_recent_games is already capped by n=CFG.RECENT_GAMES_N.

    ALSO TESTS the build_slate-level stats_season cap: when stats_date_str is None (no
    explicit baseline), build_slate now caps stats_season to nfl.get_current_season() before
    even calling load_season_weekly_stats -- confirmed from live log showing repeated 404s
    being triggered by pages without baseline toggles, because the nested-function auto-fallback
    approach in load_season_weekly_stats was unreliable in the deployed environment."""
    import nfl_engine as E
    import pandas as pd
    from unittest.mock import patch, MagicMock

    schedule_2026 = [{"season": 2026, "week": 1, "home_team": "KC", "away_team": "PHI",
                      "game_date": "2026-09-09", "home_rest": 7, "away_rest": 7}]
    fake_weekly = pd.DataFrame([
        {"player_id": "p1", "player_display_name": "Test QB", "week": 15,
         "season": 2025, "recent_team": "KC", "passing_yards": 310},
        {"player_id": "p1", "player_display_name": "Test QB", "week": 16,
         "season": 2025, "recent_team": "KC", "passing_yards": 280},
    ])
    fake_roster = [{"id": "p1", "name": "Test QB", "position": "QB"}]

    before_weeks_seen = []
    stats_seasons_requested = []
    real_player_recent_games = E.player_recent_games

    def spy_player_recent_games(weekly, player_id, before_week, n=None):
        before_weeks_seen.append(before_week)
        return real_player_recent_games(weekly, player_id, before_week,
                                        n=n or E.CFG.RECENT_GAMES_N)

    def spy_load_season_weekly_stats(s):
        stats_seasons_requested.append(s)
        return fake_weekly

    with patch.object(E, "get_schedule", return_value=schedule_2026), \
         patch.object(E, "load_season_weekly_stats", side_effect=spy_load_season_weekly_stats), \
         patch.object(E, "get_team_roster", return_value=fake_roster), \
         patch.object(E, "player_recent_games", side_effect=spy_player_recent_games), \
         patch.object(E, "_infer_season", side_effect=lambda d: 2026 if "2026" in str(d) else 2025), \
         patch.object(E.nfl, "get_current_season", return_value=2025):
        rows, meta = E.build_slate("2026-09-09", stats_date_str="2025-12-01")

    assert all(w == 999 for w in before_weeks_seen), (
        f"player_recent_games must be called with before_week=999 when using prior-season "
        f"baseline. Got: {before_weeks_seen}")

    # Test the build_slate-level cap: with no explicit stats_date_str
    before_weeks_seen.clear()
    stats_seasons_requested.clear()
    with patch.object(E, "get_schedule", return_value=schedule_2026), \
         patch.object(E, "load_season_weekly_stats", side_effect=spy_load_season_weekly_stats), \
         patch.object(E, "get_team_roster", return_value=fake_roster), \
         patch.object(E, "player_recent_games", side_effect=spy_player_recent_games), \
         patch.object(E, "_infer_season", return_value=2026), \
         patch.object(E.nfl, "get_current_season", return_value=2025):
        rows2, meta2 = E.build_slate("2026-09-09")  # no stats_date_str -- should auto-cap

    assert all(s == 2025 for s in stats_seasons_requested), (
        f"load_season_weekly_stats must never be called with season 2026 when get_current_season "
        f"returns 2025 -- the 404 loop happens because nflreadpy is called for a season that "
        f"doesn't exist. Got seasons requested: {stats_seasons_requested}")
    assert all(w == 999 for w in before_weeks_seen), (
        f"before_week must be 999 even without explicit stats_date_str when build_slate auto-caps. "
        f"Got: {before_weeks_seen}")
    print("✓ build_slate prior-season baseline correctly passes before_week=999, and auto-cap prevents any 2026 nflreadpy call when get_current_season() returns 2025")


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
