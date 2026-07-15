"""
Hot Hand Engine — WNBA matchup-adjusted leaderboard.

The honest WNBA counterpart to Dinger Engine: Dinger Engine leans on Statcast (pitch-level
tracking data with no free WNBA equivalent), so this isn't a literal port. Instead it uses a
real signal that IS available for free — every slate build already pulls both teams' box
scores, which means opponent defensive strength (how much a team has been allowing at each
stat recently) is sitting right there, unused, in data already fetched. This page puts it to
work: each rotation player's recent-form average, scaled by how generous or stingy their
TONIGHT'S opponent has been relative to the other opponents on tonight's slate.

Deliberately NOT folded into Edge Board/Best Bets' priced probabilities — see
wnba_projections.build_hot_hand_board's docstring for why keeping this a separate, clearly
labeled signal is the more conservative, honest choice for a live betting board.
"""

import streamlit as st
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import pandas as pd
from datetime import datetime
import pytz

import sports

_active = sports.active()

st.title("🔥 Hot Hand Engine")
st.caption("Recent-form leaders, adjusted for how generous tonight's opponent has actually "
           "been — the honest WNBA counterpart to Dinger Engine (no Statcast-equivalent data "
           "exists for basketball, so this leans on a real signal that does: opponent defense "
           "from box scores already being pulled for every slate).")

if not sports.require_sport("WNBA", "Hot Hand Engine"):
    st.stop()

E, P = _active.engine, _active.projections
eastern = pytz.timezone("US/Eastern")


@st.cache_data(ttl=300, show_spinner=False)
def load_board(date_str: str):
    rows, meta = E.build_slate(date_str)
    if not rows:
        return [], 0

    opp_ids = sorted({r["_opp_id"] for r in rows if r.get("_opp_id") is not None})
    opp_allowed = {oid: E.get_team_recent_allowed_stats(oid, date_str) for oid in opp_ids}
    team_ids = sorted({r["_team_id"] for r in rows if r.get("_team_id") is not None})
    team_rest = {tid: E.get_team_rest_info(tid, date_str) for tid in team_ids}
    board = P.build_hot_hand_board(rows, opp_allowed, team_rest)
    return board, len(meta)


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
    board, n_games = load_board(date_str)

if not board:
    st.info(f"No projectable players for this date. Pick a date with scheduled {_active.label} games.")
    st.stop()

markets = sorted({b["Market"] for b in board})
mc1, mc2, mc3 = st.columns([2, 1, 1])
with mc1:
    chosen_markets = st.multiselect("Markets", markets, default=markets)
with mc2:
    tag_filter = st.selectbox("Matchup", ["All", "🟢 Plus matchup only", "🔴 Tough matchup only"])
with mc3:
    rest_filter = st.selectbox("Rest", ["All", "⚠️ Back-to-back only"])

view = [b for b in board if b["Market"] in chosen_markets]
if tag_filter == "🟢 Plus matchup only":
    view = [b for b in view if b["Tag"] == "🟢 Plus matchup"]
elif tag_filter == "🔴 Tough matchup only":
    view = [b for b in view if b["Tag"] == "🔴 Tough matchup"]
if rest_filter == "⚠️ Back-to-back only":
    view = [b for b in view if b["B2B"]]

st.caption(f"{n_games} game(s) · {len(view)} of {len(board)} player-market rows shown")

st.info(
    "**What 'Opp Allows' and the color actually measure — read this before the table:** each "
    "opponent's WHOLE TEAM combined total at that stat, allowed to whoever they've faced "
    "recently. It is NOT specific to any one player and NOT position-adjusted — there's no "
    "per-position or per-defender data here. The color/tag is now PACE-ADJUSTED: it's driven by "
    "an estimated per-100-possession rate, not the raw per-game number shown in 'Opp Allows' — "
    "so a team that just plays fast no longer reads as a bad defense on its own. 🟢 **Green / "
    "Plus matchup** = that opponent has been allowing MORE at this stat per possession than the "
    "other opponents on tonight's slate — good news for whoever's playing them. 🔴 **Red / Tough "
    "matchup** = they've been allowing less, pace-adjusted. Each market (Points/Rebounds/"
    "Assists/Threes) is scored independently — a team can be a plus matchup on points and a "
    "tough one on rebounds at the same time. **Rest** is a separate, unrelated signal: whether "
    "the PLAYER'S OWN team (not the opponent) is on the second night of a back-to-back — real "
    "fatigue risk, kept as its own column rather than folded into the matchup color, which is "
    "about the opponent, not her legs.", icon="ℹ️")

