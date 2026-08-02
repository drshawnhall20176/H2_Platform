"""
Player Lines — MLB recent-form trend charts, pitcher or batter.

The same "is she trending toward or away from the number" chart WNBA/NBA/NCAAMB's own Matchup
Lab already has, built for MLB specifically -- ADDED DIRECTLY ON REQUEST. Reuses the exact same
venue/time split filters MLB's own pitch-level Matchup Lab already uses (best_bets_data.
render_split_selector), and the same real-line-vs-model-default honesty pattern the basketball
trend charts already established: a dashed reference line shows tonight's actual sportsbook
number once fetched, the model's own default line otherwise, always clearly labeled as which.

PITCHER: Outs, Hits Allowed, Earned Runs, Strikeouts -- built on mlb_engine.get_pitcher_recent_
games (a thin wrapper around the same real starts data the pitcher regression tracker uses).

BATTER: Hits, Total Bases, Hits+Runs+RBIs, HR, and Strikeouts -- built on mlb_engine.
get_hitter_recent_games. HRR here is the REAL per-game sum (hits+runs+rbi actually recorded),
not the simulated market probability build_best_bets computes elsewhere.
"""

import streamlit as st
import components as C
import plotly.graph_objects as go
from datetime import datetime
import pytz

import sports
import mlb_engine as E
import projections as P
import odds_api as O
import best_bets_data as BBD

eastern = pytz.timezone("US/Eastern")

C.base_css()
C.page_header("📉", "Player Lines",
             "Recent-form trend vs. the line, pitcher or batter — the same real chart WNBA/NBA/"
             "NCAAMB's own Matchup Lab already has, built for MLB's real markets.")

if not sports.require_sport(["MLB"], "Player Lines"):
    st.stop()


@st.cache_data(ttl=300, show_spinner="Loading probable starters…")
def load_pitchers(date_str: str):
    return E.build_pitching_slate(date_str)


@st.cache_data(ttl=300, show_spinner="Loading hitters…")
def load_hitters(date_str: str):
    rows, _meta = E.build_slate(date_str)
    return rows


# Pitcher chart spec: (stat_key on get_pitcher_recent_games's own row, display market name,
# hardcoded default line). Matches DEFAULT_LINES exactly -- reused, not reinvented.
PITCHER_CHARTS = [
    ("outs", "Pitcher Outs", P.DEFAULT_LINES["Pitcher Outs"]),
    ("hits_allowed", "Pitcher Hits Allowed", P.DEFAULT_LINES["Pitcher Hits Allowed"]),
    ("earned_runs", "Pitcher Earned Runs", P.DEFAULT_LINES["Pitcher Earned Runs"]),
    ("strikeouts", "Pitcher Strikeouts", P.DEFAULT_LINES["Pitcher Strikeouts"]),
]
# Batter chart spec: same shape as PITCHER_CHARTS. "Batter HR"'s own 0.5 default lives here
# directly rather than in DEFAULT_LINES, matching how every other Batter HR call site on this
# platform already sources it (real_line_or_default("Batter HR", ..., 0.5) -- hardcoded at the
# call site, not centrally).
BATTER_CHARTS = [
    ("hits", "Batter Total Hits", P.DEFAULT_LINES["Batter Total Hits"]),
    ("total_bases", "Batter Total Bases", P.DEFAULT_LINES["Batter Total Bases"]),
    ("hrr", "Batter Hits+Runs+RBIs", P.DEFAULT_LINES["Batter Hits+Runs+RBIs"]),
    ("hr", "Batter HR", 0.5),
    ("strikeouts", "Batter Strikeouts", P.DEFAULT_LINES["Batter Strikeouts"]),
]

c1, c2 = st.columns([2, 1])
with c1:
    date_str = st.date_input("Slate date", datetime.now(eastern)).strftime("%Y-%m-%d")
with c2:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

player_type = st.radio("Player type", ["Pitcher", "Batter"], horizontal=True)

if player_type == "Pitcher":
    pitchers = load_pitchers(date_str)
    if not pitchers:
        st.info("No probable starters found for this date. Pick a date with scheduled games.")
        st.stop()
    p_by_label = {f"{r['Pitcher']} ({r['Team']})": r for r in pitchers}
    label = st.selectbox("Pitcher (type to search)", sorted(p_by_label.keys()))
    selected = p_by_label[label]
    player_name, player_id = selected["Pitcher"], selected.get("_pid")
else:
    hitters = load_hitters(date_str)
    if not hitters:
        st.info("No hitters found for this date. Pick a date with scheduled games.")
        st.stop()
    h_by_label = {f"{r['Player']} ({r['Team']})": r for r in hitters}
    label = st.selectbox("Batter (type to search)", sorted(h_by_label.keys()))
    selected = h_by_label[label]
    player_name, player_id = selected["Player"], selected.get("_pid")

if not player_id:
    st.warning("No player ID on file for this selection — can't load a real game log.")
    st.stop()

venue_split, time_split = BBD.render_split_selector(key_prefix="player_lines")

# --- real lines, same honesty pattern as WNBA/NBA/NCAAMB's own trend charts -------------------
api_key = BBD.get_odds_api_key()
if not api_key:
    st.caption("🔑 No `ODDS_API_KEY` found — charts below show the model's own default line "
              "instead of tonight's actual sportsbook number.")
else:
    preferred_book = st.session_state.get("_preferred_book_mlb", O.DEFAULT_BOOK)
    BBD.ensure_mlb_offers_session_state(date_str, api_key, preferred_book)

offers = st.session_state.get(f"_real_offers_MLB_{date_str}") or []
live_lines = O.market_lines_for_player(offers, player_name, projections_module=P) if offers else {}

season = int(date_str[:4])
if player_type == "Pitcher":
    games = E.get_pitcher_recent_games(player_id, season, before_date=date_str,
                                       venue=venue_split, time_of_day=time_split, n=10)
    chart_spec = PITCHER_CHARTS
else:
    games = E.get_hitter_recent_games(player_id, season, before_date=date_str,
                                      venue=venue_split, time_of_day=time_split, n=10)
    chart_spec = BATTER_CHARTS

st.markdown(f"**{player_name} — recent-form trend vs. the line**")
if not games:
    st.info(f"No recent games on file for {player_name} yet with these filters — try loosening "
           f"the venue/time split, or check back once more games are logged this season.")
    st.stop()

st.caption(f"{len(games)} game(s) shown, oldest to newest, matching the current venue/time split.")

xs = [g.get("game_date", "—")[5:10] for g in games]   # MM-DD, short enough for a small chart

n_charts = len(chart_spec)
rows_of_cols = [st.columns(2) for _ in range((n_charts + 1) // 2)]
slots = [col for row in rows_of_cols for col in row][:n_charts]

for (stat_key, disp, default_line), slot in zip(chart_spec, slots):
    with slot:
        ys = [g.get(stat_key, 0.0) for g in games]
        odds_key = P.MLB_MARKET_TO_ODDS_KEY.get(disp)
        line_val = live_lines.get(odds_key) if odds_key else None
        is_live = line_val is not None
        if line_val is None:
            line_val = default_line
        hover = [f"{disp}: {y:g}" for y in ys]
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

st.caption("Dashed line is the real sportsbook number once fetched above (needs `ODDS_API_KEY` "
          "set); otherwise it's this platform's own default line, clearly labeled as such, "
          "never presented as a live quote it isn't.")
