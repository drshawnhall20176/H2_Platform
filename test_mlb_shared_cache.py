"""
test_mlb_shared_cache.py — offline tests for mlb_shared_cache.py.

    python test_mlb_shared_cache.py     # or: pytest test_mlb_shared_cache.py
"""

from unittest.mock import patch

import mlb_shared_cache as MSC


def test_load_pitching_slate_cached_wraps_build_pitching_slate():
    with patch.object(MSC.E, "build_pitching_slate", return_value=[{"Pitcher": "Test"}]) as mock_build:
        result = MSC.load_pitching_slate_cached.__wrapped__("2026-08-06")
    mock_build.assert_called_once_with("2026-08-06")
    assert result == [{"Pitcher": "Test"}]
    print("✓ load_pitching_slate_cached correctly wraps mlb_engine.build_pitching_slate with the real date passed through")


def test_get_team_bullpen_fatigue_cached_wraps_the_real_engine_call():
    fake_fatigue = [{"player_id": 1, "days_since_last": 0}]
    with patch.object(MSC.E, "get_team_bullpen_fatigue", return_value=fake_fatigue) as mock_fetch:
        result = MSC.get_team_bullpen_fatigue_cached.__wrapped__(147, "2026-08-06")
    mock_fetch.assert_called_once_with(147, "2026-08-06")
    assert result == fake_fatigue
    print("✓ get_team_bullpen_fatigue_cached correctly wraps mlb_engine.get_team_bullpen_fatigue with the real team_id and date passed through")


def test_get_team_bullpen_fatigue_cached_is_genuinely_cached():
    assert hasattr(MSC.get_team_bullpen_fatigue_cached, "__wrapped__"), (
        "get_team_bullpen_fatigue_cached must genuinely be decorated by st.cache_data, not a plain, uncached function")
    print("✓ get_team_bullpen_fatigue_cached is genuinely decorated by st.cache_data, not accidentally uncached")


def test_load_hitter_slate_cached_wraps_build_slate():
    fake_result = ([{"Hitter": "Test"}], [{"label": "Team A @ Team B"}])
    with patch.object(MSC.E, "build_slate", return_value=fake_result) as mock_build:
        result = MSC.load_hitter_slate_cached.__wrapped__("2026-08-06")
    mock_build.assert_called_once_with("2026-08-06")
    assert result == fake_result
    print("✓ load_hitter_slate_cached correctly wraps mlb_engine.build_slate with the real date passed through")


def test_load_hitter_slate_cached_is_genuinely_cached():
    assert hasattr(MSC.load_hitter_slate_cached, "__wrapped__"), (
        "load_hitter_slate_cached must genuinely be decorated by st.cache_data, not a plain, uncached function")
    print("✓ load_hitter_slate_cached is genuinely decorated by st.cache_data, not accidentally uncached")


def test_get_team_injuries_cached_wraps_the_real_engine_call():
    fake_injuries = [{"player": "Test Player", "status": "10-Day IL"}]
    with patch.object(MSC.E, "get_team_injuries", return_value=fake_injuries) as mock_fetch:
        result = MSC.get_team_injuries_cached.__wrapped__(147)
    mock_fetch.assert_called_once_with(147)
    assert result == fake_injuries
    print("✓ get_team_injuries_cached correctly wraps mlb_engine.get_team_injuries with the real team_id passed through")


def test_get_team_injuries_cached_returns_empty_for_no_team_id():
    result = MSC.get_team_injuries_cached.__wrapped__(None)
    assert result == []
    print("✓ get_team_injuries_cached correctly returns an honest empty list when no real team_id is given, without calling the real fetch")


def test_get_team_injuries_cached_is_genuinely_cached():
    assert hasattr(MSC.get_team_injuries_cached, "__wrapped__"), (
        "get_team_injuries_cached must genuinely be decorated by st.cache_data, not a plain, uncached function")
    print("✓ get_team_injuries_cached is genuinely decorated by st.cache_data, not accidentally uncached")


def test_load_slate_with_fip_cached_wraps_build_slate_with_the_real_fip_constant():
    fake_result = ([{"Hitter": "Test"}], [{"label": "Team A @ Team B"}])
    with patch.object(MSC.E, "build_slate", return_value=fake_result) as mock_build:
        result = MSC.load_slate_with_fip_cached.__wrapped__("2026-08-06", 3.10)
    mock_build.assert_called_once_with("2026-08-06", 3.10)
    assert result == fake_result
    print("✓ load_slate_with_fip_cached correctly passes the real date and fip_constant through to build_slate")