# --- the board -----------------------------------------------------------------
def _rest_display(r):
    if r["Rest Days"] is None:
        return "—"
    return "⚠️ B2B" if r["B2B"] else f"{r['Rest Days']}d rest"


for b in view:
    b["Rest"] = _rest_display(b)

df = pd.DataFrame(view)[["Player", "Team", "Opp", "Market", "Recent Avg", "Opp Allows", "Opp Pace",
                         "Opp Allows /100 Poss", "Slate Avg /100 Poss", "Matchup Factor",
                         "Matchup Score", "Tag", "Rest", "Game"]]
df = df.rename(columns={"Opp Allows": "Opp Team Total"})
st.dataframe(
    df.style.format({"Recent Avg": "{:.1f}", "Opp Team Total": "{:.1f}", "Opp Pace": "{:.1f}",
                     "Opp Allows /100 Poss": "{:.1f}", "Slate Avg /100 Poss": "{:.1f}",
                     "Matchup Factor": "{:.2f}×", "Matchup Score": "{:.1f}"}, na_rep="—")
    .theme_gradient(cmap="RdYlGn", subset=["Matchup Factor"]),
    hide_index=True, use_container_width=True, height=520,
)
st.caption("\"Opp Team Total\" = that opponent's entire team combined for that stat, raw per-game "
           "(not a per-player or per-position figure). \"Opp Pace\" = their estimated possessions "
           "per game recently. \"Matchup Factor\" = Opp Allows /100 Poss ÷ Slate Avg /100 Poss — "
           "the pace-adjusted rate driving color and sort — above 1.08 is 🟢, below 0.92 is 🔴, "
           "in between is 🟡 neutral. \"Rest\" = her OWN team's rest, separate from the matchup "
           "read entirely — \"—\" means no recent game was found to compute it from (start of "
           "season, not a claim she's fresh).")

with st.expander("Full column reference"):
    st.markdown("""
- **Recent Avg** — the player's own bootstrap-model average over their last 10 games (same number
  Best Bets/Edge Board use), with no opponent adjustment.
- **Opp Team Total** — how much tonight's opponent has been giving up at this stat over *their*
  last 10 games, as a WHOLE TEAM (all 5 players combined, not per-position), raw per-game. Built
  from box score data already fetched for the slate — no extra API cost.
- **Opp Pace** — that opponent's own estimated possessions per game recently (FGA − OREB + TOV +
  0.44×FTA, the standard estimate used when official play-by-play possession counts aren't
  available). This is what turns "Opp Team Total" into a rate instead of a raw count.
- **Opp Allows /100 Poss** — Opp Team Total, pace-adjusted: what that opponent allows per 100
  possessions rather than per game. This is the number a fast-paced-but-actually-solid defense
  and a slow-paced-but-actually-leaky one would no longer be confused on.
- **Slate Avg /100 Poss** — the average pace-adjusted allowed rate across every opponent actually
  playing tonight (not a full-league average) — a single constant every "Opp Allows /100 Poss"
  gets compared against. This is what "generous" or "stingy" gets measured against, and it's why
  this is honest rather than a fabricated claim: it's a relative read on *tonight's* matchups, not
  a season-long defensive rating.
- **Matchup Factor** — see the note above the table for what the color and tags mean. A missing
  opponent or possession read (too few recent games for that team) stays neutral (1.00×) rather
  than guessing.
- **Matchup Score** — Recent Avg × Matchup Factor. The number this board is sorted by.
- **Rest** — the PLAYER'S OWN team's rest heading into tonight (not the opponent's), computed from
  game dates already on file — zero extra API cost. "⚠️ B2B" = second night of a back-to-back, a
  well-documented real fatigue risk. Deliberately separate from Matchup Factor/Score, which are
  entirely about the opponent's defense — rest is a different kind of risk, not another input into
  the same number. "—" means no recent game was found in the lookback window (start of season),
  reported honestly as unknown rather than assumed "well-rested."
    """)

st.caption("v1 signal, now pace- and rest-aware — still no positional matchup data (who's "
           "actually likely to guard this player), no blowout/minutes-risk or injury/"
           "availability context yet. This measures team-wide generosity at a stat, per "
           "possession, not a specific positional mismatch. A reasonable next layer, not built "
           "yet.")
