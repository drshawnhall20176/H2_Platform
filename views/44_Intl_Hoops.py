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
              "EuroLeague and NBL: opponent-adjusted ratings against the spread, total and moneyline. Tracking only "
              "until the record proves it.")
league = st.radio("League", ["EUROLEAGUE", "NBL"], format_func=lambda k: I.LEAGUES[k]["title"], horizontal=True,
                  key="ih_league")
HG.render(league)
