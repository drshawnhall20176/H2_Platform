"""
NCAAF QB Lab — matchup-aware Pass Yards projections PLUS a TD:INT regression table.

Adapted directly from NFL's own QB Lab (views/14_QB_Lab.py), NOT a fresh build -- a real,
deliberate choice, not an oversight. Every function this page calls (ncaaf_projections.
build_qb_matchup_projections / build_qb_efficiency_table, ncaaf_engine.get_team_allowed_stats /
get_league_average_pass_yards_allowed / get_league_average_rush_yards_allowed /
get_player_season_games) was confirmed, side by side against its NFL counterpart, to share an
IDENTICAL signature and an IDENTICAL output dict shape (same real keys: "Recent Avg", "Matchup
Factor", "TD-INT Delta (recent vs season)", and so on) -- the underlying engine and projections
layers were already built with this exact page in mind (see ncaaf_shared_cache.py's own module
docstring, written proactively before any NCAAF view file existed). That confirmed match is why
this page's own display logic -- column names, formatting, chart structure -- is a direct port,
not a reinvention.

A REAL, HONEST CAVEAT WORTH CARRYING FORWARD: sports.py's own NCAAF entry notes this sport's
whole pipeline was verified against realistic, schema-matched constructed data, not an actual
live render against CFBD's real API (unreachable from that verification environment) -- this
page's own first real load is part of closing that gap, the same "first real run is the actual
verification step" pattern already used elsewhere on this platform. See that page's own caption
below for the same note, kept visible rather than buried in a comment only a developer would see.
"""

import streamlit as st
import components as C
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
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
C.page_header("🏈", "NCAAF QB Lab",
             "Matchup-aware Pass Yards projections and a TD:INT regression table — adapted "
             "directly from NFL's own QB Lab, on confirmed-matching real engine and projections "
             "functions, not a forced port of baseball's formulas.")

if not sports.require_sport(["NCAAF"], "NCAAF QB Lab"):
    st.stop()

st.info("🆕 This page's own first real live load is part of this platform's first real, "
       "end-to-end NCAAF verification — the underlying pipeline was tested against realistic, "
       "schema-matched data ahead of time, not an actual live CFBD fetch. If a number here looks "
       "genuinely wrong (not just \"no data yet\"), that's real, valuable signal — flag it.",
       icon="🆕")


@st.cache_data(ttl=600, show_spinner=False)
def load(date_str: str, stats_date_str: str):
    # Same real, established shared-cache discipline as NFL QB Lab's own load() -- see
    # ncaaf_shared_cache.py's own module docstring for the full reasoning (built proactively,
    # specifically so this page's own first real caller would reach for it from line one rather
    # than defining a local, soon-to-be-duplicated wrapper).
    #
    # TWO DIFFERENT DATES, ADDED DIRECTLY ON REQUEST, on purpose, not a bug: date_str picks which
    # REAL, ACTUAL games/players show up (today's real 2026 slate, always) -- stats_date_str
    # picks which season's data POWERS the numbers for those same real players. Normally these
    # are identical. The one real exception is the 2025-baseline mode below: _infer_season
    # already, correctly resolves any January/February date to the PRIOR year's season (see its
    # own docstring) -- so passing a real date like "2026-02-01" here, while date_str stays on
    # today's real slate date, gives every stats-lookup function below the real, complete,
    # already-finished 2025 season, with zero new functions needed and zero risk of the real
    # week-number collision a same-season blend would risk (see get_team_drive_outcomes' own
    # docstring for why that collision is a real, named concern elsewhere in this build).
    rows, meta = NSC.load_ncaaf_slate_cached(date_str)
    qb_rows = [r for r in rows if r["Position"] == "QB"]

    opps = sorted({r["Opp"] for r in qb_rows if r.get("Opp")})
    # get_team_allowed_stats already returns both passing_yards AND rushing_yards in one call per
    # opponent — no second round of per-opponent calls needed for the rushing side. Same real
    # confirmed behavior as NFL's own get_team_allowed_stats.
    opp_stats = {opp: E.get_team_allowed_stats(opp, stats_date_str, n=None) for opp in opps}
    opp_pass_allowed = {opp: s.get("passing_yards", 0.0) for opp, s in opp_stats.items()}
    opp_rush_allowed = {opp: s.get("rushing_yards", 0.0) for opp, s in opp_stats.items()}
    league_avg_pass = E.get_league_average_pass_yards_allowed(stats_date_str)
    league_avg_rush = E.get_league_average_rush_yards_allowed(stats_date_str)
    matchup_proj = P.build_qb_matchup_projections(rows, opp_pass_allowed, league_avg_pass,
                                                  opp_rush_allowed, league_avg_rush)

    season_logs = {r["_pid"]: E.get_player_season_games(r["_pid"], stats_date_str) for r in qb_rows}
    efficiency = P.build_qb_efficiency_table(rows, season_logs)

    return matchup_proj, efficiency, len(meta), len(qb_rows)


