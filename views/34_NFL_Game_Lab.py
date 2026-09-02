"""
NFL Game Lab — game-level signals: moneyline win probability, projected spread and total,
PLUS a real, live injury report for both teams.

Adapted from NCAAF Game Lab (page 32), with two real, meaningful upgrades NFL makes possible:

  1. REAL INJURY REPORT (not a placeholder). Unlike NCAAF, which honestly shows an empty
     injury section explaining why no data exists, NFL has a real, league-mandated weekly injury
     report available via nfl_engine.get_team_injuries. This page shows it directly: players
     listed as Out/Doubtful/Questionable, with injury type and designation, sourced from
     nflreadpy's confirmed live injury data. The same real limitation NCAAF's own placeholder
     documents carries here too: this is the SCHEDULED start time's own most-recent report,
     not live in-game status -- injuries confirmed late Friday or Saturday may not be reflected
     if this page hasn't been refreshed since.

  2. NO DRIVES-BASED QUARTER/HALF SECTION. NFL has no equivalent to the NCAAF drives cache,
     so the quarter/half winner tier NCAAF Game Lab carries is genuinely absent here, not
     silently omitted. A real future addition if nflreadpy exposes drive-level data in a future
     release.

SCHEDULE FIELD NAMES: NFL uses home_score/away_score (confirmed from nfl_engine.get_schedule's
own output at line ~150, NOT home_points/away_points as NCAAF uses). Both new engine functions
(get_team_points_allowed, get_league_average_scoring) were confirmed against these field names
before use.
"""

import os

import streamlit as st
import components as C
import styling   # installs theme-proof .theme_gradient
import pandas as pd
from datetime import datetime
import pytz

import sports
import nfl_engine as E
import nfl_shared_cache as NSC
import nfl_projections as P

_active = sports.active()
eastern = pytz.timezone("US/Eastern")
game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER

C.base_css()
C.page_header("🏟️", "NFL Game Lab",
             "Moneyline win probability, projected spread and total, and real injury reports for "
             "both teams — the game-level modeling page for NFL slates, with real injury data "
             "NCAAF Game Lab's placeholder explains doesn't yet exist for college football.")

if not sports.require_sport(["NFL"], "NFL Game Lab"):
    st.stop()


@st.cache_data(ttl=300, show_spinner=False)
def load_slate_meta(date_str: str):
    _, meta = NSC.load_nfl_slate_cached(date_str)
    return meta


@st.cache_data(ttl=300, show_spinner=False)
def load_game(date_str: str, stats_date_str: str, home_abbr: str, away_abbr: str):
    """All game-level signals for one matchup -- cached per game.
    Two dates: date_str picks the game; stats_date_str picks which season's scoring rates power
    the simulation -- the same two-dates pattern QB Lab, Matchup Lab, Player Lines, and NCAAF
    Game Lab all use. stats_date_str = '2026-02-01' resolves to the 2025 NFL season via
    _infer_season's own Jan/Feb subtraction rule (month <= 2 -> season - 1)."""
    stats_season = E._infer_season(stats_date_str)
    stats_schedule = E.get_schedule(stats_season) if stats_season else []
    stats_week = E._resolve_week(stats_schedule, stats_date_str) or 999

    league_avg = E.get_league_average_scoring(stats_date_str)
    home_scoring = E.get_team_recent_scoring(home_abbr, stats_schedule, stats_week)
    away_scoring = E.get_team_recent_scoring(away_abbr, stats_schedule, stats_week)
    home_allowed = E.get_team_points_allowed(home_abbr, stats_date_str)
    away_allowed = E.get_team_points_allowed(away_abbr, stats_date_str)

    game_result = P.simulate_nfl_game(home_scoring, away_scoring, home_allowed, away_allowed,
                                      league_avg)

    # Injury report uses the CURRENT date's week, not stats_date_str -- we want this week's
    # real injury status, not last season's. date_str drives this, always.
    current_season = E._infer_season(date_str)
    current_schedule = E.get_schedule(current_season) if current_season else []
    current_week = E._resolve_week(current_schedule, date_str) or 1
    home_injuries = E.get_team_injuries(home_abbr, current_season, current_week) if current_season else []
    away_injuries = E.get_team_injuries(away_abbr, current_season, current_week) if current_season else []

    return game_result, home_scoring, away_scoring, home_allowed, away_allowed, league_avg, \
           home_injuries, away_injuries


