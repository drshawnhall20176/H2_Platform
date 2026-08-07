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
    mock_build.assert_called_once_with("2026-09-08")
    assert result == fake_result
    print("✓ load_nfl_slate_cached correctly wraps nfl_engine.build_slate with the real date passed through")


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
