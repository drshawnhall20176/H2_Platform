"""
view_mode.py — one Cards | Table choice for the whole site (Nov 25).

Members' request, through the owner: "keep the card theme throughout as the default ... give me the option to switch to
the tables like you do on the Today page." Cards are the default on every page that has both; switching on one page
switches every page (the choice is kept for the visit).
"""
from __future__ import annotations

CARDS, TABLE = "Cards", "Table"
PREF = "h2_view_pref"


def current() -> str:
    import streamlit as st
    v = st.session_state.get(PREF) or CARDS
    return v if v in (CARDS, TABLE) else CARDS


def choose(page: str, help_text: str = "") -> str:
    """The switch, drawn on a page; returns Cards or Table. Each page has its own widget (Streamlit forgets a widget's
    state on pages that don't draw it), all reading and writing the one site-wide choice."""
    import streamlit as st
    key = f"view_{page}"
    st.session_state[key] = current()

    def _changed():
        st.session_state[PREF] = st.session_state.get(key) or current()
    st.segmented_control("View", [CARDS, TABLE], key=key, on_change=_changed,
                         help=help_text or "Cards: tap any game or player to open it. Table: every row in one list. "
                                           "Your choice follows you to every page.")
    return current()