target_date = st.date_input("Slate date", datetime.now(eastern))
date_str = target_date.strftime("%Y-%m-%d")

# 2025-baseline toggle -- ADDED DIRECTLY ON REQUEST, specifically so there's real, honest content
# to discuss before 2026 has any completed games at all. "2026-02-01" is deliberately AFTER the
# real CFP National Championship (mid-January) and BEFORE the 2026 season could plausibly start
# -- _infer_season resolves it to season 2025, the full, real, already-completed season, cleanly.
show_2025_baseline = st.checkbox(
    "📊 Show 2025 season baseline instead (2026 hasn't started yet)",
    help="Uses last season's real, complete stats as a starting-point baseline for the same "
        "real players — clearly a stand-in for 2026 form, not a claim about it. A transfer, "
        "true freshman, or backup who barely played in 2025 will honestly show no baseline at "
        "all, not a guessed one.")
stats_date_str = "2026-02-01" if show_2025_baseline else date_str

if show_2025_baseline:
    st.info("📊 **Showing 2025 season data as a baseline.** Today's real matchups above are "
           "current — the numbers below are last season's, since 2026 has no games yet. Real "
           "roster and scheme changes since 2025 aren't reflected here.", icon="📊")

with st.spinner("Loading QBs and building matchup-aware projections..."):
    matchup_proj, efficiency, n_games, n_qbs = load(date_str, stats_date_str)

if not matchup_proj and not efficiency:
    if show_2025_baseline:
        st.info(
            "No 2025 data on file for any QB on today's slate — likely means these are new "
            "transfers, true freshmen, or backups who didn't see meaningful action last season. "
            "Try a different game/date, or uncheck the baseline toggle above.",
            icon="📊")
    else:
        st.info(
            "No QB has a completed game yet **this season**, so there's no real recent-form data to "
            "project from — this is expected for the first week of a new season, not a data "
            "problem with this specific date. This page's own signals stay empty until real Week "
            "1 games are actually in the books (deliberately: blending last season's game log "
            "with this one's risks mixing the wrong 'week 6' together). **Check the \"Show 2025 "
            "season baseline\" box above** for real, honest content to work with in the "
            "meantime — or use Best Bets or Graded Picks instead for actual prop decisions right "
            "now, since those already fall back to last season's full stats as a real, tested "
            "baseline.",
            icon="🕐")
    st.stop()

st.caption(f"{n_games} game(s) · {n_qbs} QB(s) on the slate")

# === Matchup-aware projections =============================================
C.section_header("⚡", "Matchup-aware Pass Yards + Rush Yards projections")
st.caption("Both Proj columns already account for how much yardage that specific opponent's "
          "defense has allowed this season relative to league average — the same odds-ratio "
          "matchup adjustment NFL QB Lab's own Proj columns use, applied here to NCAAF's own "
          "confirmed per-game data. Rush Yards is shown here even though QBs don't get a shared "
          "Rush Yards market on Edge Board/Best Bets — that exclusion was about not mixing a "
          "scrambling QB's carries with a workhorse RB's volume under one shared betting line; "
          "there's no such conflict here.")
if matchup_proj:
    pdf = pd.DataFrame(matchup_proj)
    sort_mode = st.radio("Sort", ["Projected Pass Yds", "Projected Rush Yds", "Matchup Factor"],
                         horizontal=True, key="ncaaf_qb_proj_sort")
    if sort_mode == "Projected Rush Yds":
        pdf = pdf.sort_values("Proj Rush Yds", ascending=False, kind="stable")
    elif sort_mode == "Matchup Factor":
        pdf = pdf.sort_values("Matchup Factor", ascending=False, kind="stable")
    proj_cols = ["Player", "Team", "Opp", "Game", "Recent Avg", "Opp Pass Yds Allowed (season)",
                "Matchup Factor", "Proj Pass Yds", "Recent Rush Yds",
                "Opp Rush Yds Allowed (season)", "Rush Matchup Factor", "Proj Rush Yds"]
    st.dataframe(
        pdf[proj_cols].rename(columns={"Recent Avg": "Recent Pass Yds"})
        .style.format({"Recent Pass Yds": "{:.1f}", "Opp Pass Yds Allowed (season)": "{:.1f}",
                       "Matchup Factor": "{:.2f}×", "Proj Pass Yds": "{:.1f}",
                       "Recent Rush Yds": "{:.1f}", "Opp Rush Yds Allowed (season)": "{:.1f}",
                       "Rush Matchup Factor": "{:.2f}×", "Proj Rush Yds": "{:.1f}"}, na_rep="—")
        .theme_gradient(cmap="RdYlGn", subset=["Matchup Factor", "Proj Pass Yds",
                                               "Rush Matchup Factor", "Proj Rush Yds"]),
        width="stretch", hide_index=True, height=420)
    st.caption("**Matchup Factor** / **Rush Matchup Factor** > 1.0× means this opponent has "
              "allowed MORE of that stat than league average this season (a softer defense, "
              "good for the QB); < 1.0× means tougher than average. 1.00× (neutral) shows when "
              "there isn't enough opponent/league data yet to adjust, not a claim the matchup "
              "is genuinely average.")
