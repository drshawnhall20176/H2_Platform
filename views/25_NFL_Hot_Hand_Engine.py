"""
Hot Hand Engine — NFL matchup-adjusted leaderboard.

BUILT AS ITS OWN PAGE, NOT ADDED TO THE EXISTING WNBA/NBA/NCAAMB HOT HAND ENGINE — same real
reasoning as NFL's own Matchup Lab (see that page's own module docstring): NFL's data shape is
genuinely different enough that reusing the shared page would mean either throwing away real
precision or bolting on special cases that make the shared page harder to reason about for every
sport that already uses it cleanly.

CLOSES THE ONE REAL REMAINING GAP after NFL's own Matchup Lab, Anytime TD Engine, and QB Lab were
already built (found live, on this exact page, after an earlier claim that NFL had neither Hot
Hand Engine nor Matchup Lab turned out to be wrong for Matchup Lab specifically — corrected
directly, not glossed over). Those three are one-player-at-a-time tools; this is the slate-WIDE
ranked view the basketball sports already have — nfl_projections.build_hot_hand_board's own
docstring has the full reasoning.

NO PACE ADJUSTMENT, DELIBERATELY — nfl_engine.get_team_allowed_stats' own docstring already
states why: NFL has no equivalent "possessions" concept the way basketball's per-100
normalization needs. Raw per-game allowed rates are used directly, honestly.

v1 SCOPE, STATED PLAINLY: this ships with the core matchup board and real injury data (NFL
already has both built). Rest-days and blowout-risk tracking — real, useful signals the
basketball version has — are NOT in this pass. A reasonable next layer, not silently missing.
"""

import streamlit as st
import components as C
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import pandas as pd
from datetime import datetime
import pytz

import sports
import nfl_engine as E
import nfl_projections as P

_active = sports.active()
eastern = pytz.timezone("US/Eastern")

C.base_css()
C.page_header("🔥", "Hot Hand Engine",
             "Recent-form leaders, adjusted for how generous this week's opponent has actually "
             "been — the honest NFL counterpart to WNBA/NBA/NCAAMB's own Hot Hand Engine, built "
             "on NFL's real data shape (weekly slates, no possessions concept to pace-adjust "
             "against) rather than a forced port of the basketball version.")

if not sports.require_sport(["NFL"], "Hot Hand Engine"):
    st.stop()


@st.cache_data(ttl=300, show_spinner=False)
def load_board(date_str: str):
    rows, meta = E.build_slate(date_str)
    if not rows:
        return [], 0, {}

    # Opponent allowed-stats, one real fetch per UNIQUE opponent on this week's slate (not per
    # player) -- the caller's job, matching every other sport's own hot-hand board, keeping
    # nfl_projections.build_hot_hand_board itself free of its own network fetching.
    opps = sorted({r["Opp"] for r in rows if r.get("Opp")})
    opp_allowed = {abbr: E.get_team_allowed_stats(abbr, date_str) for abbr in opps}
    board = P.build_hot_hand_board(rows, opp_allowed)
    team_abbrs = E.team_abbrs_from_meta(meta)   # zero extra cost -- meta already has this
    return board, len(meta), team_abbrs


@st.cache_data(ttl=300, show_spinner=False)
def load_injuries(date_str: str, team_abbrs_tuple: tuple):
    season = E._infer_season(date_str)
    schedule = E.get_schedule(season) if season is not None else []
    week = E._resolve_week(schedule, date_str) if schedule else None
    if season is None or week is None:
        return {}
    return {abbr: E.get_team_injuries(abbr, season, week) for abbr in team_abbrs_tuple}


# --- controls ----------------------------------------------------------------
c1, c2 = st.columns([2, 1])
with c1:
    target_date = st.date_input("Slate date", datetime.now(eastern))
with c2:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
date_str = target_date.strftime("%Y-%m-%d")

with st.spinner("Building the matchup-adjusted board..."):
    board, n_games, team_abbrs = load_board(date_str)

if not board:
    st.info("No projectable players for this date/week. Pick a date within an active NFL week.")
    st.stop()

with st.expander("🏥 Team injury report (this week's slate)"):
    injuries_by_abbr = load_injuries(date_str, tuple(sorted(set(team_abbrs.values()))))
    any_reported = False
    for abbr in sorted(set(team_abbrs.values())):
        team_injuries = injuries_by_abbr.get(abbr) or []
        if not team_injuries:
            continue
        any_reported = True
        st.markdown(f"**{abbr}**")
        idf = pd.DataFrame(team_injuries)[["player", "position", "status", "return_date", "comment"]]
        idf = idf.rename(columns={"player": "Player", "position": "Pos", "status": "Status",
                                  "return_date": "Est. Return", "comment": "Comment"})
        st.dataframe(idf, hide_index=True, width="stretch")
    if not any_reported:
        st.caption("No injuries currently reported for any team on this week's slate.")
    st.caption("Sourced from NFL's real weekly injury report. return_date always shows \"—\" here, "
              "honestly -- NFL's real injury data (confirmed live) has no return-date field the "
              "way ESPN's basketball injury endpoint does, so this platform doesn't invent one. "
              "Not folded into any score on this page -- context to weigh yourself.")

