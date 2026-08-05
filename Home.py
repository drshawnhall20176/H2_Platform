import streamlit as st
import sports
import components as C
import schedule_board as SB
from datetime import datetime as _dt
import pytz as _pytz

_ET = _pytz.timezone("US/Eastern")

C.base_css()
C.hero_banner("⚾", "H2 Sports — MLB Model Dashboard",
             "Live matchup analytics powered by the public MLB Stats API")

# Sport selector -- primary location is here in the main content area, not the sidebar.
# Streamlit's st.navigation always injects page links at the top of the sidebar regardless
# of call order, pushing any sidebar widget below the full page list. Rendering it here
# ensures it's always visible and unobstructed, at the top of the main content on the
# landing page every user sees first.
st.divider()
live = sports.enabled_sports()
keys = [s.key for s in live]
current = st.session_state.get("sport", sports.DEFAULT_SPORT)
if current not in keys:
    current = keys[0]

C.section_header("🏟", "Select Sport")
cols = st.columns(len(keys) + len([s for s in sports.REGISTRY.values() if not s.enabled]))

for i, s in enumerate(live):
    with cols[i]:
        selected = (current == s.key)
        if st.button(
            f"{s.icon} {s.label}",
            key=f"sport_btn_{s.key}",
            type="primary" if selected else "secondary",
            width="stretch"
        ):
            st.session_state["sport"] = s.key
            st.rerun()

coming = [s for s in sports.REGISTRY.values() if not s.enabled]
for i, s in enumerate(coming):
    with cols[len(live) + i]:
        st.button(
            f"{s.icon} {s.label}\n*(coming soon)*",
            key=f"sport_btn_coming_{s.key}",
            disabled=True,
            width="stretch"
        )

active = sports.REGISTRY.get(current)
if active:
    st.caption(f"Currently viewing: **{active.icon} {active.label}** — select a page from the sidebar to begin.")
    if current == "UFC":
        st.info("🥊 UFC Fight Card is live — tonight's bouts with moneyline odds, "
               "method of victory lines, and fight duration props. "
               "Phase 2 will add finishing rate history and conviction scoring.")

st.divider()

# ---------- Today's Schedule ----------
# Sport-aware, and only rendered for the sports schedule_board.py actually covers (MLB, NBA,
# WNBA, NFL, NCAAF, NCAAMB) -- UFC (individual bouts, not team matchups -- UFC Fight Card already
# IS its own schedule) is deliberately hidden here rather than shown broken/empty, same "hidden,
# not shown broken" posture the sidebar itself already uses for sport-gated pages. NCAAMB renders
# through the SAME rich board as every other sport here now (added directly on request to League
# Schedules, and this page gets it for free too, same shared schedule_board.py) -- honestly
# grouped into an "Other" section rather than real conferences, since no verified 350+-team
# conference table exists yet, see schedule_board.py's own module docstring for the full reasoning.
if active and current in SB.SUPPORTED_SPORTS:
    today_str = _dt.now(_ET).strftime("%Y-%m-%d")
    with st.spinner("Loading today's schedule..."):
        schedule_result = SB.todays_schedule(current, today_str)
    C.todays_schedule_board(schedule_result, active.icon, active.label)
    st.divider()

if active:
    with st.container(border=True):
        st.markdown(
            f"""
This dashboard is built on a single shared backend (`{active.engine_module}.py`) so every page
pulls the same live data and stays consistent.

Pick a date on any page, and the engine fetches the slate concurrently — a full day
usually loads in a few seconds. See the sidebar for every page available for
**{active.icon} {active.label}**.
"""
        )

st.info(
    "Analytics here describe likelihoods and trends, not certainties. If you publish picks "
    "to an audience, note that gambling-content promotion is regulated in many regions "
    "(affiliate/advertising rules vary by jurisdiction)."
)
