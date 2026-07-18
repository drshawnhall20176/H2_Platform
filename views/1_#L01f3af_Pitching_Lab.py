"""
Pitching Lab — ERA-vs-FIP regression PLUS matchup-aware starter projections.

The FIP table flags positive/negative regression candidates. The projections table shows
each starter's expected IP/K/BB/outs computed against the OPPOSING LINEUP (odds-ratio
matchup), so a strikeout arm vs a whiff-prone lineup projects higher than vs a contact team.
"""

import streamlit as st
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import pandas as pd
from datetime import datetime
import pytz

import mlb_engine as E
import projections as P

st.title("🎯 Pitching Lab")
st.caption("ERA vs FIP regression and matchup-aware strikeout/innings projections")

eastern = pytz.timezone("US/Eastern")


def game_time_et(iso_utc):
    """ISO-UTC start -> '7:10 PM ET', or 'TBD' if missing."""
    if not iso_utc:
        return "TBD"
    try:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(eastern)
        return dt.strftime("%I:%M %p").lstrip("0") + " ET"
    except (ValueError, TypeError):
        return "TBD"


@st.cache_data(ttl=600, show_spinner=False)
def load(date_str: str, fip_constant: float):
    rows, meta = E.build_slate(date_str, fip_constant)
    projections = P.build_pitcher_projection_rows(rows, meta, seed=11)
    # FIP regression table, rebuilt from the probable starters in meta.
    fip_rows = []
    for m in meta:
        for pm, team, opp, team_id in ((m["home_pm"], m["home_name"], m["away_name"], m.get("home_id")),
                                       (m["away_pm"], m["away_name"], m["home_name"], m.get("away_id"))):
            if pm.id is None or pm.era == 0:
                continue
            fip_rows.append({
                "Pitcher": pm.name, "Team": team, "Opponent": opp, "Hand": pm.hand,
                "ERA": round(pm.era, 2), "FIP": pm.fip, "Delta": round(pm.era - pm.fip, 2),
                "K/9": round(pm.k9, 1), "WHIP": round(pm.whip, 2), "HR/9": round(pm.hr9, 2), "OBA": pm.oba,
                "_game_date": m.get("game_date"), "_team_id": team_id,
            })
    return fip_rows, projections, meta


col_a, col_b = st.columns([2, 1])
with col_a:
    target_date = st.date_input("Analysis Date", datetime.now())
with col_b:
    fip_constant = st.number_input("FIP constant", value=E.FIP_CONSTANT_DEFAULT,
                                   step=0.01, help="Season-specific; ~3.1-3.2.")

date_str = target_date.strftime("%Y-%m-%d")

with st.spinner("Loading starters and opposing lineups..."):
    fip_rows, proj_rows, meta = load(date_str, fip_constant)

if not fip_rows:
    st.info("No probable starters found for this date. Pick a date with scheduled games.")
    st.stop()

df = pd.DataFrame(fip_rows)
df["Time"] = df["_game_date"].apply(game_time_et)

# === Matchup-aware projections =============================================
st.subheader("⚡ Matchup-aware starter projections")
st.caption("Expected line vs the opposing lineup. Proj K already accounts for how much that "
           "specific lineup strikes out — the same odds-ratio matchup used on the hitter side.")
if proj_rows:
    pdf = pd.DataFrame(proj_rows)
    pdf["Time"] = pdf["_game_date"].apply(game_time_et)
    sort_mode = st.radio("Sort", ["Chronological", "Projected K"], horizontal=True, key="proj_sort")
    if sort_mode == "Chronological":
        pdf = pdf.sort_values("_game_date", kind="stable", na_position="last")
    else:
        pdf = pdf.sort_values("Proj K", ascending=False, kind="stable")
    show = pdf.rename(columns={"K over%": "SO o5.5", "K fair": "SO fair"})
    cols = ["Time", "Pitcher", "Team", "Opp", "Hand", "Proj IP", "Proj K", "SO o5.5", "SO fair",
            "Proj BB", "Proj Outs", "ERA", "FIP"]
    show = show[[c for c in cols if c in show.columns]]
    st.dataframe(
        show.style.format({"SO o5.5": "{:.1%}", "Proj IP": "{:.1f}", "Proj K": "{:.1f}",
                           "Proj BB": "{:.1f}", "Proj Outs": "{:.1f}", "ERA": "{:.2f}", "FIP": "{:.2f}"})
        .theme_gradient(cmap="RdYlGn", subset=["Proj K", "SO o5.5"]),
        use_container_width=True, hide_index=True, height=420)
else:
    st.write("No projectable starters (need 3+ starts of data).")

# === FIP regression ========================================================
st.divider()
st.subheader("📉 ERA vs FIP regression")
buys = df[df["Delta"] >= 0.50].sort_values("Delta", ascending=False)
fades = df[df["Delta"] <= -0.50].sort_values("Delta")
m1, m2, m3 = st.columns(3)
m1.metric("Probable starters", len(df))
m2.metric("Positive-regression (buy)", len(buys))
m3.metric("Negative-regression (fade)", len(fades))

fip_cols = ["Time", "Pitcher", "Team", "Opponent", "Hand", "ERA", "FIP", "Delta",
            "K/9", "WHIP", "HR/9", "OBA"]
styled = (
    df.sort_values("Delta", ascending=False)[fip_cols]
    .style.format({"ERA": "{:.2f}", "FIP": "{:.2f}", "Delta": "{:+.2f}",
                   "K/9": "{:.1f}", "WHIP": "{:.2f}", "HR/9": "{:.2f}", "OBA": "{:.3f}"})
    .theme_gradient(cmap="RdYlGn", subset=["Delta", "K/9"])
    .theme_gradient(cmap="RdYlGn_r", subset=["ERA", "FIP", "WHIP", "HR/9"])
)
st.dataframe(styled, use_container_width=True, hide_index=True)

# === Bullpen fatigue =========================================================
st.divider()
st.subheader("💪 Bullpen fatigue")
st.caption("Which relievers on each side have real recent workload — pitched on 3+ straight "
          "days is the clearest \"likely unavailable tonight\" signal. Scoped to one game at a "
          "time, not the whole slate — each team's read costs several real API calls (a "
          "schedule window plus one boxscore per recent game), so this narrows first rather "
          "than fetching bullpen data for every team on a busy night up front.")


@st.cache_data(ttl=900, show_spinner=False)
def load_bullpen_fatigue(team_id, date_str_inner, fip_constant_inner):
    if not team_id:
        return []
    fatigue = E.get_team_bullpen_fatigue(team_id, date_str_inner)
    return E.enrich_bullpen_fatigue_with_metrics(fatigue, fip_constant_inner)


game_options = {m["label"]: m for m in meta if m.get("home_id") and m.get("away_id")}
if game_options:
    game_pick = st.selectbox("Game", sorted(game_options.keys()))
    picked = game_options[game_pick]

    with st.spinner("Checking recent bullpen usage and quality for both teams..."):
        home_fatigue = load_bullpen_fatigue(picked["home_id"], date_str, fip_constant)
        away_fatigue = load_bullpen_fatigue(picked["away_id"], date_str, fip_constant)

    bc1, bc2 = st.columns(2)
    for col, label, fatigue in ((bc1, picked["home_name"], home_fatigue),
                                (bc2, picked["away_name"], away_fatigue)):
        with col:
            st.markdown(f"**{label}**")
            if not fatigue:
                st.caption("No pitchers with recent appearances found in the last 5 days.")
                continue
            bdf = pd.DataFrame(fatigue)[["name", "days_since_last_appearance", "consecutive_days",
                                        "total_outs_in_window", "ERA", "FIP", "K9", "tag"]]
            bdf = bdf.rename(columns={"name": "Pitcher", "days_since_last_appearance": "Days Since",
                                      "consecutive_days": "Streak", "total_outs_in_window": "Outs (window)",
                                      "K9": "K/9"})
            st.dataframe(
                bdf.style.format({"ERA": "{:.2f}", "FIP": "{:.2f}", "K/9": "{:.1f}"}, na_rep="—")
                .theme_gradient(cmap="RdYlGn", subset=["K/9"])
                .theme_gradient(cmap="RdYlGn_r", subset=["ERA", "FIP"]),
                hide_index=True, use_container_width=True)
    st.caption("Every pitcher who recorded an out in either team's last 5 games, not just "
              "confirmed relievers — cross-reference against the probable starter above to "
              "read the rest as bullpen arms. \"Outs (window)\" is total workload across the "
              "whole 5-day window, not per game. ERA/FIP/K9 are each pitcher's own SEASON line — "
              "\"available AND good\" vs. \"available but mediocre\" in one table, not two "
              "separate lookups.")
else:
    st.caption("No games with both team ids available for this date.")

# === Discussion hooks ======================================================
st.divider()
st.subheader("🤳 Discussion hooks (auto-generated)")
st.caption("Talking points where the underlying metrics diverge from the surface results.")
if buys.empty:
    st.write("No strong positive-regression candidates on this slate.")
for _, r in buys.head(5).iterrows():
    st.code(
        f"{r['Pitcher']} ({r['Team']}) carries a {r['ERA']:.2f} ERA but a {r['FIP']:.2f} FIP "
        f"— a {r['Delta']:+.2f} gap. The peripherals (K/9 {r['K/9']:.1f}, WHIP {r['WHIP']:.2f}) "
        f"suggest he's pitching better than the line shows. #MLB",
        language=None,
    )

st.caption("Trends, not guarantees. FIP normalizes for defense/luck; projections assume the "
           "starter goes his typical length and the opposing lineup is roughly as posted.")
