"""
Owner_Office.py -- the Office door (office.py). Password first; once in, the sidebar switches to the Office's own menu.
"""
import streamlit as st

import components as C
import office as OF

C.base_css()
C.section_header("🔐", "Owner Office", "Your books, grading, proof and investor pages — kept apart from the sport desks")

try:
    expected = st.secrets.get(OF.SECRET)
except Exception:                                               # noqa: BLE001
    expected = None

if OF.active(st.session_state):
    st.success("You're in the Office. Its pages are in the sidebar; the sport you pick there still applies to them.")
    c1, c2 = st.columns(2)
    if c1.button("⬅ Back to the sport desks", type="primary"):
        st.session_state[OF.MODE] = False
        st.rerun()
    if c2.button("🔒 Lock the Office"):
        st.session_state[OF.MODE] = False
        st.session_state[OF.UNLOCKED] = False
        st.rerun()
elif OF.unlocked(st.session_state):
    st.info("The Office is unlocked for this session.")
    if st.button("Enter the Office", type="primary"):
        st.session_state[OF.MODE] = True
        st.rerun()
else:
    if not expected:
        st.error(f"The Office is shut: no password is set. Add `{OF.SECRET}` to this app's secrets on Streamlit Cloud "
                 "(Settings → Secrets), then reload.")
        st.stop()
    st.caption("Only the person with the Office password can open these pages. Partners need you to share it.")
    with st.form("office_door", clear_on_submit=True):
        pw = st.text_input("Office password", type="password")
        go = st.form_submit_button("Open the Office", type="primary")
    if go:
        if OF.check(pw, expected):
            st.session_state[OF.UNLOCKED] = True
            st.session_state[OF.MODE] = True
            st.session_state["trading_unlocked"] = True         # Bet Log / Track Record: one password, not two
            st.rerun()
        st.error("Incorrect password.")
