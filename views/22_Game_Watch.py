"""
Game Watch — tonight's whole slate, three real signals per game, honestly combined.

WHAT THIS IS, PRECISELY: for each game, compares starter quality (FIP), bullpen freshness, and
bullpen quality (aggregate ERA) side by side, then reports how many of those signals favor each
team. That's it. NOT a win probability. NOT a betting recommendation. NOT a prediction of the
final score. A transparent count of how many independently-computed factors happen to point the
same way -- see projections.matchup_signal_tally's own docstring for why a count, not a fabricated
weighted score: there's no real backtested validation yet that would justify weighting one signal
over another, so an honest count is the most this data can currently support.

WHY THIS EXISTS: a real, repeated pattern from trader discussion -- moneyline decisions were
being made by manually comparing starter quality, bullpen state, and recent form every night,
entirely outside this platform. This is a first step at that, deliberately scoped to signals
that were already built or nearly free to add (see below), not a full game-simulation model --
that's a genuinely bigger, different undertaking, worth its own separate build if this proves
useful. Bullpen Watch already covers freshness alone, cheaply, for anyone who just wants that
quick read; this page is the fuller (and more expensive) picture for anyone who wants all three.

REAL COST, OPT-IN BY DESIGN: the starter-FIP comparison is FREE (already inside the same
build_pitching_slate fetch Bullpen Watch also uses). Bullpen freshness costs what Bullpen Watch
already costs. Bullpen quality is a genuinely NEW real cost on top of both (a full roster + per-
pitcher-metrics fetch per team) -- so, like Bullpen Watch, nothing beyond the lightweight starter
list loads until you press the button below.
"""

import streamlit as st
from datetime import datetime

import mlb_engine as E
import projections as P
import sports

game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER

# Real, stated judgment calls, not buried magic numbers -- see lower_is_better_edge's own
# docstring for why these aren't just left at the exact-tie default. FIP epsilon: roughly a
# fifth of an earned run per 9, a commonly-used "materially different" gap for a single season's
# FIP. Bullpen ERA epsilon is wider (a bullpen's aggregate line mixes several arms of very
# different quality across a whole season, genuinely noisier than one starter's own FIP).
FIP_EPSILON = 0.20
BULLPEN_ERA_EPSILON = 0.30

st.title("📡 Game Watch")
st.caption("Three real signals per game — starter quality, bullpen freshness, bullpen quality — "
          "combined into an honest count, not a predicted winner. See the disclaimer at the "
          "bottom before reading too much into any single game.")
lc1, lc2 = st.columns(2)
with lc1:
    st.page_link("views/1_#L01f3af_Pitching_Lab.py",
                 label="Full pitcher-by-pitcher detail → Pitching Lab", icon="🎯")
with lc2:
    st.page_link("views/21_Bullpen_Watch.py",
                 label="Just want the quick, cheap freshness read? → Bullpen Watch", icon="🛡️")

target = st.date_input("Slate date", datetime.now())
date_str = target.strftime("%Y-%m-%d")


@st.cache_data(ttl=600, show_spinner=False)
def load_pitching_slate(date_str_inner: str):
    return E.build_pitching_slate(date_str_inner)


with st.spinner("Loading tonight's probable starters..."):
    pitching_rows = load_pitching_slate(date_str)

if not pitching_rows:
    st.info("No probable starters found for this date yet — check back closer to first pitch.")
    st.stop()

games = E.pair_pitching_slate_by_game(pitching_rows)
games.sort(key=lambda g: (SLOT_ORDER.get(slot_of(game_dt(g["_game_date"])), 9), g["label"]))

if not games:
    st.info("Couldn't pair up both sides for any game on this date — try a different date.")
    st.stop()

st.caption(f"{len(games)} game(s) on the board for {date_str}.")

if not st.button(f"🔄 Load matchup signals for all {len(games)} game(s)",
                 help="Real cost: bullpen freshness AND bullpen quality both require a full "
                     "roster + per-pitcher fetch per team, for both teams in every game below "
                     "(starter FIP is free, already loaded above). Cached for 10 minutes."):
    st.info("Press the button above to load tonight's matchup signals. Nothing beyond the "
           "starter list above is fetched until you do.")
    st.stop()


@st.cache_data(ttl=600, show_spinner=False)
def load_bullpen_freshness(team_id, exclude_pid, date_str_inner):
    if not team_id:
        return None
    fatigue = E.get_team_bullpen_fatigue(team_id, date_str_inner)
    return P.bullpen_fatigued_fraction(fatigue, exclude_pid=exclude_pid)