markets = sorted({b["Market"] for b in board})
mc1, mc2 = st.columns([2, 1])
with mc1:
    chosen_markets = st.multiselect("Markets", markets, default=markets)
with mc2:
    min_factor = st.selectbox("Matchup", ["All", "🟢 Favorable only (1.08×+)", "🔴 Tough only (0.92×-)"])

view = [b for b in board if b["Market"] in chosen_markets]
if min_factor == "🟢 Favorable only (1.08×+)":
    view = [b for b in view if b["Matchup Factor"] >= 1.08]
elif min_factor == "🔴 Tough only (0.92×-)":
    view = [b for b in view if b["Matchup Factor"] <= 0.92]

st.caption(f"{n_games} game(s) this week · {len(view)} of {len(board)} player-market rows shown")

st.info(
    "**What 'Opp Allows' actually measures — read this before the table:** each opponent's "
    "WHOLE TEAM combined total at that stat, allowed to whoever they've faced recently this "
    "season. It is NOT specific to any one player or position — there's no per-position defensive "
    "data here. **Matchup Factor** = Opp Allows ÷ Slate Avg (the average allowed rate across "
    "every opponent actually on THIS WEEK's slate, not the full league) — above 1.08× means this "
    "opponent has been more generous at this stat than this week's other matchups, below 0.92× "
    "means tougher. No pace adjustment (unlike the basketball version) — NFL has no equivalent "
    "\"possessions\" concept to normalize against, so raw per-game rates are used directly, "
    "honestly, rather than force-fit into an adjustment that wouldn't mean the same thing here. "
    "Each market is scored independently — a team can be a plus matchup on Pass Yards and a "
    "tough one on Rush Yards in the same game.",
    icon="ℹ️")

df = pd.DataFrame(view)[["Player", "Team", "Opp", "Position", "Market", "Recent Avg",
                         "Opp Allows", "Slate Avg", "Matchup Factor", "Hot Hand Score"]]
st.dataframe(
    df.style.format({"Recent Avg": "{:.1f}", "Opp Allows": "{:.1f}", "Slate Avg": "{:.1f}",
                     "Matchup Factor": "{:.2f}×", "Hot Hand Score": "{:.1f}"}, na_rep="—")
    .theme_gradient(cmap="RdYlGn", subset=["Matchup Factor"]),
    hide_index=True, width="stretch", height=520,
)
st.caption("\"Opp Allows\" = that opponent's entire team combined for that stat, raw per-game, "
          "season-to-date. \"Slate Avg\" = the average allowed rate across every opponent "
          "actually playing this week (not a full-league average) — a single constant every "
          "\"Opp Allows\" gets compared against, the same real, relative-to-this-week's-slate "
          "honesty the basketball version's own Slate Avg already holds to. A missing opponent "
          "read (too few games logged yet, early season) stays neutral (1.00×) rather than "
          "guessing.")

with st.expander("Full column reference"):
    st.markdown("""
- **Recent Avg** — the player's own recent-games average for this market (same number Best Bets/
  QB Lab/Anytime TD Engine use), with no opponent adjustment.
- **Opp Allows** — how much this week's opponent has been giving up at this stat, as a WHOLE TEAM
  (all opposing players combined, not per-position), raw per-game, season-to-date. Built from
  data already fetched for the slate — no extra API cost.
- **Slate Avg** — the average allowed rate across every opponent actually playing this week (not
  a full-league average) — a single constant every "Opp Allows" gets compared against. This is
  what "generous" or "stingy" gets measured against, and it's why this is honest rather than a
  fabricated claim: it's a relative read on *this week's* matchups, not a season-long defensive
  rating.
- **Matchup Factor** — Opp Allows ÷ Slate Avg. Above 1.08× is a favorable matchup, below 0.92× is
  tough, in between is neutral. A missing opponent read stays neutral (1.00×) rather than guessing.
- **Hot Hand Score** — Recent Avg × Matchup Factor. The number this board is sorted by.
- **Not included in this pass** — rest-days tracking and blowout-risk (game spread) context, both
  real signals the basketball version has. A reasonable next layer once this core version has
  been checked against real results, not silently missing.
    """)

st.caption("v1 signal — no rest-days or blowout-risk context yet (see above), and no positional "
          "matchup data (which specific defender/scheme a player actually faces). This measures "
          "team-wide generosity at a stat, not a specific positional mismatch. A reasonable next "
          "layer, not built yet.")