# --- controls ----------------------------------------------------------------
c1, c2 = st.columns([2, 1])
with c1:
    target_date = st.date_input("Slate date", datetime.now(eastern))
with c2:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
date_str = target_date.strftime("%Y-%m-%d")

with st.spinner("Loading this week's NFL slate..."):
    meta = load_slate_meta(date_str)

if not meta:
    st.info("No NFL games scheduled for this date — try a different date.", icon="🕐")
    st.stop()

meta_sorted = sorted(meta, key=lambda m: m.get("game_date") or "~")
for _m in meta_sorted:
    _m["_slot"] = slot_of(game_dt(_m.get("game_date")))
slots_present = sorted({m["_slot"] for m in meta_sorted}, key=lambda s: SLOT_ORDER.get(s, 9))
slot_pick = st.selectbox("Time slot", ["All slate"] + slots_present, key="gl_slot")
slot_meta = meta_sorted if slot_pick == "All slate" else [m for m in meta_sorted if m["_slot"] == slot_pick]
game_options = {f"{m['away_name']} @ {m['home_name']}": m for m in slot_meta}
if not game_options:
    st.info("No games in this time slot — try a different slot.", icon="🕐")
    st.stop()
game_label = st.selectbox("Game", list(game_options.keys()))
selected = game_options[game_label]
home_name = selected["home_name"]
away_name = selected["away_name"]
# NFL meta stores team abbreviations as home_name/away_name -- confirmed by reading
# nfl_engine.build_slate's own meta dict construction (home_abbr / away_abbr keys)
home_abbr = selected.get("home_abbr") or selected.get("home_name")
away_abbr = selected.get("away_abbr") or selected.get("away_name")

# 2025-BASELINE TOGGLE — same real mechanism as every other NCAAF/NFL page this session.
# "2026-02-01" resolves to the 2025 NFL season via _infer_season's own confirmed Jan/Feb rule.
# Injury report always uses the current date's own real week regardless of this toggle -- we
# want actual current-week injury status, not last season's.
show_2025_baseline = st.checkbox(
    "📊 Use 2025 season baseline (2026 NFL hasn't started yet)",
    value=True,
    help="Uses last season's real scoring rates for both teams. The injury report below always "
        "reflects the current real week regardless of this toggle.")
stats_date_str = "2026-02-01" if show_2025_baseline else date_str

if show_2025_baseline:
    st.info("📊 **Using 2025 season data.** Scoring rates and simulation below use last season's "
           "real rates. Injury report reflects this week's actual status.", icon="📊")

with st.spinner(f"Simulating {away_name} @ {home_name} + loading injury reports..."):
    game_result, home_scoring, away_scoring, home_allowed, away_allowed, league_avg, \
    home_injuries, away_injuries = load_game(date_str, stats_date_str, home_abbr, away_abbr)

st.markdown(f"## {away_name} @ {home_name}")
st.caption(f"20,000 simulations · Normal score distribution · Odds-ratio blend · "
          f"League avg scoring: {league_avg:.1f} pts/team-game" if league_avg else
          "20,000 simulations · Limited data — early season or no completed games yet")

# --- Injury reports (the real NFL-specific upgrade) --------------------------
C.section_header("🏥", "Injury report — both teams")
st.caption("Source: NFL's own weekly injury report via nflreadpy. Most recent available "
          "report — injuries confirmed late Saturday may not be reflected without a refresh. "
          "Players listed as Out are confirmed out; Doubtful is very likely out; "
          "Questionable is genuinely uncertain.")

_STATUS_ORDER = {"Out": 0, "Doubtful": 1, "Questionable": 2, "Full": 3}


def _render_injuries(team_name: str, injuries: list) -> None:
    st.markdown(f"**{team_name}**")
    key_injuries = [p for p in injuries if p.get("status") in ("Out", "Doubtful", "Questionable")]
    key_injuries.sort(key=lambda p: _STATUS_ORDER.get(p.get("status", ""), 9))
    if not key_injuries:
        st.caption("No Out/Doubtful/Questionable players on the current injury report.")
        return
    df = pd.DataFrame([{
        "Player": p["player"], "Pos": p.get("position", "—"),
        "Status": p.get("status", "—"), "Injury": p.get("comment") or "—",
    } for p in key_injuries])

    def _color_status(val):
        if val == "Out":
            return "color: #ef4444"
        if val == "Doubtful":
            return "color: #f97316"
        if val == "Questionable":
            return "color: #eab308"
        return ""

    st.dataframe(df.style.applymap(_color_status, subset=["Status"]),
                hide_index=True, width="stretch")


