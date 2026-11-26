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


def test_tour_never_opens_by_itself(monkeypatch):
    """Nov 26 (owner): no pop-up on a first visit; only the button opens it."""
    import streamlit as st
    import tour as T
    shown = []
    monkeypatch.setattr(T, "_show", lambda: shown.append(1))
    monkeypatch.setattr(T, "seen", lambda: False)                # a first-time visitor
    monkeypatch.setattr(st, "button", lambda *a, **k: False)
    st.session_state.pop(T.OPEN_KEY, None)
    T.render()
    assert shown == []
    st.session_state[T.OPEN_KEY] = True
    T.render()
    assert shown == [1]