else:
    st.write("No projectable QBs (need at least one recent game on file).")

# === TD:INT regression + rushing TDs ========================================
st.divider()
C.section_header("📉", "Touchdowns: passing vs. rushing, and TD:INT regression")
st.caption("Passing TD:INT regression compares each QB's recent differential against their OWN "
          "season-long rate, not league average — a QB trending well above or below their own "
          "established norm is flagged, since the season sample is the more reliable baseline to "
          "expect a reversion toward. Rushing TD Rate is shown alongside as its own raw signal, "
          "not blended into the passing-specific delta — there's no rushing equivalent of an "
          "interception to regress it against the same way.")
if efficiency:
    edf = pd.DataFrame(efficiency)
    trending_up = edf[edf["TD-INT Delta (recent vs season)"] >= 0.5]
    trending_down = edf[edf["TD-INT Delta (recent vs season)"] <= -0.5]
    m1, m2, m3 = st.columns(3)
    m1.metric("QBs with a season sample", len(edf[edf["Season Passing TD Rate"].notna()]))
    m2.metric("Trending above season norm", len(trending_up))
    m3.metric("Trending below season norm", len(trending_down))

    eff_cols = ["Player", "Team", "Opp", "Recent Passing TD Rate", "Recent INT Rate",
               "Season Passing TD Rate", "Season INT Rate", "TD-INT Delta (recent vs season)",
               "Recent Rushing TD Rate", "Season Rushing TD Rate", "Tag"]
    styled = (
        edf[eff_cols]
        .style.format({"Recent Passing TD Rate": "{:.2f}", "Recent INT Rate": "{:.2f}",
                       "Season Passing TD Rate": "{:.2f}", "Season INT Rate": "{:.2f}",
                       "TD-INT Delta (recent vs season)": "{:+.2f}",
                       "Recent Rushing TD Rate": "{:.2f}", "Season Rushing TD Rate": "{:.2f}"}, na_rep="—")
        .theme_gradient(cmap="RdYlGn", subset=["TD-INT Delta (recent vs season)"])
    )
    st.dataframe(styled, width="stretch", hide_index=True, height=420)
else:
    st.write("No QBs with enough data for a regression comparison yet.")

# === Discussion hooks ========================================================
st.divider()
C.section_header("🤳", "Discussion hooks (auto-generated)")
st.caption("Talking points where recent form has meaningfully diverged from a QB's own season norm.")
if efficiency:
    edf_sorted = pd.DataFrame(efficiency)
    movers = edf_sorted[edf_sorted["TD-INT Delta (recent vs season)"].abs() >= 0.5].copy()
    movers["_abs_delta"] = movers["TD-INT Delta (recent vs season)"].abs()
    movers = movers.sort_values("_abs_delta", ascending=False)
    if movers.empty:
        st.write("No QBs trending meaningfully away from their season norm on this slate.")
    for _, r in movers.head(5).iterrows():
        direction = "above" if r["TD-INT Delta (recent vs season)"] > 0 else "below"
        st.code(
            f"{r['Player']} ({r['Team']}) is running a {r['Recent Passing TD Rate']:.1f} TD / "
            f"{r['Recent INT Rate']:.1f} INT per-game rate recently, {direction} his "
            f"{r['Season Passing TD Rate']:.1f} TD / {r['Season INT Rate']:.1f} INT season norm — "
            f"worth watching whether that holds up or reverts. #NCAAF",
            language=None,
        )
else:
    st.write("No data available for discussion hooks yet.")

st.caption("Trends, not guarantees. Both Matchup Factors use SEASON-long opponent data, "
          "deliberately not a recent-games version (a league-wide 'recent' baseline is genuinely "
          "ambiguous — see get_league_average_pass_yards_allowed's own docstring for why). TD:INT "
          "regression compares recency, not luck-vs-skill the way ERA-vs-FIP does — a real but "
          "different axis of the same underlying idea. Rushing TD Rate is a raw signal, not "
          "folded into the passing-specific delta above.")
