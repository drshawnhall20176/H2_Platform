"""
Players — one page for every player tool (Nov 16). Commercial layout only.

A switcher over the active sport's player views (players_hub.py); only the chosen view's own script runs, unchanged.
"""
import runpy
from pathlib import Path

import streamlit as st

import components as C
import players_hub as PH
import sports

sport = st.session_state.get("sport", sports.DEFAULT_SPORT)
tools = PH.tools_for(sport)
if not tools:
    C.base_css()
    C.page_header("👤", "Players", "Player views for the sport you have picked.")
    st.info("There are no player views for this sport. Pick another sport on Today.")
    st.stop()

names = [n for n, _ in tools]
view = st.segmented_control("View", names, default=names[0], key=f"players_view_{sport}",
                            label_visibility="collapsed") or names[0]
st.caption(PH.ABOUT.get(view, ""))
script = PH.script_for(dict(tools)[view], Path(__file__).parent)
if script is None:
    st.error("This view is not available right now.")
    st.stop()
runpy.run_path(str(script), run_name="__main__")
