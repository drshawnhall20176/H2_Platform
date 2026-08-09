"""
test_basketball_shared_cache.py — offline tests for basketball_shared_cache.py.

    python test_basketball_shared_cache.py     # or: pytest test_basketball_shared_cache.py
"""

from unittest.mock import patch

import basketball_shared_cache as BSC


def test_load_team_spreads_cached_wraps_fetch_slate_spreads():
    fake_result = ({"Boston Red Sox": -5.0}, {"events_total": 1, "events_fetched": 1, "remaining": 100})
    with patch.object(BSC.O, "fetch_slate_spreads", return_value=fake_result) as mock_fetch:
        result = BSC.load_team_spreads_cached.__wrapped__("WNBA", "2026-08-08", "fake_key")
    mock_fetch.assert_called_once_with("2026-08-08", "fake_key", sport="basketball_wnba")
    assert result == fake_result
    print("✓ load_team_spreads_cached correctly resolves the real sport's own odds_sport_key and passes the real date/api_key through")


def test_load_team_spreads_cached_is_genuinely_cached():
    assert hasattr(BSC.load_team_spreads_cached, "__wrapped__"), (
        "load_team_spreads_cached must genuinely be decorated by st.cache_data, not a plain, uncached function")
    print("✓ load_team_spreads_cached is genuinely decorated by st.cache_data, not accidentally uncached")


def test_blowout_risk_for_team_delegates_to_the_real_sport_specific_tag():
    class FakeProj:
        @staticmethod
        def blowout_risk_tag(spread):
            return "⚠️ Blowout risk" if spread is not None and abs(spread) >= 10.0 else "Competitive"

    team_spreads = {"Boston Red Sox": -14.0, "New York Yankees": -3.0}
    assert BSC.blowout_risk_for_team("Boston Red Sox", team_spreads, FakeProj) == "⚠️ Blowout risk"
    assert BSC.blowout_risk_for_team("New York Yankees", team_spreads, FakeProj) == "Competitive"
    print("✓ blowout_risk_for_team correctly delegates to the real sport's own blowout_risk_tag implementation")


def test_blowout_risk_for_team_honest_dash_for_a_sport_with_no_real_tag():
    class FakeProjWithoutBlowoutTag:
        pass   # a real sport whose projections module genuinely has no blowout_risk_tag at all

    result = BSC.blowout_risk_for_team("Any Team", {"Any Team": -20.0}, FakeProjWithoutBlowoutTag)
    assert result == "—"
    print("✓ blowout_risk_for_team honestly returns '—' for a real sport with no blowout_risk_tag capability, never a fabricated risk label")


def test_blowout_risk_for_team_honest_dash_for_a_team_with_no_real_spread():
    class FakeProj:
        @staticmethod
        def blowout_risk_tag(spread):
            return "—" if spread is None else "⚠️ Blowout risk"

    result = BSC.blowout_risk_for_team("Unknown Team", {"Other Team": -14.0}, FakeProj)
    assert result == "—"
    print("✓ blowout_risk_for_team honestly returns '—' for a real team with no real spread fetched or found tonight")


def test_basketball_shared_cache_importable_without_streamlit():
    # Same real, confirmed pattern already proven for mlb_shared_cache.py, nfl_shared_cache.py,
    # and ncaaf_shared_cache.py -- a module used by both the live Streamlit app and any future
    # standalone script must not require Streamlit at all.
    import builtins
    import sys

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "streamlit" or name.startswith("streamlit."):
            raise ImportError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    saved_modules = {m: sys.modules[m] for m in list(sys.modules)
                     if "streamlit" in m or m == "basketball_shared_cache"}
    for m in saved_modules:
        del sys.modules[m]
    builtins.__import__ = _blocked_import
    try:
        import basketball_shared_cache as BSC_no_streamlit
        assert BSC_no_streamlit.st is None, "st must be honestly None when streamlit isn't installed, not crash the import"
        assert not hasattr(BSC_no_streamlit, "load_team_spreads_cached"), (
            "load_team_spreads_cached must not be defined at all without streamlit -- "
            "referencing st.cache_data without a real st would crash")
        assert BSC_no_streamlit.O is not None, "odds_api itself must still import cleanly, unaffected by this module's own streamlit dependency"
        assert BSC_no_streamlit.blowout_risk_for_team is not None, (
            "blowout_risk_for_team has no real streamlit dependency and must still be defined without it")
    finally:
        builtins.__import__ = real_import
        for m in list(sys.modules):
            if "streamlit" in m or m == "basketball_shared_cache":
                del sys.modules[m]
        for m, mod in saved_modules.items():
            sys.modules[m] = mod
    print("✓ basketball_shared_cache is safely importable without streamlit, correctly omitting only the cached function rather than crashing")


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
