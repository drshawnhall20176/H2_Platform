"""
conftest.py — shared pytest fixtures for the whole test suite.

A REAL, CONFIRMED BUG FIX, not a precaution taken speculatively: while adding caching to
best_bets_data.load_mlb_best_bets_board (a real, deliberate fix for a real, reported slowness --
see that function's own docstring), a real, empirical check found that two EXISTING tests
(test_load_mlb_best_bets_board_full_pipeline_runs_and_blends and test_load_mlb_best_bets_board_
returns_meta_not_just_count) call that function with the exact same real arguments but genuinely
different mocks (one with real bullpen data, one without). Confirmed directly: the second test
was silently receiving the first test's own cached result instead of running its own real mock
setup -- st.cache_data's own in-memory store (confirmed active even outside a real Streamlit
runtime, via its own "No runtime found, using MemoryCacheStorageManager" fallback) persists
across separate test functions within the same pytest process by default, with no built-in
per-test isolation.

This wasn't caught by either test's own assertions before now purely by coincidence -- neither
test happened to assert on the specific field (_bullpen_blended) that differed between their two
mocks. A future test checking that exact field, or any other @st.cache_data-decorated function
tested the same way, would silently get a wrong, stale result with no warning.

Fixed at the root, not per-test: an autouse fixture here clears every real Streamlit cache before
each test runs, so every test's own mocks are guaranteed to produce a real, fresh call -- the
same guarantee a real, separate Streamlit Cloud session would have for two genuinely different
real requests.
"""

import pytest


@pytest.fixture(autouse=True)
def _clear_streamlit_caches():
    """Runs before every single test in the whole suite, no per-test opt-in needed. Clears
    BOTH real Streamlit cache types (cache_data AND cache_resource) -- st.cache_data.clear()
    alone doesn't touch cache_resource, and a future @st.cache_resource-decorated function
    would have the exact same real cross-test pollution risk this fixture exists to prevent."""
    try:
        import streamlit as st
        st.cache_data.clear()
        st.cache_resource.clear()
    except Exception:
        # A real, honest fail-soft: if streamlit itself isn't installed in whatever real
        # environment runs this suite, there's no real cache to clear -- never block collection
        # or a real test run over a missing optional dependency.
        pass
    yield


@pytest.fixture(autouse=True)
def _game_money_not_paused(monkeypatch, request):
    """Nov 22: the 💰 college game-line rule is paused in production (money_score.PAUSED); tests of the rule itself
    run it unpaused, and test_money_score checks the pause directly. test_rules fingerprints the real setting."""
    if request.node.fspath.basename == "test_rules.py":
        return
    try:
        import money_score as _MSC
        monkeypatch.setattr(_MSC, "PAUSED", {})
    except Exception:                                           # noqa: BLE001
        pass


@pytest.fixture(autouse=True)
def _no_live_injury_report(monkeypatch):
    """Nov 25: cards re-check tonight's ESPN injury report; tests never reach the network for it."""
    try:
        import injury_check as IC
        monkeypatch.setattr(IC, "_get_json", lambda sport: {})
        IC._cache.clear()
        IC._full.clear()
    except Exception:                                           # noqa: BLE001
        pass
    try:                                                        # Nov 26: nor for the cards' news feed
        import news as NW
        monkeypatch.setattr(NW, "_get_json", lambda sport, limit=100: {})
        monkeypatch.setattr(NW, "_get_url", lambda url, params: {})
        NW._cache.clear()
        NW._board.clear()
        NW._story.clear()
    except Exception:                                           # noqa: BLE001
        pass
    try:                                                        # Nov 26: nor for the football cards' weather
        import football_weather as FW
        monkeypatch.setattr(FW, "_card_slate", lambda sport, day: [])
    except Exception:                                           # noqa: BLE001
        pass
    try:                                                        # Nov 26: nor for the cards' league defense tables
        import soft_spots as SS
        monkeypatch.setattr(SS, "load_league", lambda sport, day: {"games": []})
    except Exception:                                           # noqa: BLE001
        pass
    try:                                                        # Nov 26: nor for NFL play-by-play (zones)
        import nfl_zones as NZ
        monkeypatch.setattr(NZ, "_load", lambda season: [])
    except Exception:                                           # noqa: BLE001
        pass
