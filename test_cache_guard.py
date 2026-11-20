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
