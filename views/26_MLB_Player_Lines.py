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
game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER   # shared with Matchup Lab

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
    return E.build_slate(date_str)   # (rows, meta) -- meta carries each game's real gamePk,
                                     # needed for the same doubleheader-safe Game filter Matchup
                                     # Lab already uses (hitter rows themselves have GameLabel
                                     # but no gamePk/game_date of their own -- see the join below)


def apply_slot_and_game_filters(rows: list, label_key: str, key_prefix: str) -> list:
    """Time slot + Game filters — THE SAME shared pattern Best Bets and every Matchup Lab page
    already use, narrowing a busy night's player list before picking one. ADDED DIRECTLY ON
    REQUEST, closing a real, reported gap: the first version of this page only carried over
    Venue/Time SPLIT (which reshapes the DATA for an already-picked player) and missed these two
    (which narrow the SEARCH LIST itself) entirely.

    Real, doubleheader-safe Game disambiguation, not a simplified reimplementation -- reuses the
    same _gamePk-keyed logic Matchup Lab's own page already established after a real, confirmed
    bug (two legs of a doubleheader sharing the identical "Away @ Home" label used to collapse
    into one dropdown entry, silently discarding Game 2's own real info). Every row passed in
    MUST already carry _game_date and _gamePk -- pitcher rows have these natively; hitter rows
    need them joined on first, since build_slate's own hitter rows don't carry either (see the
    join in this page's own hitter-loading code below)."""
    for r in rows:
        r["_slot"] = slot_of(game_dt(r.get("_game_date")))
    slots_present = sorted({r["_slot"] for r in rows}, key=lambda s: SLOT_ORDER.get(s, 9))

    c_slot, c_game = st.columns(2)
    with c_slot:
        slot_pick = st.selectbox("Time slot", ["All slate"] + slots_present, key=f"{key_prefix}_slot")
    slot_rows = rows if slot_pick == "All slate" else [r for r in rows if r["_slot"] == slot_pick]
    if not slot_rows:
        return []

    pk_date: dict = {}
    label_pks: dict = {}
    for r in slot_rows:
        pk = r.get("_gamePk")
        if pk is None:
            continue
        pk_date.setdefault(pk, r.get("_game_date"))
        label_pks.setdefault(r[label_key], set()).add(pk)
    for lbl in label_pks:
        label_pks[lbl] = sorted(label_pks[lbl], key=lambda p: pk_date.get(p) or "")
    game_number_by_pk = {pk: i for pks in label_pks.values() for i, pk in enumerate(pks, 1)}
    games_present = sorted(pk_date, key=lambda p: pk_date[p] or "~")

    def _game_label_fmt(pk) -> str:
        base = next((r[label_key] for r in slot_rows if r.get("_gamePk") == pk), str(pk))
        if len(label_pks.get(base, [])) > 1:
            base = f"{base} (Game {game_number_by_pk.get(pk, 1)})"
        dt = game_dt(pk_date.get(pk))
        return f"{dt.strftime('%-I:%M %p ET')} — {base}" if dt is not None else base

    with c_game:
        game_pick = st.selectbox("Game", ["All games in this slot"] + games_present,
                                 format_func=lambda g: _game_label_fmt(g) if g != "All games in this slot" else g,
                                 key=f"{key_prefix}_game")
    return (slot_rows if game_pick == "All games in this slot"
           else [r for r in slot_rows if r.get("_gamePk") == game_pick])


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
    final_pitchers = apply_slot_and_game_filters(pitchers, "Game", "player_lines_p")
    if not final_pitchers:
        st.info("No probable starters match the current filters — try a different time slot or game.")
        st.stop()
    p_by_label = {f"{r['Pitcher']} ({r['Team']})": r for r in final_pitchers}
    label = st.selectbox("Pitcher (type to search)", sorted(p_by_label.keys()))
    selected = p_by_label[label]
    player_name, player_id = selected["Pitcher"], selected.get("_pid")
else:
    hitters, hitter_meta = load_hitters(date_str)
    if not hitters:
        st.info("No hitters found for this date. Pick a date with scheduled games.")
        st.stop()
    # Real join: build_slate's own hitter rows carry GameLabel but no _game_date/_gamePk of
    # their own (confirmed directly against _hitter_row's real return dict) -- meta has both,
    # keyed by the same label string, so it's joined on here rather than assumed present.
    meta_by_label = {m["label"]: m for m in hitter_meta}
    for r in hitters:
        m = meta_by_label.get(r.get("GameLabel"), {})
        r["_game_date"] = m.get("game_date")
        r["_gamePk"] = m.get("gamePk")
    final_hitters = apply_slot_and_game_filters(hitters, "GameLabel", "player_lines_h")
    if not final_hitters:
        st.info("No hitters match the current filters — try a different time slot or game.")
        st.stop()
    h_by_label = {f"{r['Hitter']} ({r['Team']})": r for r in final_hitters}
    label = st.selectbox("Batter (type to search)", sorted(h_by_label.keys()))
    selected = h_by_label[label]
    player_name, player_id = selected["Hitter"], selected.get("_pid")

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
