"""
Matchup Lab — WNBA player-vs-opponent deep-dive.

The honest WNBA counterpart to MLB's Matchup Lab: MLB's version is pitch-type granular
(Statcast tracks every pitch), which has no free WNBA equivalent. This is built on three real,
computable signals instead — recent form (what the model already prices off), head-to-head
history vs this exact opponent this season, and the opponent's recent-vs-season defensive trend
(built on the same box-score infrastructure Hot Hand Engine uses, extended with a season-wide
scan for the head-to-head piece).
"""

import streamlit as st
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import pandas as pd
from datetime import datetime
import pytz

import sports

_active = sports.active()

st.title("🔬 Matchup Lab")
st.caption("One player, one opponent, three real signals: recent form, head-to-head history "
           "this season, and whether the opponent's defense has been trending looser or "
           "tighter lately — the honest WNBA counterpart to Dinger Engine's pitch-type "
           "Matchup Lab (no free WNBA equivalent to Statcast exists, so this leans on box-score "
           "signals instead, the same foundation Hot Hand Engine is built on).")

if not sports.require_sport("WNBA", "Matchup Lab"):
    st.stop()

E, P = _active.engine, _active.projections
eastern = pytz.timezone("US/Eastern")


@st.cache_data(ttl=300, show_spinner=False)
def load_slate(date_str: str):
    rows, meta = E.build_slate(date_str)
    return rows, len(meta)


@st.cache_data(ttl=300, show_spinner=False)
def load_matchup(date_str: str, player_id: int, team_id: int, opp_id: int):
    h2h_log = E.get_player_history_vs_opponent(player_id, team_id, opp_id, date_str)
    opp_recent = E.get_team_recent_allowed_stats(opp_id, date_str)                    # last 10
    opp_season = E.get_team_recent_allowed_stats(opp_id, date_str, n=82, days_back=200)  # season-wide
    return h2h_log, opp_recent, opp_season


# --- controls ----------------------------------------------------------------
c1, c2 = st.columns([2, 1])
with c1:
    target_date = st.date_input("Slate date", datetime.now(eastern))
with c2:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
date_str = target_date.strftime("%Y-%m-%d")

with st.spinner("Loading tonight's slate..."):
    rows, n_games = load_slate(date_str)

if not rows:
    st.info(f"No projectable players for this date. Pick a date with scheduled {_active.label} games.")
    st.stop()

rows_sorted = sorted(rows, key=lambda r: (r["GameLabel"], r["Player"]))
options = {f"{r['Player']} ({r['Team']}) — {r['GameLabel']}": r for r in rows_sorted}
choice = st.selectbox("Player", list(options.keys()))
row = options[choice]

pid, team_id, opp_id = row["_pid"], row["_team_id"], row["_opp_id"]
if team_id is None or opp_id is None:
    st.error("This player's team/opponent couldn't be resolved — try refreshing the slate.")
    st.stop()

with st.spinner(f"Pulling {row['Opp']}'s matchup history and defensive trend..."):
    h2h_log, opp_recent, opp_season = load_matchup(date_str, pid, team_id, opp_id)

profile = P.build_matchup_profile(row, h2h_log, opp_recent, opp_season)

st.markdown(f"### {row['Player']} vs {row['Opp']}")
st.caption(f"{row['GameLabel']}  ·  averaging {row['AvgMin']:.0f} min/game over their last "
           f"{len(row.get('_game_log') or [])} games")

st.info(
    "**What 'Defense Trend' actually measures — read this before the table:** it's "
    f"{row['Opp']}'s **whole team's combined total** at each stat, allowed to whoever they've "
    "played recently, compared to their own season-long average. It is NOT specific to "
    f"{row['Player']}, and NOT specific to her position — there's no per-position or "
    "per-defender data here, just \"has this team's overall defense at this stat been "
    "trending looser or tighter than their own norm lately.\" 🟢 **Green / 📈 Looser lately** "
    f"= the opponent has been allowing MORE than usual — good news for {row['Player']}'s "
    "counting stats. 🔴 **Red / 📉 Tighter lately** = they've been allowing less — a tougher "
    "recent stretch for whoever they're facing. Each row (Points/Rebounds/Assists/Threes) has "
    "its own independent trend — a team can be trending looser on points and tighter on "
    "rebounds at the same time.", icon="ℹ️")

