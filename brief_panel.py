"""
brief_panel.py -- the owner's morning brief and afternoon picks note, on the page (Nov 26).

morning_brief.py saves each note ("brief:<date>:<kind>"); without a private Discord webhook this panel is the only
place to read it. Owner deployment only -- the notes carry the owner's bets.
"""
from __future__ import annotations


def render(day=None) -> bool:
    """The day's notes, newest open. Returns True when one was shown."""
    import streamlit as st
    try:
        if st.secrets.get("AUDIENCE", "owner") != "owner":
            return False
    except Exception:                                           # noqa: BLE001 -- no secrets file: a local owner run
        pass
    try:
        from datetime import datetime
        import pandas as pd
        import pytz
        import components as C
        import model_store as MS
        day = day or datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
        briefs = [(k, t, MS.get_setting(f"brief:{day}:{k}")) for k, t in
                  (("picks", "🎯 This afternoon's picks"), ("morning", "☀️ Morning brief"))]
        briefs = [(k, t, b) for k, t, b in briefs if isinstance(b, dict) and b.get("text")]
        for i, (_kind, title, b) in enumerate(briefs):
            with st.expander(title + " (only you see this)", expanded=i == 0):
                lines = b["text"].split("\n")[1:]               # the first line is the note's own title
                if b.get("table"):
                    head = [l for l in lines if l.strip() and not l.startswith("•")]
                    foot = [l for l in head if l.startswith("Singles only")]
                    for ln in [l for l in head if l not in foot]:
                        st.markdown(C.money_md(ln))
                    tdf = pd.DataFrame(b["table"])
                    if "Price" in tdf:
                        tdf["Price"] = tdf["Price"].fillna("—")
                    st.dataframe(tdf, hide_index=True, width="stretch")
                    for ln in foot:
                        st.caption(C.money_md(ln))
                else:
                    st.markdown(C.money_md("  \n".join(lines)))
        return bool(briefs)
    except Exception:                                           # noqa: BLE001 -- the brief is a bonus
        return False
