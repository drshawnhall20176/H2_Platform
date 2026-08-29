"""
NCAAF Anytime TD Engine — who's most likely to find the end zone this week.

Adapted directly from NFL's own Anytime TD Engine (page 13). Same Bernoulli shrinkage method,
same honest model-only posture (no live odds wired in for v1). Genuine NCAAF difference: TD
column names are rushing_TD / receiving_TD / passing_TD, confirmed from the real 2025 refresh
log (they appeared explicitly in the printed stat-column list), unlike NFL's own rushing_tds /
receiving_tds / passing_tds (nflreadpy convention). See ncaaf_projections.
build_ncaaf_anytime_td_board's own docstring for the full method reasoning.

EARLY-SEASON NOTE: this page requires per-game log data to compute historical TD rates. The
2025 baseline toggle below provides real data from last season. Without it, every player shows
zero games in their log and the board stays empty -- the honest result, not a workaround.
"""

import streamlit as st
import components as C
import styling   # installs theme-proof .theme_gradient
import pandas as pd
from datetime import datetime
import pytz

import sports
import ncaaf_engine as E
import ncaaf_shared_cache as NSC
import ncaaf_projections as P

_active = sports.active()
eastern = pytz.timezone("US/Eastern")

C.base_css()
C.page_header("🎯", "NCAAF Anytime TD Engine",
             "Who's most likely to score — a ranked probability board for this week's "
             "touchdown-eligible players, adapted from NFL's own Anytime TD Engine using "
             "confirmed NCAAF column names.")

if not sports.require_sport(["NCAAF"], "NCAAF Anytime TD Engine"):
    st.stop()


@st.cache_data(ttl=300, show_spinner=False)
def load(date_str: str, stats_date_str: str):
    rows, meta = NSC.load_ncaaf_slate_cached(date_str)
    season_logs = {r["_pid"]: E.get_player_season_games(r["_pid"], stats_date_str)
                  for r in rows if r.get("_pid")}
    proj_rows = [dict(r, _recent_games=season_logs.get(r["_pid"]) or [])
                if stats_date_str != date_str else r for r in rows]
    board = P.build_ncaaf_anytime_td_board(proj_rows)
    return board, len(meta)


c1, c2 = st.columns([2, 1])
with c1:
    target_date = st.date_input("Slate date", datetime.now(eastern))
with c2:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
date_str = target_date.strftime("%Y-%m-%d")

show_2025_baseline = st.checkbox(
    "📊 Show 2025 season baseline instead (2026 hasn't started yet)",
    value=True,
    help="Uses last season's real game logs to compute TD rates. Without this, the board will "
        "be empty before 2026 Week 1 games are completed.")
stats_date_str = "2026-02-01" if show_2025_baseline else date_str

if show_2025_baseline:
    st.info("📊 **Showing 2025 season data as a baseline.** Today's matchups are current — "
           "TD probability rates are built from last season's real game logs.", icon="📊")

with st.spinner("Building TD probability board..."):
    board, n_games = load(date_str, stats_date_str)

if not board:
    st.info(
        "No players on the board yet — the TD Engine needs real per-game logs to compute "
        "scoring rates. Try checking the 2025 baseline toggle above.",
        icon="🕐")
    st.stop()

# --- position filter ---------------------------------------------------------
positions_present = sorted({r["Position"] for r in board if r.get("Position")})
pos_filter = st.multiselect("Position", positions_present, default=positions_present,
                            key="td_pos_filter")
filtered = [r for r in board if r.get("Position") in pos_filter]
if not filtered:
    st.info("No results match the current filters.")
    st.stop()

st.markdown(f"**{len(filtered)} players · {n_games} game(s) on slate**")

df = pd.DataFrame(filtered)[["Player", "Team", "Position", "Opp", "Game",
                              "TDGames", "GamesPlayed", "ModelProb", "Why"]]
df["ModelProb%"] = (df["ModelProb"] * 100).round(1).astype(str) + "%"
df = df.drop(columns=["ModelProb"])

st.dataframe(
    df.style.format({"TDGames": "{:.0f}", "GamesPlayed": "{:.0f}"}, na_rep="—"),
    hide_index=True, width="stretch", height=500)

st.caption(
    "**Model Prob** = Bayesian-shrunk Bernoulli rate: player's own historical TD-game rate "
    "(TD games ÷ total games on file) shrunk toward a prior of ~15% — the same empirical-Bayes "
    "approach NFL's own Anytime TD Engine uses. Ranking is by raw model probability, not "
    "Conviction ratio — a workhorse RB at 35% and a WR at 15% can both be genuine value "
    "depending on their role; dividing both by a shared 0.5 baseline wouldn't be meaningful "
    "the same way. Model-only, no live odds — see NFL's own Anytime TD Engine's own docstring "
    "for why live pricing hasn't been wired in yet (unverified offer shape).")
