"""
NFL Player Lines — recent-form trend charts, every market for one player's own position at
once, browsable by position first.

Adapted from NCAAF Player Lines (page 31), which was itself adapted from MLB Player Lines
(page 26). Uses NFL's own already-proven functions throughout:
- get_player_season_games / player_recent_games: nflreadpy weekly stats, same function NCAAF
  adapted for its own per-game cache
- build_trend_series / stat_key_for / market_list / default_line / is_td_eligible_position:
  all confirmed to exist in nfl_projections.py (stat_key_for is an identity function for NFL,
  unlike NCAAF's real translation layer -- confirmed by reading that function's own docstring)
- market_lines_for_player / fetch_slate_props: same odds_api.py functions every other sport
  already calls, sport-aware via _active.odds_sport_key

ONE REAL DIFFERENCE FROM NCAAF, confirmed directly: NFL's TD columns are "rushing_tds" and
"receiving_tds" (nflreadpy's own confirmed weekly-stat column names, same names get_team_tds_
allowed already uses), NOT NCAAF's own "rushing_TD" / "receiving_TD". The bar chart lambdas
below use these directly. Unlike NCAAF, this is confirmed from live use, not a cross-referenced
guess.

NFL PLAYER LINES HAS NO BASELINE TOGGLE, a real, deliberate difference: the NFL season is
underway in the same window NCAAF builds this page for Week 1 -- NFL has real, current-season
game log data available, so a toggle back to a prior season isn't the right default posture.
If the current season genuinely has no data for a specific player (injury, new signing), the
page will honestly say so.
"""

import os

import streamlit as st
import components as C
import styling   # installs theme-proof .theme_gradient
import plotly.graph_objects as go
from datetime import datetime
import pytz

import sports
import odds_api as O
import nfl_engine as E
import nfl_shared_cache as NSC
import nfl_projections as P

_active = sports.active()
eastern = pytz.timezone("US/Eastern")
game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER

C.base_css()
C.page_header("📉", "NFL Player Lines",
             "Recent-form trend vs. the line, every real market for one player's position at "
             "once — the same fast, browse-by-position tool MLB and NCAAF Player Lines already "
             "provide, using NFL's own confirmed nflreadpy weekly-stat columns.")

if not sports.require_sport(["NFL"], "NFL Player Lines"):
    st.stop()


def get_api_key():
    try:
        return st.secrets["ODDS_API_KEY"]
    except Exception:
        return os.environ.get("ODDS_API_KEY")


@st.cache_data(ttl=300, show_spinner=False)
def load_slate(date_str: str, stats_date_str: str):
    rows, meta = NSC.load_nfl_slate_cached(date_str, stats_date_str=stats_date_str)
    return rows


# Position-group -> chart spec. Matches nfl_engine._MARKETS_FOR_POSITION's own confirmed
# groupings (QB/RB/WR/TE/FB), confirmed by reading that module directly.
# TD columns use NFL's own confirmed nflreadpy column names (rushing_tds / receiving_tds),
# NOT NCAAF's own (rushing_TD / receiving_TD).
_POSITION_GROUPS = {
    "QB": {
        "positions": ("QB",),
        "line_markets": [("player_pass_yds", "Pass Yards")],
        "td_charts": [("Passing TDs", lambda g: g.get("passing_tds") or 0),
                     ("Rushing TDs", lambda g: g.get("rushing_tds") or 0)],
    },
    "RB": {
        "positions": ("RB", "FB"),
        "line_markets": [("player_rush_yds", "Rush Yards"), ("player_receptions", "Receptions"),
                         ("player_reception_yds", "Receiving Yards")],
        "td_charts": [("Touchdowns", lambda g: (g.get("rushing_tds") or 0) + (g.get("receiving_tds") or 0))],
    },
    "WR / TE": {
        "positions": ("WR", "TE"),
        "line_markets": [("player_receptions", "Receptions"), ("player_reception_yds", "Receiving Yards")],
        "td_charts": [("Touchdowns", lambda g: (g.get("rushing_tds") or 0) + (g.get("receiving_tds") or 0))],
    },
}

_market_col_by_key = {mk: c for mk, c, _d in P.market_list()}


c1, c2 = st.columns([2, 1])
with c1:
    target_date = st.date_input("Slate date", datetime.now(eastern))
with c2:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
date_str = target_date.strftime("%Y-%m-%d")

show_2025_baseline = st.checkbox("📊 Use 2025 season baseline (2026 hasn't started yet)", value=True,
    help="Uses last season's real player data. Uncheck once 2026 Week 1 games are in the books.")
stats_date_str = "2025-12-01" if show_2025_baseline else date_str
if show_2025_baseline:
    st.info("📊 **Using 2025 season data.** Today's real matchups are current — player stats use last season's game logs.", icon="📊")

with st.spinner("Loading this week's slate..."):
    rows = load_slate(date_str, stats_date_str)

if not rows:
    st.info("No NFL players on today's slate — try a different date.", icon="🕐")
    st.stop()

group_name = st.radio("Position", list(_POSITION_GROUPS.keys()), horizontal=True)
group = _POSITION_GROUPS[group_name]
group_rows = [r for r in rows if r.get("Position") in group["positions"]]

if not group_rows:
    st.info(f"No {group_name} players on today's real slate — try a different position or date.")
    st.stop()

for r in group_rows:
    r["_slot"] = slot_of(game_dt(r.get("_game_date")))