# --- the matchup grid --------------------------------------------------------
df = pd.DataFrame(profile)[["Market", "Recent Avg", "H2H Avg", "H2H Games", "Opp Recent Allowed",
                            "Opp Season Allowed", "Defense Trend", "Trend Tag"]]
df = df.rename(columns={"Opp Recent Allowed": "Opp Team Total (recent)",
                        "Opp Season Allowed": "Opp Team Total (season)"})
st.dataframe(
    df.style.format({"Recent Avg": "{:.1f}", "H2H Avg": "{:.1f}", "Opp Team Total (recent)": "{:.1f}",
                     "Opp Team Total (season)": "{:.1f}", "Defense Trend": "{:.2f}×"}, na_rep="—")
    .theme_gradient(cmap="RdYlGn", subset=["Defense Trend"]),
    hide_index=True, use_container_width=True,
)
st.caption(f"\"Opp Team Total\" = {row['Opp']}'s entire team combined, not a per-player or "
           "per-position figure. \"Defense Trend\" = Team Total (recent) ÷ Team Total (season) "
           "— above 1.08 is tagged looser/green, below 0.92 is tighter/red, in between is steady.")

if not h2h_log:
    st.caption(f"ℹ️ {row['Team']} and {row['Opp']} haven't played each other yet this season — "
               "H2H columns are honestly blank rather than a guess. Recent form and defense "
               "trend are still real signals on their own.")

with st.expander("Full column reference"):
    st.markdown("""
- **Recent Avg** — the player's own bootstrap-model average over their last 10 games, no
  opponent adjustment (the same number Best Bets/Edge Board price off).
- **H2H Avg / H2H Games** — this player's actual average in every game their team has played
  against tonight's specific opponent *this season*. Teams typically meet 2-4 times a season, so
  a small sample here is expected, not a bug — read it as a data point, not a verdict.
- **Opp Team Total (recent)** — tonight's opponent's WHOLE TEAM combined total at this stat, over
  *their* last 10 games (same number Hot Hand Engine uses). Not player- or position-specific.
- **Opp Team Total (season)** — the same thing, over a season-wide window instead of just their
  last 10. The gap between these two is the actual signal: a defense trending different from
  their own established norm.
- **Defense Trend** — Team Total (recent) ÷ Team Total (season). See the note above the table for
  what the color and tags mean.
    """)

# --- supporting detail: recent game log + H2H game log ----------------------
gc1, gc2 = st.columns(2)
with gc1:
    st.markdown("**Recent games (any opponent)**")
    log = row.get("_game_log") or []
    if log:
        rec_df = pd.DataFrame([{"Date": g.get("date", "—")[:10], "Opp": g.get("opp", "—"),
                                "PTS": g.get("pts", 0), "REB": g.get("reb", 0),
                                "AST": g.get("ast", 0), "3PM": g.get("fg3m", 0),
                                "MIN": g.get("min", 0)} for g in log])
        st.dataframe(rec_df, hide_index=True, use_container_width=True, height=250)
    else:
        st.caption("No recent games on file.")

with gc2:
    st.markdown(f"**Games vs {row['Opp']} this season**")
    if h2h_log:
        h2h_df = pd.DataFrame([{"Date": g.get("date", "—")[:10], "PTS": g.get("pts", 0),
                                "REB": g.get("reb", 0), "AST": g.get("ast", 0),
                                "3PM": g.get("fg3m", 0), "MIN": g.get("min", 0)} for g in h2h_log])
        st.dataframe(h2h_df, hide_index=True, use_container_width=True, height=250)
    else:
        st.caption("No meetings yet this season.")

st.caption("v1 signals — no positional matchup data (who's likely to guard this player), no pace "
           "adjustment. Recent Avg here is deliberately NOT adjusted by the Defense Trend column "
           "(unlike Hot Hand Engine's Matchup Score) — this page is meant to show you the raw "
           "signals side by side so you can weigh them yourself, not hand you one blended number.")
