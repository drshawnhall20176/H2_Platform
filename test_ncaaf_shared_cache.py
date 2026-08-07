"""
test_ncaaf_shared_cache.py — offline tests for ncaaf_shared_cache.py.

    python test_ncaaf_shared_cache.py     # or: pytest test_ncaaf_shared_cache.py
"""

from unittest.mock import patch

import ncaaf_shared_cache as NCSC


def test_load_ncaaf_slate_cached_wraps_build_slate():
    fake_result = ([{"Player": "Test QB"}], [{"label": "Team A @ Team B"}])
    with patch.object(NCSC.E, "build_slate", return_value=fake_result) as mock_build:
        result = NCSC.load_ncaaf_slate_cached.__wrapped__("2026-09-05")
    mock_build.assert_called_once_with("2026-09-05")
    assert result == fake_result
    print("✓ load_ncaaf_slate_cached correctly wraps ncaaf_engine.build_slate with the real date passed through")


def test_load_ncaaf_slate_cached_is_genuinely_cached():
    assert hasattr(NCSC.load_ncaaf_slate_cached, "__wrapped__"), (
        "load_ncaaf_slate_cached must genuinely be decorated by st.cache_data, not a plain, uncached function")
    print("✓ load_ncaaf_slate_cached is genuinely decorated by st.cache_data, not accidentally uncached")


def test_ncaaf_shared_cache_importable_without_streamlit():
    # Same real, confirmed pattern already proven for statcast_data.py, mlb_shared_cache.py,
    # and nfl_shared_cache.py -- applied here proactively, before any real NCAAF page exists to
    # depend on it.
    import builtins
    import sys

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "streamlit" or name.startswith("streamlit."):
            raise ImportError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    saved_modules = {m: sys.modules[m] for m in list(sys.modules)
                     if "streamlit" in m or m == "ncaaf_shared_cache"}
    for m in saved_modules:
        del sys.modules[m]
    builtins.__import__ = _blocked_import
    try:
        import ncaaf_shared_cache as NCSC_no_streamlit
        assert NCSC_no_streamlit.st is None, "st must be honestly None when streamlit isn't installed, not crash the import"
        assert not hasattr(NCSC_no_streamlit, "load_ncaaf_slate_cached"), (
            "load_ncaaf_slate_cached must not be defined at all without streamlit -- "
            "referencing st.cache_data without a real st would crash")
        assert NCSC_no_streamlit.E is not None, "ncaaf_engine itself must still import cleanly, unaffected by this module's own streamlit dependency"
    finally:
        builtins.__import__ = real_import
        for m in list(sys.modules):
            if "streamlit" in m or m == "ncaaf_shared_cache":
                del sys.modules[m]
        for m, mod in saved_modules.items():
            sys.modules[m] = mod
    print("✓ ncaaf_shared_cache is safely importable without streamlit, correctly omitting the cached function rather than crashing")


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
