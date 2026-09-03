"""
NCAAF Hot Hand Engine — matchup-adjusted slate-wide leaderboard.

Adapted directly from NFL's own Hot Hand Engine (page 25), which itself is the NFL analog to
WNBA/NBA/NCAAMB's basketball Hot Hand Engine. One genuine, confirmed difference from NFL's
version: NCAAF's row structure uses short display keys (PassYds/RushYds/...) and CFBD's own
per-game column names (passing_YDS/rushing_YDS/...), not nflreadpy's column names -- handled
by ncaaf_projections.build_ncaaf_hot_hand_board using the same _ROW_FIELD_TO_CFBD_COL
translation map already proven in Matchup Lab.

EARLY-SEASON HONEST NOTE: Hot Hand signals are most meaningful once several weeks of real game
logs exist. Week 1 shows season-average rates (not recent-game recency), honestly labeled.
The 2025 baseline toggle below provides real game-level data from last season's full log.
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
game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER

C.base_css()
C.page_header("🔥", "NCAAF Hot Hand Engine",
             "Who has the best matchup this week — a slate-wide ranked view by recent form "
             "adjusted for this week's specific opponent, adapted from NFL's own Hot Hand Engine.")

if not sports.require_sport(["NCAAF"], "NCAAF Hot Hand Engine"):
    st.stop()


@st.cache_data(ttl=300, show_spinner=False)
def load_slate(date_str: str, stats_date_str: str):
    rows, meta = NSC.load_ncaaf_slate_cached(date_str)
    for r in rows:
        r["_slot"] = slot_of(game_dt(r.get("_game_date")))
    return rows, meta


def build_board(rows: list, stats_date_str: str):
    opps = sorted({r["Opp"] for r in rows if r.get("Opp")})
    opp_allowed = {opp: E.get_team_allowed_stats(opp, stats_date_str, n=None) for opp in opps}
    return P.build_ncaaf_hot_hand_board(rows, opp_allowed)


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
    help="Uses last season's real game logs as the recent-form signal. Week-by-week recency "
        "will emerge automatically as 2026 games are completed.")
stats_date_str = "2026-02-01" if show_2025_baseline else date_str

if show_2025_baseline:
    st.info("📊 **Showing 2025 season data as a baseline.** Today's matchups are current — "
           "the Hot Hand scores below use last season's per-game rates.", icon="📊")

with st.spinner("Loading slate..."):
    all_rows, meta = load_slate(date_str, stats_date_str)

if not all_rows:
    st.info("No players on the slate for this date — try a different date.", icon="🕐")
    st.stop()

slots_present = sorted({r["_slot"] for r in all_rows}, key=lambda s: SLOT_ORDER.get(s, 9))
c_slot, c_game = st.columns(2)
with c_slot:
    slot_pick = st.selectbox("Time slot", ["All slate"] + slots_present, key="hh_slot")
slot_rows = all_rows if slot_pick == "All slate" else [r for r in all_rows if r["_slot"] == slot_pick]

game_date_by_label = {r["GameLabel"]: r.get("_game_date") for r in slot_rows}
games_present = sorted(game_date_by_label, key=lambda g: game_date_by_label[g] or "~")
with c_game:
    game_pick = st.selectbox("Game", ["All games in this slot"] + games_present, key="hh_game")
final_rows = slot_rows if game_pick == "All games in this slot" else [r for r in slot_rows if r["GameLabel"] == game_pick]

with st.spinner("Building matchup-adjusted board..."):
    board = build_board(final_rows, stats_date_str)

if not board:
    st.info(
        "No players on the board yet — either the slate has no players with recent-game data, "
        "or the 2025 baseline toggle above isn't checked. Try checking the baseline box.",
        icon="🕐")
    st.stop()

# --- filters -----------------------------------------------------------------
positions_present = sorted({r["Position"] for r in board if r.get("Position")})
markets_present = sorted({r["Market"] for r in board})
cf1, cf2 = st.columns(2)
with cf1:
    pos_filter = st.multiselect("Position", positions_present, default=positions_present)
with cf2:
    mkt_filter = st.multiselect("Market", markets_present, default=markets_present)

filtered = [r for r in board if r.get("Position") in pos_filter and r.get("Market") in mkt_filter]
if not filtered:
    st.info("No results match the current filters.")
    st.stop()

st.markdown(f"**{len(filtered)} player-market combinations · {len(meta)} game(s) on slate**")

df = pd.DataFrame(filtered)[["Player", "Team", "Opp", "Position", "Market",
                              "Recent Avg", "Opp Allows", "Slate Avg", "Matchup Factor",
                              "Hot Hand Score", "Game"]]
st.dataframe(
    df.style.format({
        "Recent Avg": "{:.1f}", "Opp Allows": "{:.1f}", "Slate Avg": "{:.1f}",
        "Matchup Factor": "{:.2f}×", "Hot Hand Score": "{:.1f}",
    }, na_rep="—")
    .theme_gradient(cmap="RdYlGn", subset=["Matchup Factor", "Hot Hand Score"]),
    hide_index=True, width="stretch", height=500)

st.caption(
    "**Hot Hand Score** = Recent Avg × Matchup Factor. **Matchup Factor** = how much this "
    "opponent allows in this stat relative to the average across ALL opponents on this week's "
    "slate (not full-league) — > 1.0× means a softer matchup than the week's own baseline, "
    "< 1.0× means tighter. Matchup Factor is 1.00 (neutral) when this opponent's own allowed "
    "data isn't available yet. No pace adjustment — NFL/NCAAF has no 'possessions' equivalent "
    "the way basketball's per-100 normalization needs.")