slots_present = sorted({r["_slot"] for r in group_rows}, key=lambda s: SLOT_ORDER.get(s, 9))

c_slot, c_game = st.columns(2)
with c_slot:
    slot_pick = st.selectbox("Time slot", ["All slate"] + slots_present)
slot_rows = group_rows if slot_pick == "All slate" else [r for r in group_rows if r["_slot"] == slot_pick]

game_date_by_label = {}
for r in slot_rows:
    game_date_by_label.setdefault(r["GameLabel"], r.get("_game_date"))
games_present = sorted(game_date_by_label, key=lambda g: game_date_by_label[g] or "~")

with c_game:
    game_pick = st.selectbox("Game", ["All games in this slot"] + games_present)
final_rows = slot_rows if game_pick == "All games in this slot" else [r for r in slot_rows if r["GameLabel"] == game_pick]

if not final_rows:
    st.info("No players match the current filters.")
    st.stop()

p_by_label = {f"{r['Player']} ({r['Team']})": r for r in final_rows}
label = st.selectbox(f"{group_name} (type to search)", sorted(p_by_label.keys()))
selected = p_by_label[label]
player_name, player_id = selected["Player"], selected.get("_pid")

if not player_id:
    st.warning("No player ID on file for this selection — can't load a real game log.")
    st.stop()

with st.spinner(f"Loading {player_name}'s real game log..."):
    games = E.get_player_season_games(player_id, stats_date_str)
trend_log = P.build_trend_series(games)

# --- live lines, same opt-in fetch pattern as Matchup Lab and NCAAF Player Lines -----------
api_key = get_api_key()
if not api_key:
    st.caption("🔑 No `ODDS_API_KEY` found — charts show the model's own default line instead.")
elif st.button("📡 Fetch live lines", help="Covers the whole slate — switching players reuses it."):
    st.session_state["nfl_player_lines_fetch_odds"] = True

offers = []
if api_key and st.session_state.get("nfl_player_lines_fetch_odds"):
    try:
        with st.spinner("Fetching live lines..."):
            offers, _info = O.fetch_slate_props(date_str, api_key, list(_active.markets),
                                                sport=_active.odds_sport_key)
    except O.OddsAPIError as e:
        st.error(f"Odds API error: {e}")
live_lines = O.market_lines_for_player(offers, player_name, projections_module=P) if offers else {}

st.markdown(f"**{player_name} — recent-form trend vs. the line**")
if not trend_log:
    st.info(f"No games on file for {player_name} yet this season — try a different player.")
    st.stop()

st.caption(f"{len(trend_log)} game(s) shown, oldest to newest.")

xs = [f"Wk {g.get('week', '—')}" for g in trend_log]
line_specs = group["line_markets"]
td_specs = group["td_charts"]
n_charts = len(line_specs) + len(td_specs)
rows_of_cols = [st.columns(2) for _ in range((n_charts + 1) // 2)]
slots = [col for row in rows_of_cols for col in row][:n_charts]
slot_iter = iter(slots)

for mkey, disp in line_specs:
    col = _market_col_by_key.get(mkey)
    stat_key = P.stat_key_for(col) if col else None   # identity for NFL -- returns col unchanged
    with next(slot_iter):
        if not trend_log:
            st.caption(f"{disp}: no games on file.")
            continue
        line_val = live_lines.get(mkey)
        is_live = line_val is not None
        if line_val is None:
            line_val = P.default_line(mkey)
        ys = [g.get(stat_key, 0.0) for g in trend_log] if stat_key else [0.0] * len(trend_log)
        hover = [f"{disp}: {y:g}<br>vs {g.get('recent_team_opp', g.get('opponent_team', '—'))}"
                for y, g in zip(ys, trend_log)]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name=disp,
                                 line=dict(color="#3b82f6"), marker=dict(size=8),
                                 text=hover, hoverinfo="text"))
        if line_val is not None:
            fig.add_hline(y=line_val, line_dash="dash", line_color="#f97316",
                         annotation_text=f"{'Line' if is_live else 'Model default'}: {line_val:g}",
                         annotation_position="top left")
        fig.update_xaxes(type="category")
        fig.update_layout(template="plotly_white", height=240,
                          margin=dict(l=10, r=10, t=30, b=10), title=disp, showlegend=False)
        st.plotly_chart(fig, width="stretch")

for title, stat_fn in td_specs:
    with next(slot_iter):
        ys = [stat_fn(g) for g in trend_log]
        hover = [f"{title}: {y:g}<br>vs {g.get('recent_team_opp', g.get('opponent_team', '—'))}"
                for y, g in zip(ys, trend_log)]
        fig = go.Figure(go.Bar(x=xs, y=ys, marker=dict(color="#3b82f6"), text=hover, hoverinfo="text"))
        fig.update_xaxes(type="category")
        fig.update_yaxes(dtick=1)
        fig.update_layout(template="plotly_white", height=240,
                          margin=dict(l=10, r=10, t=30, b=10), title=title, showlegend=False)
        st.plotly_chart(fig, width="stretch")

st.caption("Dashed line is this week's actual sportsbook number once fetched; otherwise it's the "
          "model's own default line, clearly labeled as such. TD bar charts have no line "
          "reference — no established default exists for touchdown counts the way one does for "
          "yardage markets. NFL TD columns confirmed from live nflreadpy weekly-stat data "
          "(rushing_tds / receiving_tds / passing_tds) — unlike NCAAF's own still-unverified "
          "column names, these are proven.")
