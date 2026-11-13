"""
International Hoops — EuroLeague and Australia's NBL game model (Nov 3). TRACKING ONLY until the record proves it.
Owner only.

Every upcoming game the books price, saved every 3 hours by the capture-intl workflow: the ratings model's margin and
total against the consensus spread and total, its win chance against the moneyline, and tracking picks where it
clears its bar. Graded from the leagues' results. Model: intl_hoops.py; capture / grading / record: intl_picks.py;
the view: hoops_games_page.py (shared with the college basketball Game Lab).
"""
import streamlit as st

import components as C
import hoops_games_page as HG
import intl_hoops as I

C.base_css()
C.page_header("🌍", "International Hoops",
              "EuroLeague, EuroCup, Champions League, FIBA Europe Cup, EuroCup Women, NBL and five domestic leagues: opponent-adjusted ratings against the spread, total and moneyline. Tracking only "
              "until the record proves it.")
import intl_picks as IP
# Nov 13 (owner): like soccer -- only the leagues with a game today or tomorrow
_all = [k for k in IP.INTL_LEAGUES if k in I.LEAGUES]
_on = IP.slate_leagues()
shown = _all if _on is None else _on
if not shown:
    st.info("No international games today or tomorrow in these leagues. The list refreshes with every capture.")
    st.stop()
league = st.radio("League (playing today or tomorrow)", shown, format_func=lambda k: I.LEAGUES[k]["title"],
                  horizontal=True, key="ih_league")
HG.render(league)
