"""
NFL Anytime TD Engine — who's most likely to find the end zone this week.

THE NFL ANALOG TO MLB'S DINGER ENGINE, NOT A PORT OF THE FOUR CORE MARKETS: those four (Pass
Yards, Rush Yards, Receptions, Receiving Yards) are continuous stats priced with an Over/Under
line. Scoring a touchdown is a single, high-variance, boom/bust BINARY outcome — the honest
football counterpart to "will this player hit a home run," not another yardage market. See
nfl_projections.build_anytime_td_board's own docstring for the full modeling reasoning (a direct
empirical-Bayes shrinkage of each player's own scoring rate, not a bootstrap-over-yards approach).

V1, MODEL-ONLY, NO LIVE ODDS — a deliberate scoping choice, not an oversight: the four Core
markets' live-odds integration was built and verified against a real, confirmed Over/Under offer
shape (see odds_api.py). Anytime TD is typically a single-sided Yes/No market at sportsbooks, a
different offer shape that hasn't been verified here yet. Rather than guess at that shape and risk
a silent parsing bug, this ships the same way every sport's FIRST board did — the model's own
ranked probabilities, clearly labeled as model-only, with live pricing a real follow-on once that
shape is confirmed the same rigorous way the Core markets' was.
"""

import streamlit as st
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import pandas as pd
from datetime import datetime
import pytz

import sports
import nfl_engine as E
import nfl_projections as P

_active = sports.active()
eastern = pytz.timezone("US/Eastern")

st.title("🎯 Anytime TD Engine")
st.caption("Who's most likely to score — a ranked probability board for a single binary outcome, "
          "the honest NFL counterpart to Dinger Engine's home-run board. Model-only for now — "
          "see the note below for why live odds aren't wired in yet.")

if not sports.require_sport(["NFL"], "Anytime TD Engine"):
    st.stop()

st.info("**Model-only board, not yet priced against live odds.** Anytime TD is typically offered "
       "as a single-sided Yes/No market at sportsbooks — a different shape than the four Core "
       "markets' Over/Under, and one this platform hasn't verified against a real response yet. "
       "Rather than guess at that shape, this shows the model's own ranked probabilities only, "
       "the same way every sport's first board here started before live pricing was added.",
       icon="ℹ️")


@st.cache_data(ttl=300, show_spinner=False)
def load_board(date_str: str):
    rows, meta = E.build_slate(date_str)
    board = P.build_anytime_td_board(rows, seed=None)
    return board, len(meta)


c1, c2 = st.columns([2, 1])
with c1:
    target_date = st.date_input("Slate date", datetime.now(eastern))
with c2:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
date_str = target_date.strftime("%Y-%m-%d")

with st.spinner("Building this week's Anytime TD board..."):
    board, n_games = load_board(date_str)

if not board:
    st.info("No projectable players for this date. Pick a date within an NFL week with a real slate.")
    st.stop()

st.caption(f"{n_games} game(s) · {len(board)} player(s) with a recent-game log to project from")

# --- position filter ---------------------------------------------------------
positions_present = sorted({b["Position"] for b in board})
pos_pick = st.multiselect("Position", positions_present, default=positions_present)
filtered = [b for b in board if b["Position"] in pos_pick] if pos_pick else board

if not filtered:
    st.info("No players match the current position filter.")
    st.stop()

# --- leaderboard ---------------------------------------------------------
st.subheader("🏆 Leaderboard")
top_n = st.slider("Show top N", 5, min(50, len(filtered)), min(25, len(filtered)))
top = filtered[:top_n]

ldf = pd.DataFrame(top)[["Player", "Position", "Team", "Opp", "ModelProb", "Fair", "TDGames", "GamesPlayed"]]
ldf = ldf.rename(columns={"ModelProb": "Model %", "Fair": "Fair Odds", "TDGames": "TD Games",
                          "GamesPlayed": "Games on File"})
st.dataframe(
    ldf.style.format({"Model %": "{:.0%}"}, na_rep="—")
    .theme_gradient(cmap="RdYlGn", subset=["Model %"]),
    hide_index=True, use_container_width=True,
)
st.caption("**Model %** is an empirical-Bayes-shrunk rate (each player's own recent TD-scored-or-"
          "not rate, pulled toward a neutral baseline by how many real games back it — a 2-game "
          "sample gets pulled hard, a 5-game sample barely moves), not a bootstrap over a yardage "
          "line. **Fair Odds** is the break-even American price at that probability, before any "
          "sportsbook's own vig — a real number to compare a live line against once you have one, "
          "not a recommendation to bet at it.")

# --- by position breakdown ---------------------------------------------------
st.subheader("By position")
tabs = st.tabs([f"{p}" for p in positions_present])
for tab, pos in zip(tabs, positions_present):
    with tab:
        pos_rows = [b for b in board if b["Position"] == pos][:15]
        if not pos_rows:
            st.caption("No players at this position on the current slate.")
            continue
        pdf = pd.DataFrame(pos_rows)[["Player", "Team", "Opp", "ModelProb", "Fair", "Why"]]
        pdf = pdf.rename(columns={"ModelProb": "Model %", "Fair": "Fair Odds"})
        st.dataframe(
            pdf.style.format({"Model %": "{:.0%}"}, na_rep="—")
            .theme_gradient(cmap="RdYlGn", subset=["Model %"]),
            hide_index=True, use_container_width=True,
        )

st.caption("v1 signal — no opponent adjustment (a defense that's allowed more TDs lately isn't "
          "yet folded into this board, the same 'raw signals, not one blended number' philosophy "
          "Matchup Lab follows), no goal-line-role or red-zone-target-share detail beyond what a "
          "recent TD-scored-or-not rate already captures implicitly. A player new to a role (a "
          "recent trade, an injury opening up touches) will look weaker here than their CURRENT "
          "role deserves until enough games accumulate to reflect it — same honest limitation "
          "every recency-window model on this platform carries.")
