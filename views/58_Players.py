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

# Nov 25 (owner: "merge the data we see in the Players tab into the player card so we do not have two data points
# showing different things"): Cards (the default) list tonight's players and open the one player card -- the model's
# projection plus the head-to-head, defense-lately and rest context these views used to show on their own. The
# separate tools stay under Table.
import view_mode as VM
C.base_css()
if VM.choose("players", "Cards: tonight's players, each opening his player card. Table: the separate player tools "
                        "(by position, hot players, head to head ...).") == VM.CARDS:
    import players_cards as PCD
    PCD.render(sport)
    st.stop()
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
