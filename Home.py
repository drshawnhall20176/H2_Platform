import streamlit as st
import sports

st.title("⚾ H2 Sports — MLB Model Dashboard")
st.caption("Live matchup analytics powered by the public MLB Stats API")

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

st.markdown("### 🏟 Select Sport")
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

st.markdown(
    """
This dashboard is built on a single shared backend (`mlb_engine.py`) so every page
pulls the same live data and stays consistent.

**Pages**
- **🎯 Pitching Lab** — probable starters across today's slate, ERA vs FIP regression,
  and auto-generated discussion hooks.
- **💣 Dinger Engine** — every projected hitter on the slate with platoon edges, ISO/OPS,
  and matchup leaderboards. Uses posted lineups when available, active rosters otherwise.

Pick a date on any page, and the engine fetches the slate concurrently — a full day
usually loads in a few seconds.
"""
)

st.info(
    "Analytics here describe likelihoods and trends, not certainties. If you publish picks "
    "to an audience, note that gambling-content promotion is regulated in many regions "
    "(affiliate/advertising rules vary by jurisdiction)."
)