icol1, icol2 = st.columns(2)
with icol1:
    _render_injuries(away_name, away_injuries)
with icol2:
    _render_injuries(home_name, home_injuries)

# --- Team strength indicators -----------------------------------------------
st.divider()
C.section_header("📊", "Team scoring context")
col1, col2 = st.columns(2)
with col1:
    st.markdown(f"**{away_name} (Away)**")
    if away_scoring:
        st.metric("Recent avg scored", f"{away_scoring['recent_avg']:.1f}",
                 delta=f"{away_scoring['recent_avg'] - away_scoring['season_avg']:+.1f} vs season",
                 delta_color="normal")
    else:
        st.caption("No completed games yet")
    if away_allowed:
        st.metric("Recent avg allowed", f"{away_allowed['recent_avg']:.1f}",
                 delta=f"{away_allowed['recent_avg'] - away_allowed['season_avg']:+.1f} vs season",
                 delta_color="inverse")
with col2:
    st.markdown(f"**{home_name} (Home)**")
    if home_scoring:
        st.metric("Recent avg scored", f"{home_scoring['recent_avg']:.1f}",
                 delta=f"{home_scoring['recent_avg'] - home_scoring['season_avg']:+.1f} vs season",
                 delta_color="normal")
    else:
        st.caption("No completed games yet")
    if home_allowed:
        st.metric("Recent avg allowed", f"{home_allowed['recent_avg']:.1f}",
                 delta=f"{home_allowed['recent_avg'] - home_allowed['season_avg']:+.1f} vs season",
                 delta_color="inverse")

st.caption("Recent = last 4 games. Positive delta on scoring is good (trending up), "
          "negative delta on allowed is good (trending tighter). No home-field advantage "
          "adjustment in v1 — a real, acknowledged simplification worth adding once graded "
          "results exist to validate the magnitude.")

# --- Moneyline / spread / total ---------------------------------------------
st.divider()
C.section_header("🎯", "Moneyline / spread / total")

if not game_result:
    st.info(
        "Not enough completed games on file for a reliable projection yet — this fills in "
        "as the season progresses. Come back after a few weeks of real games.",
        icon="🕐")
else:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(f"{away_name} ML", f"{game_result['away_win_prob']:.1%}")
    m2.metric(f"{home_name} ML", f"{game_result['home_win_prob']:.1%}")
    spread_label = (f"{home_name} -{abs(game_result['proj_spread']):.1f}"
                   if game_result["proj_spread"] > 0
                   else f"{away_name} -{abs(game_result['proj_spread']):.1f}")
    m3.metric("Projected spread", spread_label)
    m4.metric("Projected total", f"{game_result['proj_total']:.1f}")

    st.caption(f"Proj: {away_name} **{game_result['proj_away_score']:.1f}** — "
              f"{home_name} **{game_result['proj_home_score']:.1f}** · "
              f"Std: {game_result['away_std']:.1f} / {game_result['home_std']:.1f} · "
              f"{game_result['n_sims']:,} sims")

    with st.expander("How this works — and what it doesn't account for"):
        st.markdown(f"""
**Method:** each team's projected score = their own recent scoring rate, adjusted by how much
this specific opponent allows relative to league average (odds-ratio blend, the same math as
QB and player matchup projections on this platform). {game_result['n_sims']:,} games simulated
using a Normal distribution around each team's projected score.

**What this genuinely reflects:** recent offensive output vs. this specific opponent's recent
defensive performance. The injury report above is a real, separate signal — a key Out player
isn't yet factored into the scoring rates unless their absence already showed up in recent
games.

**What it does NOT reflect:** home-field advantage, weather, specific scheme matchups, or the
market's own price. Use the de-vigged moneylines section in Command Center to compare this
model's own probability against what DraftKings actually implies.
        """)

st.caption("v1 — no home-field advantage, no quarter/half breakdown (NFL drive data not yet "
          "available via nflreadpy for period-level simulation, unlike NCAAF's own drives cache "
          "built this session). Injury report reflects nflreadpy's most recent fetch.")
