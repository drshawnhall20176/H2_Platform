"""
NCAAF Player Lines — recent-form trend charts, every market for one player's own position at
once, browsable by position first.

ADDED DIRECTLY ON REQUEST, the same real gap MLB Player Lines (page 26) closed for MLB: NCAAF
Matchup Lab (page 30) already has real trend charts, but it's a deep-dive tool -- one player,
filtered to only the markets that player's own row already cleared. This page is the fast,
browse-by-position version: pick QB / RB / WR-TE first, then see every real market for that
position group at once, regardless of whether this specific player happens to clear a rotation
floor on all of them. Built entirely on functions this session already built and tested
(get_player_season_games, build_trend_series, market_list/default_line/stat_key_for) -- no new
engine work needed, which is a real, concrete reason to build this now rather than earlier.

TWO REAL, HONEST CARRYOVERS FROM QB LAB/MATCHUP LAB, NOT REPEATED BY ACCIDENT:

  1. TD-ALLOWED-STYLE COLUMN NAMES (passing_TD/rushing_TD/receiving_TD) ARE STILL A PLAUSIBLE,
     NOT YET LIVE-VERIFIED GUESS. This page's own TD charts inherit that same real uncertainty --
     see ncaaf_engine._TD_STAT_COLS' own docstring for the full reasoning. Flagged here too,
     not silently assumed correct just because it's used elsewhere already.
  2. The 2025-baseline toggle, same real mechanism as QB Lab/Matchup Lab: redirects the STATS
     lookup to a real, completed prior season while the player SELECTOR itself stays on today's
     real slate -- see NCAAF QB Lab's own comment for the full reasoning on why these two dates
     must stay genuinely independent.
"""

import os

import streamlit as st
import components as C
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import plotly.graph_objects as go
from datetime import datetime
import pytz

import sports
import odds_api as O
import ncaaf_engine as E
import ncaaf_shared_cache as NSC
import ncaaf_projections as P

_active = sports.active()
eastern = pytz.timezone("US/Eastern")
game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER   # shared with Matchup Lab

C.base_css()
C.page_header("📉", "NCAAF Player Lines",
             "Recent-form trend vs. the line, every real market for one player's own position "
             "at once — the same fast, browse-by-position tool MLB's own Player Lines already "
             "provides, adapted for NCAAF's real position groups.")

if not sports.require_sport(["NCAAF"], "NCAAF Player Lines"):
    st.stop()


def get_api_key():
    try:
        return st.secrets["ODDS_API_KEY"]
    except Exception:
        return os.environ.get("ODDS_API_KEY")


@st.cache_data(ttl=300, show_spinner=False)
def load_slate(date_str: str):
    rows, meta = NSC.load_ncaaf_slate_cached(date_str)
    return rows


# Position-group -> chart spec. Yardage/reception entries carry a real default_line (line chart,
# dashed reference); TD entries carry no line at all (bar chart, matching Matchup Lab's own
# _render_bar_chart -- there's no established default_line for a touchdown count the way there
# is for a yardage market).
_POSITION_GROUPS = {
    "QB": {
        "positions": ("QB",),
        "line_markets": [("player_pass_yds", "Pass Yards"), ("player_rush_yds", "Rush Yards")],
        "td_charts": [("Passing TDs", lambda g: g.get("passing_TD") or 0),
                     ("Rushing TDs", lambda g: g.get("rushing_TD") or 0)],
    },
    "RB": {
        "positions": ("RB",),
        "line_markets": [("player_rush_yds", "Rush Yards"), ("player_receptions", "Receptions"),
                         ("player_reception_yds", "Receiving Yards")],
        "td_charts": [("Touchdowns", lambda g: (g.get("rushing_TD") or 0) + (g.get("receiving_TD") or 0))],
    },
    "WR / TE": {
        "positions": ("WR", "TE"),
        "line_markets": [("player_receptions", "Receptions"), ("player_reception_yds", "Receiving Yards")],
        "td_charts": [("Touchdowns", lambda g: (g.get("rushing_TD") or 0) + (g.get("receiving_TD") or 0))],
    },
}


c1, c2 = st.columns([2, 1])
with c1:
    target_date = st.date_input("Slate date", datetime.now(eastern))
with c2:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
date_str = target_date.strftime("%Y-%m-%d")

# 2025-baseline toggle -- same real mechanism as QB Lab/Matchup Lab (see their own comments for
# the full reasoning). date_str (the slate/player-picker date) stays independent of
# stats_date_str (what actually powers the charts below).
show_2025_baseline = st.checkbox(
    "📊 Show 2025 season baseline instead (2026 hasn't started yet)",
    help="Uses last season's real, complete game log as a starting-point baseline for the same "
        "real players — clearly a stand-in for 2026 form, not a claim about it. A transfer, "
        "true freshman, or backup who barely played in 2025 will honestly show no games at all, "
        "not a guessed baseline.")
stats_date_str = "2026-02-01" if show_2025_baseline else date_str

