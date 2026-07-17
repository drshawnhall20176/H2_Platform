"""
QB Lab — matchup-aware Pass Yards projections PLUS a TD:INT regression table.

The honest NFL counterpart to MLB's Pitching Lab. Two real signals, not a forced port of
Pitching Lab's exact mechanics: matchup-aware Pass Yards projections (each QB's own recent-form
average, scaled by how much this week's opponent's pass defense allows relative to league
average — the same odds-ratio-style adjustment Pitching Lab's own Proj K applies), and a TD:INT
efficiency table comparing each QB's recent rates against their own season-long rates, flagging a
meaningful divergence — built from real confirmed data (TD/INT counts), not a fabricated "NFL
FIP" this platform doesn't have the tracking data to support honestly. See
nfl_projections.build_qb_matchup_projections and build_qb_efficiency_table for the full reasoning
behind each.
"""

import streamlit as st
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import pandas as pd
from datetime import datetime
import pytz

import sports
import nfl_engine as E
import nfl_projections as P

_active = sports.active()
eastern = pytz.timezone("US/Eastern")

st.title("🏈 QB Lab")
st.caption("Matchup-aware Pass Yards projections and a TD:INT regression table — the honest NFL "
          "counterpart to Pitching Lab's ERA-vs-FIP framing and matchup-adjusted K projections, "
          "built on real confirmed play data rather than a forced port of baseball's formulas.")

if not sports.require_sport(["NFL"], "QB Lab"):
    st.stop()


@st.cache_data(ttl=600, show_spinner=False)
def load(date_str: str):
    rows, meta = E.build_slate(date_str)
    qb_rows = [r for r in rows if r["Position"] == "QB"]

    opps = sorted({r["Opp"] for r in qb_rows if r.get("Opp")})
    opp_allowed = {opp: E.get_team_allowed_stats(opp, date_str, n=None).get("passing_yards", 0.0)
                   for opp in opps}
    league_avg = E.get_league_average_pass_yards_allowed(date_str)
    matchup_proj = P.build_qb_matchup_projections(rows, opp_allowed, league_avg)

    season_logs = {r["_pid"]: E.get_player_season_games(r["_pid"], date_str) for r in qb_rows}
    efficiency = P.build_qb_efficiency_table(rows, season_logs)

    return matchup_proj, efficiency, len(meta), len(qb_rows)


target_date = st.date_input("Slate date", datetime.now(eastern))
date_str = target_date.strftime("%Y-%m-%d")

with st.spinner("Loading QBs and building matchup-aware projections..."):
    matchup_proj, efficiency, n_games, n_qbs = load(date_str)

if not matchup_proj and not efficiency:
    st.info("No projectable QBs for this date. Pick a date within an NFL week with a real slate.")
    st.stop()

st.caption(f"{n_games} game(s) · {n_qbs} QB(s) on the slate")

# === Matchup-aware projections =============================================
st.subheader("⚡ Matchup-aware Pass Yards projections")
st.caption("Proj Pass Yds already accounts for how much yardage that specific opponent's pass "
          "defense has allowed this season relative to league average — the same odds-ratio "
          "matchup adjustment Pitching Lab's own Proj K uses, applied here to a yardage stat.")
if matchup_proj:
    pdf = pd.DataFrame(matchup_proj)
    sort_mode = st.radio("Sort", ["Projected Pass Yds", "Matchup Factor"], horizontal=True, key="qb_proj_sort")
    if sort_mode == "Matchup Factor":
        pdf = pdf.sort_values("Matchup Factor", ascending=False, kind="stable")
    st.dataframe(
        pdf.style.format({"Recent Avg": "{:.1f}", "Opp Pass Yds Allowed (season)": "{:.1f}",
                          "Matchup Factor": "{:.2f}×", "Proj Pass Yds": "{:.1f}"}, na_rep="—")
        .theme_gradient(cmap="RdYlGn", subset=["Matchup Factor", "Proj Pass Yds"]),
        use_container_width=True, hide_index=True, height=420)
    st.caption("**Matchup Factor** > 1.0× means this opponent has allowed MORE passing yards "
              "than league average this season (a softer pass defense, good for the QB); "
              "< 1.0× means a tougher-than-average pass defense. 1.00× (neutral) shows when "
              "there isn't enough opponent/league data yet to adjust, not a claim the matchup "
              "is genuinely average.")
else:
    st.write("No projectable QBs (need at least one recent game on file).")

# === TD:INT regression ======================================================
st.divider()
st.subheader("📉 TD:INT regression — recent vs. season")
st.caption("Compares each QB's recent TD:INT differential against their OWN season-long rate, "
          "not against league average — a QB trending well above or below their own established "
          "norm is flagged, since the season sample is the more reliable baseline to expect a "
          "reversion toward.")
if efficiency:
    edf = pd.DataFrame(efficiency)
    trending_up = edf[edf["TD-INT Delta (recent vs season)"] >= 0.5]
    trending_down = edf[edf["TD-INT Delta (recent vs season)"] <= -0.5]
    m1, m2, m3 = st.columns(3)
    m1.metric("QBs with a season sample", len(edf[edf["Season TD Rate"].notna()]))
    m2.metric("Trending above season norm", len(trending_up))
    m3.metric("Trending below season norm", len(trending_down))

    eff_cols = ["Player", "Team", "Opp", "Recent TD Rate", "Recent INT Rate", "Season TD Rate",
               "Season INT Rate", "TD-INT Delta (recent vs season)", "Tag"]
    styled = (
        edf[eff_cols]
        .style.format({"Recent TD Rate": "{:.2f}", "Recent INT Rate": "{:.2f}",
                       "Season TD Rate": "{:.2f}", "Season INT Rate": "{:.2f}",
                       "TD-INT Delta (recent vs season)": "{:+.2f}"}, na_rep="—")
        .theme_gradient(cmap="RdYlGn", subset=["TD-INT Delta (recent vs season)"])
    )
    st.dataframe(styled, use_container_width=True, hide_index=True, height=420)
else:
    st.write("No QBs with enough data for a regression comparison yet.")

# === Discussion hooks ========================================================
st.divider()
st.subheader("🤳 Discussion hooks (auto-generated)")
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
            f"{r['Player']} ({r['Team']}) is running a {r['Recent TD Rate']:.1f} TD / "
            f"{r['Recent INT Rate']:.1f} INT per-game rate recently, {direction} his "
            f"{r['Season TD Rate']:.1f} TD / {r['Season INT Rate']:.1f} INT season norm — worth "
            f"watching whether that holds up or reverts. #NFL",
            language=None,
        )
else:
    st.write("No data available for discussion hooks yet.")

st.caption("Trends, not guarantees. Matchup Factor uses SEASON-long opponent data, deliberately "
          "not a recent-games version (a league-wide 'recent' baseline is genuinely ambiguous — "
          "see get_league_average_pass_yards_allowed's own docstring for why). TD:INT regression "
          "compares recency, not luck-vs-skill the way ERA-vs-FIP does — a real but different "
          "axis of the same underlying idea.")
