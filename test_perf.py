"""Nov 26: the owner's page-timing panel."""
import time

import perf as PF


def test_timed_steps_slowest_first(monkeypatch):
    import streamlit as st
    st.session_state.clear() if hasattr(st.session_state, "clear") else None
    PF.start()
    with PF.timed("fast"):
        pass
    with PF.timed("slow"):
        time.sleep(0.02)
    rows, total = PF.steps()
    assert [k for k, _ in rows] == ["slow", "fast"] and total >= 0.02


def test_today_page_shows_the_timing_panel(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import todays_best as TB
    import streamlit as st
    st.cache_data.clear()
    monkeypatch.setattr(TB, "collect", lambda day, keys, past=False: {"rows": [], "props": {}})
    monkeypatch.setattr(TB, "winner_rows", lambda day, leagues=None, past=False: [])
    at = AppTest.from_file("views/57_Today.py", default_timeout=60).run()
    assert not at.exception
    assert any(e.label.startswith("⏱️ Page timing — Today") for e in at.expander)