if show_2025_baseline:
    st.info("📊 **Showing 2025 season data as a baseline.** Today's real slate above is "
           "current — the game log below is last season's, since 2026 has no games yet. Real "
           "roster and scheme changes since 2025 aren't reflected here.", icon="📊")

with st.spinner("Loading this week's slate..."):
    rows = load_slate(date_str)

if not rows:
    st.info("No games scheduled for this date — try a different date.", icon="🕐")
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

games_present = sorted({r["GameLabel"] for r in slot_rows})
with c_game:
    game_pick = st.selectbox("Game", ["All games in this slot"] + games_present)
final_rows = slot_rows if game_pick == "All games in this slot" else [r for r in slot_rows if r["GameLabel"] == game_pick]

if not final_rows:
    st.info("No players match the current filters — try a different time slot or game.")
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
trend_log = P.build_trend_series(games)   # oldest -> newest, for left-to-right reading

# --- real lines, same opt-in fetch and honesty pattern as Matchup Lab -----------------------
api_key = get_api_key()
if not api_key:
    st.caption("🔑 No `ODDS_API_KEY` found — charts below show the model's own default line "
              "instead of this week's actual sportsbook number.")
elif st.button("📡 Fetch live lines", help="One fetch covers every player/market on this week's "
              "slate — switching players afterward reuses it at no extra API cost."):
    st.session_state["ncaaf_player_lines_fetch_odds"] = True

offers = []
if api_key and st.session_state.get("ncaaf_player_lines_fetch_odds"):
    try:
        with st.spinner("Fetching live lines..."):
            offers, _info = O.fetch_slate_props(date_str, api_key, list(_active.markets),
                                                sport=_active.odds_sport_key)
    except O.OddsAPIError as e:
        st.error(f"Odds API error: {e}")
live_lines = O.market_lines_for_player(offers, player_name, projections_module=P) if offers else {}

st.markdown(f"**{player_name} — recent-form trend vs. the line**")
if not trend_log:
    st.info(f"No real games on file for {player_name} yet" +
           (" in 2025" if show_2025_baseline else " this season") +
           " — try a different player, or check the 2025-baseline toggle above.")
    st.stop()

st.caption(f"{len(trend_log)} game(s) shown, oldest to newest"
          + (" (2025 season)" if show_2025_baseline else "") + ".")

xs = [f"Wk {g.get('week', '—')}" for g in trend_log]
line_specs = group["line_markets"]
td_specs = group["td_charts"]
n_charts = len(line_specs) + len(td_specs)
rows_of_cols = [st.columns(2) for _ in range((n_charts + 1) // 2)]
slots = [col for row in rows_of_cols for col in row][:n_charts]
slot_iter = iter(slots)

_market_col_by_key = {mk: c for mk, c, _d in P.market_list()}

for mkey, disp in line_specs:
    col = _market_col_by_key.get(mkey)
    stat_key = P.stat_key_for(col) if col else None
    with next(slot_iter):
        ys = [g.get(stat_key, 0.0) for g in trend_log] if stat_key else [0.0] * len(trend_log)
        line_val = live_lines.get(mkey)
        is_live = line_val is not None
        if line_val is None:
            line_val = P.default_line(mkey)
        hover = [f"{disp}: {y:g}<br>vs {g.get('opponent_team', '—')}" for y, g in zip(ys, trend_log)]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name=disp,
                                 line=dict(color="#3b82f6"), marker=dict(size=8),
                                 text=hover, hoverinfo="text"))
        if line_val is not None:
            ref_label = "Line" if is_live else "Model default"
            fig.add_hline(y=line_val, line_dash="dash", line_color="#f97316",
                         annotation_text=f"{ref_label}: {line_val:g}",
                         annotation_position="top left")
        fig.update_xaxes(type="category")
        fig.update_layout(template="plotly_white", height=240,
                          margin=dict(l=10, r=10, t=30, b=10), title=disp, showlegend=False)
        st.plotly_chart(fig, width="stretch")

for title, stat_fn in td_specs:
    with next(slot_iter):
        ys = [stat_fn(g) for g in trend_log]
        hover = [f"{title}: {y:g}<br>vs {g.get('opponent_team', '—')}" for y, g in zip(ys, trend_log)]
        fig = go.Figure(go.Bar(x=xs, y=ys, marker=dict(color="#3b82f6"), text=hover, hoverinfo="text"))
        fig.update_xaxes(type="category")
        fig.update_yaxes(dtick=1)
        fig.update_layout(template="plotly_white", height=240,
                          margin=dict(l=10, r=10, t=30, b=10), title=title, showlegend=False)
        st.plotly_chart(fig, width="stretch")

st.caption("Dashed line is this week's actual sportsbook number once fetched above; otherwise "
          "it's the model's own default line, clearly labeled as such, never presented as a "
          "live quote it isn't. TD charts have no line reference at all — no established default "
          "exists for a touchdown count the way one does for a yardage market. TD-allowed-style "
          "column names are a plausible, not yet live-verified guess — see this page's own "
          "module docstring.")