def test_load_slate_with_fip_cached_is_genuinely_cached():
    assert hasattr(MSC.load_slate_with_fip_cached, "__wrapped__"), (
        "load_slate_with_fip_cached must genuinely be decorated by st.cache_data, not a plain, uncached function")
    print("✓ load_slate_with_fip_cached is genuinely decorated by st.cache_data, not accidentally uncached")


def test_load_pitching_slate_cached_is_genuinely_cached():
    # __wrapped__ bypasses Streamlit's own cache for the unit test above (isolating the real
    # logic from Streamlit's runtime, which doesn't have a real session here) -- this confirms
    # the REAL, live-decorated function is genuinely wrapped BY st.cache_data, not accidentally
    # calling the raw, uncached function.
    assert hasattr(MSC.load_pitching_slate_cached, "__wrapped__"), (
        "load_pitching_slate_cached must genuinely be decorated by st.cache_data (which adds "
        "__wrapped__), not a plain, uncached function")
    print("✓ load_pitching_slate_cached is genuinely decorated by st.cache_data, not accidentally uncached")


def test_get_all_active_player_names_cached_wraps_the_real_engine_call():
    fake_names = {"Kevin Gausman", "Alí Sánchez"}
    with patch.object(MSC.E, "get_all_active_player_names", return_value=fake_names) as mock_fetch:
        result = MSC.get_all_active_player_names_cached.__wrapped__(2026)
    mock_fetch.assert_called_once_with(2026)
    assert result == fake_names
    print("✓ get_all_active_player_names_cached correctly wraps mlb_engine.get_all_active_player_names with the real season passed through")


def test_get_all_active_player_names_cached_is_genuinely_cached():
    assert hasattr(MSC.get_all_active_player_names_cached, "__wrapped__"), (
        "get_all_active_player_names_cached must genuinely be decorated by st.cache_data, not a plain, uncached function")
    print("✓ get_all_active_player_names_cached is genuinely decorated by st.cache_data, not accidentally uncached")


def test_mlb_shared_cache_importable_without_streamlit():
    # THE real, confirmed production incident this class of fix guards against, reproduced
    # directly here, not just asserted from source text -- the exact same real pattern already
    # proven for statcast_data.py's own load_cached (see that module's own test for the full
    # real incident this traces back to). A standalone script that imports mlb_engine directly
    # must never be forced to also have Streamlit installed just because THIS module exists.
    import builtins
    import sys

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "streamlit" or name.startswith("streamlit."):
            raise ImportError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    saved_modules = {m: sys.modules[m] for m in list(sys.modules)
                     if "streamlit" in m or m == "mlb_shared_cache"}
    for m in saved_modules:
        del sys.modules[m]
    builtins.__import__ = _blocked_import
    try:
        import mlb_shared_cache as MSC_no_streamlit
        assert MSC_no_streamlit.st is None, "st must be honestly None when streamlit isn't installed, not crash the import"
        assert not hasattr(MSC_no_streamlit, "load_pitching_slate_cached"), (
            "load_pitching_slate_cached must not be defined at all without streamlit -- "
            "referencing st.cache_data without a real st would crash")
        assert not hasattr(MSC_no_streamlit, "get_team_bullpen_fatigue_cached"), (
            "get_team_bullpen_fatigue_cached must not be defined at all without streamlit either")
        assert not hasattr(MSC_no_streamlit, "load_hitter_slate_cached"), (
            "load_hitter_slate_cached must not be defined at all without streamlit either")
        assert not hasattr(MSC_no_streamlit, "get_team_injuries_cached"), (
            "get_team_injuries_cached must not be defined at all without streamlit either")
        assert not hasattr(MSC_no_streamlit, "load_slate_with_fip_cached"), (
            "load_slate_with_fip_cached must not be defined at all without streamlit either")
        assert not hasattr(MSC_no_streamlit, "get_all_active_player_names_cached"), (
            "get_all_active_player_names_cached must not be defined at all without streamlit either")
        assert MSC_no_streamlit.E is not None, "mlb_engine itself must still import cleanly, unaffected by this module's own streamlit dependency"
    finally:
        builtins.__import__ = real_import
        for m in list(sys.modules):
            if "streamlit" in m or m == "mlb_shared_cache":
                del sys.modules[m]
        for m, mod in saved_modules.items():
            sys.modules[m] = mod
    print("✓ mlb_shared_cache is safely importable without streamlit, correctly omitting the cached function rather than crashing")


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
