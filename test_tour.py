import tour as T


def test_steps_cover_the_honest_reading_rules():
    text = " ".join(b for _, b in T.STEPS)
    assert "earned chance" in text and "🃏 Bet" in text and "🧪 Tracking" in text and "Track record" in text
    assert 5 <= len(T.STEPS) <= 8


def test_finish_marks_it_seen(monkeypatch):
    import streamlit as st
    st.session_state.clear()
    T._go(99)
    assert st.session_state[T.STEP_KEY] == len(T.STEPS) - 1
    T._go(-3)
    assert st.session_state[T.STEP_KEY] == 0
    T.finish()
    assert T.seen() and st.session_state[T.OPEN_KEY] is False
