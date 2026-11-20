"""Nov 20 (owner: "my platform loves to crash Streamlit's resource requirements"): cache_guard.py."""
import cache_guard as CG


def test_install_caps_every_cache_without_its_own_limit(monkeypatch):
    import streamlit as st
    seen = []

    class Fake:
        def __call__(self, func=None, **kw):
            seen.append(kw)
            return (lambda f: f) if func is None else func

        def clear(self):
            seen.append("cleared")
    monkeypatch.setattr(st, "cache_data", Fake())
    CG.install()

    @st.cache_data(ttl=60)
    def a():
        return 1

    @st.cache_data(ttl=60, max_entries=5)
    def b():
        return 2

    @st.cache_data
    def c():
        return 3
    assert seen[0] == {"ttl": 60, "max_entries": CG.DEFAULT_MAX_ENTRIES} and seen[1]["max_entries"] == 5
    assert seen[2] == {"max_entries": CG.DEFAULT_MAX_ENTRIES}
    st.cache_data.clear()
    assert seen[-1] == "cleared"
    CG.install()                                               # twice is a no-op
    assert getattr(st.cache_data, "_h2_guard", False)


def test_watchdog_clears_over_the_limit_at_most_once_a_minute(monkeypatch):
    monkeypatch.setenv("H2_MEM_LIMIT_MB", "1000")
    CG._STATE["last"] = 0.0
    cleared = []
    assert not CG.watchdog(now=1000, rss=900, clear=lambda: cleared.append(1))
    assert CG.watchdog(now=1000, rss=1200, clear=lambda: cleared.append(1)) and cleared == [1]
    assert not CG.watchdog(now=1030, rss=1300, clear=lambda: cleared.append(1))       # within a minute
    assert CG.watchdog(now=1100, rss=1300, clear=lambda: cleared.append(1)) and cleared == [1, 1]
    assert CG.rss_mb() is None or CG.rss_mb() > 0
    CG._STATE["last"] = 0.0


def test_reload_race_is_recognised_and_import_retried(monkeypatch):
    import importlib
    assert CG.is_reload_race(AttributeError("'NoneType' object has no attribute '__dict__'"))
    assert CG.is_reload_race(ImportError("cannot import name 'x' from partially initialized module 'y'"))
    assert not CG.is_reload_race(AttributeError("'Foo' object has no attribute 'bar'"))
    calls = []
    real = importlib.import_module

    def flaky(name):
        calls.append(name)
        if len(calls) == 1:
            raise AttributeError("'NoneType' object has no attribute '__dict__'")
        return real(name)
    monkeypatch.setattr(importlib, "import_module", flaky)
    assert CG.safe_import("json").__name__ == "json" and len(calls) == 2


def test_app_loads_the_saved_board_instead_of_building(monkeypatch):
    """Nov 20: a college football board build measured ~1 GB; the app loads the warm job's saved copy."""
    import time
    import base64
    import best_bets_data as BBD
    import model_store as MS
    import slate_store as SS
    store = {}
    monkeypatch.setattr(SS, "_off", lambda: False)
    monkeypatch.setattr(MS, "save_slate", lambda sp, d, payload, db_path=None: store.__setitem__((sp, d), payload))
    from datetime import datetime, timezone, timedelta

    def load(sp, d, db_path=None, age_h=0.5):
        if (sp, d) not in store:
            return None
        return {"ts": (datetime.now(timezone.utc) - timedelta(hours=load.age)).isoformat(), "payload": store[(sp, d)]}
    load.age = 0.5
    monkeypatch.setattr(MS, "load_slate", load)
    day = SS._today_et()
    BBD.save_board("NBA", day, "draftkings", ([{"Player": "A"}], [{"g": 1}], ["draftkings"], [], {}))
    got = BBD.saved_board("NBA", day, "draftkings")
    assert got[0] == [{"Player": "A"}]
    load.age = 2                                                 # older than 75 minutes: NBA rebuilds
    assert BBD.saved_board("NBA", day, "draftkings") is None
    BBD.save_board("NCAAF", day, "draftkings", ([{"Player": "B"}], [], [], [], {}))
    assert BBD.saved_board("NCAAF", day, "draftkings")[0] == [{"Player": "B"}]   # heavy: 2h old is still used
    load.age = 7
    assert BBD.saved_board("NCAAF", day, "draftkings") is None
    monkeypatch.setenv("H2_BOARD_LIVE", "1")
    load.age = 0.1
    assert BBD.saved_board("NCAAF", day, "draftkings") is None                      # the warm job always builds


def test_heavy_sports_are_never_built_inside_the_app(monkeypatch):
    import best_bets_data as BBD
    monkeypatch.setattr(BBD, "saved_board", lambda *a, **k: None)
    monkeypatch.setattr(BBD, "_in_app", lambda: True)
    monkeypatch.setattr(BBD, "build_generic_board", lambda *a, **k: (_ for _ in ()).throw(AssertionError("built")))
    BBD.load_generic_best_bets_board.clear()
    assert BBD.load_generic_best_bets_board("NCAAF", "2026-11-21", "draftkings")[0] == []
    monkeypatch.setattr(BBD, "build_generic_board", lambda *a, **k: (["p"], [], []))
    assert BBD.load_generic_best_bets_board("NBA", "2026-11-21", "draftkings")[0] == ["p"]      # light sports build
    BBD.load_generic_best_bets_board.clear()