@st.cache_data(ttl=900, show_spinner=False)
def load_bullpen_quality(team_id, exclude_pid):
    if not team_id:
        return None
    agg = E.get_bullpen_aggregate_stat(team_id, exclude_pid=exclude_pid)
    return agg.get("era") if agg else None


progress = st.progress(0.0, text="Checking starter quality, bullpen freshness, and bullpen quality...")
for i, g in enumerate(games):
    away_row, home_row = g["away"], g["home"]
    away_fresh = load_bullpen_freshness(away_row["_team_id"], away_row["_pid"], date_str)
    home_fresh = load_bullpen_freshness(home_row["_team_id"], home_row["_pid"], date_str)
    away_bp_era = load_bullpen_quality(away_row["_team_id"], away_row["_pid"])
    home_bp_era = load_bullpen_quality(home_row["_team_id"], home_row["_pid"])

    starter_edge = P.lower_is_better_edge(away_row.get("FIP"), home_row.get("FIP"), epsilon=FIP_EPSILON)
    freshness_edge = P.bullpen_freshness_edge(away_fresh, home_fresh)
    quality_edge = P.lower_is_better_edge(away_bp_era, home_bp_era, epsilon=BULLPEN_ERA_EPSILON)

    g["_tally"] = P.matchup_signal_tally([starter_edge, freshness_edge, quality_edge])
    g["_signals"] = {
        "Starter FIP": (away_row.get("FIP"), home_row.get("FIP"), starter_edge),
        "Bullpen freshness": (away_fresh, home_fresh, freshness_edge),
        "Bullpen ERA": (away_bp_era, home_bp_era, quality_edge),
    }
    progress.progress((i + 1) / len(games), text=f"Checked {g['label']} ({i + 1}/{len(games)})")
progress.empty()


def _fmt(value, kind):
    if value is None:
        return "—"
    if kind == "pct":
        return f"{value:.0%}"
    return f"{value:.2f}"


VERDICT_TEXT = {
    "insufficient_data": "Not enough data to compare — nothing to show here.",
    "even": "Signals split or too close to call — no real edge either way.",
}

for g in games:
    dt = game_dt(g["_game_date"])
    time_str = dt.strftime("%-I:%M %p ET") if dt else "TBD"
    away_row, home_row = g["away"], g["home"]
    tally = g["_tally"]
    with st.container(border=True):
        st.markdown(f"### {g['label']} — {time_str}")

        rows = []
        for signal_name, (away_val, home_val, edge) in g["_signals"].items():
            kind = "pct" if signal_name == "Bullpen freshness" else "num"
            lean = {"home": f"→ {home_row['Team']}", "away": f"→ {away_row['Team']}",
                   "even": "even", None: "no data"}[edge]
            rows.append((signal_name, _fmt(away_val, kind), _fmt(home_val, kind), lean))

        h1, h2, h3, h4 = st.columns([2, 1, 1, 2])
        h1.caption("Signal")
        h2.caption(f"{away_row['Team']} (away)")
        h3.caption(f"{home_row['Team']} (home)")
        h4.caption("Edge")
        for name, av, hv, lean in rows:
            c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
            c1.write(name)
            c2.write(av)
            c3.write(hv)
            c4.write(lean)

        if tally["verdict"] in VERDICT_TEXT:
            st.markdown(f"**{VERDICT_TEXT[tally['verdict']]}**")
        else:
            winner = home_row["Team"] if tally["verdict"] == "home" else away_row["Team"]
            st.markdown(f"**{tally[tally['verdict']]} of {tally['available']} available signals "
                       f"favor {winner}.**")

st.divider()
st.caption("⚠️ **Read this before reading too much into any game above.** This is three "
          "individually honest comparisons counted up, not a probability and not a validated "
          "model — there's no historical backtest yet showing these three signals actually "
          "predict outcomes, or how much weight each deserves relative to the others. A 2-of-3 "
          "read is a starting point for your own judgment, not a call to act on by itself. "
          "\"Even\" and \"not enough data\" are both real, honest outcomes — most games likely "
          "won't show a clean sweep, and that itself is useful information, not a failure of "
          "the page. Uses the same FIP/bullpen-ERA \"real gap\" thresholds stated at the top of "
          f"this page (±{FIP_EPSILON:.2f} FIP, ±{BULLPEN_ERA_EPSILON:.2f} bullpen ERA) so a "
          "razor-thin numeric difference isn't shown as a real edge.")
