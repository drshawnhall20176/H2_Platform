"""
NCAAF Game Lab — game-level signals: moneyline win probability, projected spread and total,
quarter winners, and half winners. The first game-level modeling page on this platform for
NCAAF, specifically built for games where DK has no player props available.

TWO DISTINCT DATA TIERS, with real, honest provenance per tier:

  TIER 1 — SCHEDULE-BASED (shown by default, Week-1 ready, fully proven):
    Moneyline win probability, projected spread, projected total. Built entirely from the
    already-cached schedule's home_points/away_points -- the same data source every other NCAAF
    signal already uses. Zero new data dependencies. Available as soon as any completed games
    exist in the schedule cache.

  TIER 2 — DRIVES-BASED (opt-in checkbox, explicitly flagged as unverified):
    Quarter winner probabilities (Q1, Q2, Q3, Q4) and half winner probabilities (H1, H2).
    Requires the drives cache (ncaaf_data.DRIVES_PATH), which was built against CFBD field
    names cross-confirmed from third-party sources -- not CFBD's own official schema verified
    directly -- and whose start_period field this tier's per-period bucketing entirely depends on.
    Gated behind an opt-in checkbox for exactly this reason, same posture as Command Center's
    own de-vigged moneylines section (which costs real API quota) -- this costs real
    data-integrity trust until one real, live completed-week drive response verifies it.

METHOD: Normal distribution for full-game scores (football scoring as a sum of fixed-chunk
events: 3/6/7/8 pts, CLT applies -- much better fit than Poisson for final scores). Odds-ratio
blend for projected score (same math as QB matchup projections, applied at the game level).
Standard deviation floored at 7 pts for full game, 3 pts per period -- minimum meaningful
football score variance. See ncaaf_projections.simulate_ncaaf_game's own docstring for full
reasoning.
"""

import os

import streamlit as st
import components as C
import styling  # installs theme-proof .theme_gradient
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
C.page_header("🏟️", "NCAAF Game Lab",
             "Moneyline win probability, projected spread/total, and (when drive data is "
             "available) quarter and half winner probabilities — the first game-level modeling "
             "on this platform, built specifically for NCAAF slates where player props aren't "
             "available.")

if not sports.require_sport(["NCAAF"], "NCAAF Game Lab"):
    st.stop()


@st.cache_data(ttl=300, show_spinner=False)
def load_slate_meta(date_str: str):
    """Load just the game-level meta, not full player rows -- Game Lab doesn't need player data."""
    _, meta = NSC.load_ncaaf_slate_cached(date_str)
    return meta


@st.cache_data(ttl=300, show_spinner=False)
def load_game(date_str: str, stats_date_str: str, home_name: str, away_name: str):
    """All signals for one specific game -- cached per game so switching games reuses data.

    TWO DIFFERENT DATES, same real pattern as QB Lab/Matchup Lab/Player Lines: date_str picks
    which GAME to analyze (tomorrow's real 2026 matchup); stats_date_str picks which season's
    own historical data POWERS the scoring rates. When the baseline toggle is active,
    stats_date_str resolves to 2025 via _infer_season("2026-02-01") -- the full, complete prior
    season -- so the simulation uses last season's real scoring context for both teams."""
    # Stats date drives schedule/week for scoring rate lookups
    stats_season = E._infer_season(stats_date_str)
    stats_schedule = E.get_schedule(stats_season) if stats_season else []
    stats_week = E._resolve_week(stats_schedule, stats_date_str) or 999

    league_avg = E.get_league_average_scoring(stats_date_str)

    home_scoring = E.get_team_recent_scoring(home_name, stats_schedule, stats_week)
    away_scoring = E.get_team_recent_scoring(away_name, stats_schedule, stats_week)
    home_allowed = E.get_team_points_allowed(home_name, stats_date_str)
    away_allowed = E.get_team_points_allowed(away_name, stats_date_str)

    game_result = P.simulate_ncaaf_game(home_scoring, away_scoring, home_allowed, away_allowed,
                                        league_avg)

    home_period = E.get_team_period_scoring(home_name, stats_date_str)
    away_period = E.get_team_period_scoring(away_name, stats_date_str)
    period_result = P.simulate_period_winners(home_period, away_period)

    return game_result, period_result, home_scoring, away_scoring, home_allowed, away_allowed, league_avg


# --- controls ----------------------------------------------------------------
c1, c2 = st.columns([2, 1])
with c1:
    target_date = st.date_input("Slate date", datetime.now(eastern))
with c2:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
date_str = target_date.strftime("%Y-%m-%d")

with st.spinner("Loading this week's slate..."):
    meta = load_slate_meta(date_str)

if not meta:
    st.info("No games scheduled for this date — try a different date.", icon="🕐")
    st.stop()

# Sort by real game time, not alphabetically -- same established pattern as Matchup Lab
meta_sorted = sorted(meta, key=lambda m: m.get("game_date") or "~")
game_options = {f"{m['away_name']} @ {m['home_name']}": m for m in meta_sorted}
game_label = st.selectbox("Game", list(game_options.keys()))
selected = game_options[game_label]
home_name = selected["home_name"]
away_name = selected["away_name"]

# 2025-BASELINE TOGGLE — same real mechanism as QB Lab/Matchup Lab/Player Lines.
# This is the direct fix for "no completed games yet": the 2025 schedule and scoring data
# are already cached (refresh_ncaaf.py always pulls both years since the fix earlier this
# session), so _infer_season("2026-02-01") correctly resolves to 2025 and returns a full
# season of real scoring rates for both teams.
show_2025_baseline = st.checkbox(
    "📊 Use 2025 season baseline (2026 hasn't started yet)",
    value=True,   # on by default since Week 1 has no data yet -- the common case right now
    help="Uses last season's real scoring rates for both teams. Real transfers, scheme changes, "
        "and personnel differences since 2025 aren't reflected -- clearly a stand-in, not a "
        "claim about 2026 form. The model will update automatically as 2026 games are played.")
stats_date_str = "2026-02-01" if show_2025_baseline else date_str

if show_2025_baseline:
    st.info("📊 **Using 2025 season data.** Today's real matchup is current — scoring rates "
           "below are last season's. Roster and scheme changes since 2025 aren't reflected.",
           icon="📊")

show_period = st.checkbox(
    "📡 Show quarter and half winner probabilities (requires drive data — flagged as unverified)",
    help="Period-level probabilities are computed from the drives cache, which was built against "
        "CFBD field names cross-confirmed from third-party sources, not CFBD's own official schema "
        "directly. The moneyline section above uses schedule data only and is always reliable.")

with st.spinner(f"Simulating {away_name} @ {home_name}..."):
    game_result, period_result, home_scoring, away_scoring, home_allowed, away_allowed, league_avg = load_game(
        date_str, stats_date_str, home_name, away_name)

st.markdown(f"## {away_name} @ {home_name}")
st.caption(f"20,000 simulations · Normal score distribution · Odds-ratio blend · "
          f"League avg scoring: {league_avg:.1f} pts/team-game" if league_avg else
          "20,000 simulations · No completed 2026 games yet — check the \"Use 2025 season baseline\" box above")

# --- Team strength indicators -----------------------------------------------
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

st.caption("Recent = last 4 games (n=4). Delta vs season shown; positive delta on scoring is good "
          "(trending up), negative delta on allowed is good (trending tighter). Note: no "
          "home-field advantage adjustment in this model — a real, acknowledged simplification "
          "for v1. Worth adding once graded results can validate the magnitude.")

# --- Moneyline / spread / total (Tier 1, schedule-based) --------------------
st.divider()
C.section_header("🎯", "Moneyline / spread / total — schedule data")

if not game_result:
    st.info(
        "Not enough completed games on file for a reliable projection yet — this page's signals "
        "fill in as the season progresses. Come back after a few games have been played.",
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

    with st.expander("What the win probability means — and what it doesn't"):
        st.markdown(f"""
This is a **model probability**, not a market price. It answers: given each team's own recent
scoring rate and recent points allowed, adjusted for this specific matchup, how often does each
team win across {game_result['n_sims']:,} simulated games?

**What it genuinely reflects:** each team's own recent offensive output vs. this specific
opponent's recent defensive performance, via an odds-ratio blend (the same math as QB
matchup projections on this platform).

**What it does NOT reflect:**
- Home-field advantage (not modeled in v1)
- Injuries, weather, travel, or scheme-specific adjustments
- Quarterback-specific passing game — this is team-level aggregate offense/defense, not
  QB-grade
- The market's own probability (de-vigged from DK's moneyline) — use the de-vigged moneylines
  section in Command Center to compare this model against what the market actually believes

**When this is most/least useful:** most useful for identifying games where the model and the
market meaningfully disagree — largest potential value signal. Least useful on its own for
marquee, heavily-traded games where the market has more information.
        """)

# --- Quarter / half winners (Tier 2, drives-based) ---------------------------
if show_period:
    st.divider()
    C.section_header("⏱️", "Quarter and half winner probabilities — drive data (unverified)")
    st.warning(
        "**This section uses the drives cache**, built against CFBD field names cross-confirmed "
        "from third-party sources but not CFBD's own official schema directly. "
        "start_period (the field this section's per-period bucketing depends on) is plausible "
        "but still unverified against a real completed-week drive response. "
        "The moneyline section above uses schedule data only and is always reliable.",
        icon="⚠️")

    if not period_result:
        st.info(
            "No drive data on file yet — either no completed games have been played, or the "
            "drives cache hasn't been populated. Run `refresh_ncaaf.py` after games complete.",
            icon="🕐")
    else:
        # Quarter table
        period_labels = {1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4", "h1": "1st Half", "h2": "2nd Half"}
        rows = []
        for key, label in period_labels.items():
            data = period_result.get(key)
            if not data:
                continue
            rows.append({
                "Period": label,
                f"{away_name} win%": f"{data['away_win_prob']:.1%}",
                f"Proj {away_name}": f"{data['proj_away']:.1f}",
                f"Proj {home_name}": f"{data['proj_home']:.1f}",
                f"{home_name} win%": f"{data['home_win_prob']:.1%}",
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.caption("Win% from normal distribution simulation per period, clipped at 0 pts. "
                      "Ties counted separately, so home + away win% may not sum to exactly 100%.")

        # Full-game via drives (as a cross-check against the schedule-based result)
        full = period_result.get("full")
        if full and game_result:
            diff = abs(full["home_win_prob"] - game_result["home_win_prob"])
            if diff > 0.1:
                st.warning(
                    f"Drive-based full-game win probability ({full['home_win_prob']:.1%} home) "
                    f"diverges from the schedule-based result "
                    f"({game_result['home_win_prob']:.1%} home) by {diff:.1%}. "
                    "A large gap here is real, valuable signal about the drives data quality "
                    "for this specific team/matchup — worth flagging rather than choosing one.",
                    icon="🔍")

st.caption("v1 — no home-field advantage, no weather/travel/injury adjustment, "
          "schedule-based std is a simplification. Quarter/half section additionally depends on "
          "unverified drive cache field names. Compare against the market's own de-vigged "
          "moneyline (Command Center → Show de-vigged moneylines) before acting on this.")
