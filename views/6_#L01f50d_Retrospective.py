"""
Retrospective — how did the model's board hold up against what actually happened?
 
A MODEL REVIEW, not an outlier hunt. It grades the pre-game probabilities against real
results and shows where the model ranked the players who actually produced. It never mines
for new variables to explain a specific surprise after the fact.
"""
 
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
 
import retro as R
import sports
import grading as G
import best_bets_data as BBD

_active = sports.active()
E, P = _active.engine, _active.projections

st.title("🔍 Retrospective")
st.caption(f"How the model's pre-game board lined up with what actually happened — "
           f"{_active.icon} {_active.label}")

if not sports.require_live_engine("Retrospective"):
    st.stop()

_MARKET_ICONS = {
    "Batter HR": "🏠", "Pitcher Strikeouts": "⚡", "Batter Total Bases": "📊",
    "Batter Total Hits": "✅", "Batter Strikeouts": "🌀", "Pitcher Outs": "🎯", "Pitcher Walks": "🚶",
    "Points": "🏀", "Rebounds": "🔁", "Assists": "🤝", "Threes Made": "3️⃣",
}
_active_markets = list(_active.market_map.keys())


@st.cache_data(ttl=600, show_spinner=False)
def load_retro_mlb(date_str: str, fip_constant: float):
    # build_mlb_board (best_bets_data.py) is the SAME shared pipeline Best Bets and Graded Picks
    # use — a real consolidation, not just deduplication for its own sake: Retrospective used to
    # have its OWN separate, third copy of this pipeline, which meant it graded the model against
    # UNBLENDED probabilities while the actual board shown to a person used the bullpen-blended
    # ones. That's a real accuracy gap now closed, not just fewer lines of code — this now grades
    # the SAME numbers a person actually sees.
    rows, meta, plays = BBD.build_mlb_board(date_str, fip_constant)
    results = E.get_player_results(date_str)
    graded, summary = R.grade_slate(plays, results)
    reports = {m: R.market_report(plays, results, m) for m in _active_markets}
    rows_by_pid = {r.get("_pid"): r for r in rows}
    # pitcher_rows themselves aren't returned by build_mlb_board (only used internally to build
    # plays) — rebuilding them here is cheap, pure computation (no network calls; every pitcher's
    # own stats are already sitting in rows' own "_opp_stat" fields), not a real duplication of
    # the expensive part of the pipeline (build_slate, statcast, weather, the bullpen blend).
    pitcher_rows = P.build_pitcher_projection_rows(rows, meta, seed=11)
    for pr in pitcher_rows:                     # so pitcher-K misses can be explained too
        rows_by_pid.setdefault(pr.get("_pid"), pr)
    return graded, summary, reports, rows_by_pid, len(meta), len(results)


@st.cache_data(ttl=600, show_spinner=False)
def load_retro_generic(sport_key: str, date_str: str):
    sport = sports.get(sport_key)
    rows, meta = sport.engine.build_slate(date_str)
    plays = sport.projections.build_best_bets(rows)
    results = sport.engine.get_player_results(date_str)
    graded, summary = R.grade_slate(plays, results)
    reports = {m: R.market_report(plays, results, m) for m in _active_markets}
    rows_by_pid = {r.get("_pid"): r for r in rows}
    return graded, summary, reports, rows_by_pid, len(meta), len(results)
 
 
if _active.key == "MLB":
    c1, c2 = st.columns([2, 1])
    with c1:
        target = st.date_input("Slate to review", datetime.now() - timedelta(days=1))
    with c2:
        fip_constant = st.number_input("FIP constant", value=E.FIP_CONSTANT_DEFAULT, step=0.01)
    date_str = target.strftime("%Y-%m-%d")

    st.warning("**Approximate, for exploration.** Rebuilding a past slate uses *current*-season "
               "rates, so recent dates have little look-ahead but older dates have more. For "
               "rigorous, point-in-time proof, the **Bet Log** (which saved the model's probability "
               "at bet time) is the real scorecard. Read this as a model review, not a P&L.", icon="⚠️")

    with st.spinner("Rebuilding the board and pulling results..."):
        graded, summary, reports, rows_by_pid, n_games, n_results = load_retro_mlb(date_str, fip_constant)
else:
    target = st.date_input("Slate to review", datetime.now() - timedelta(days=1))
    date_str = target.strftime("%Y-%m-%d")

    st.info("Rebuilt using only games completed **strictly before** this date — genuinely "
            "point-in-time, not a look-ahead approximation. (MLB's version above rebuilds from "
            "current-season rates; WNBA's recency-window model naturally avoids that.)", icon="✅")

    with st.spinner("Rebuilding the board and pulling results..."):
        graded, summary, reports, rows_by_pid, n_games, n_results = load_retro_generic(_active.key, date_str)
 
if not summary["graded"]:
    st.info("No completed games with results for this date yet. Pick a date whose games are final.")
    st.stop()
 
st.caption(f"{n_games} games · {summary['graded']} plays graded · {n_results} players with results")
 
# --- headline: could we have caught it? (all cast markets) -----------------
st.subheader("🎯 Could we have caught it?")
st.caption("For each market we cast, of the players whose result *cleared the line*, where did "
           "the model rank them **before** the game — and for the ones it ranked low, an honest "
           "reason. High rank = the model surfaced it; deep in the list = the data says it was "
           "largely random.")


_explain_miss = R.explain_miss if _active.key == "MLB" else P.explain_miss


def _render_market_review(rep, market, rows_by_pid):
    m1, m2, m3 = st.columns(3)
    m1.metric("Caught", len(rep["caught"]),
              help=f"Cleared the line AND ranked in the model's top {rep['cutoff']} "
                   f"of {rep['total_ranked']}")
    m2.metric("Ranked low", len(rep["missed"]), help="Cleared the line but the model ranked it deep")
    m3.metric("Off the board", rep["unprojected"], help="Cleared a typical line but not in a projected lineup")
 
    if rep["caught"]:
        cdf = pd.DataFrame(rep["caught"])
        cdf["Rank"] = cdf.apply(lambda r: f"#{r['Rank']} of {r['OfTotal']}", axis=1)
        cols = [c for c in ["Player", "Value", "Line", "ModelProb", "Conviction", "Rank"]
                if c in cdf.columns]
        st.markdown("**Caught — ranked high and delivered**")
        st.dataframe(
            cdf[cols].rename(columns={"ModelProb": "Model %", "Value": market}).style.format(
                {"Model %": "{:.0%}", "Conviction": "{:.2f}×", "Line": "{:g}", market: "{:.1f}"}, na_rep="—"),
            hide_index=True, use_container_width=True)
 
    if rep["missed"]:
        st.markdown("**Ranked low — could we have caught it?**")
        mrows = []
        for m in rep["missed"]:
            row = rows_by_pid.get(m.get("PlayerId"))
            mrows.append({
                "Player": m["Player"], market: m.get("Value"), "Model %": m["ModelProb"],
                "Conviction": m.get("Conviction") if m.get("Conviction") is not None else float("nan"),
                "Rank": f"#{m['Rank']} of {m['OfTotal']}",
                "Reason": _explain_miss(row, market),
            })
        mdf = pd.DataFrame(mrows)
        st.dataframe(
            mdf.style.format({"Model %": "{:.0%}", "Conviction": "{:.2f}×", market: "{:.1f}"}, na_rep="—"),
            hide_index=True, use_container_width=True)
 
    if rep["unprojected"]:
        st.caption(f"➕ {rep['unprojected']} more from players not in a projected lineup "
                   "(late changes, call-ups, subs) — the model never saw them.")
    if not (rep["caught"] or rep["missed"]):
        st.caption("Nothing cleared the line to review for this market on this date.")
 
 
tabs = st.tabs([f"{_MARKET_ICONS.get(m, '🔹')} {m}" for m in _active_markets])
for tab, market in zip(tabs, _active_markets):
    with tab:
        _render_market_review(reports[market], market, rows_by_pid)
        if market == "Batter Total Hits":
            st.caption("⚠️ Reminder: 1+ hits lands well over half the time, so a 'miss' here is closer "
                       "to a coin flip than a called shot — most are simply variance, not something the "
                       "model should have caught.")

if _active.key == "MLB":
    st.caption("**\"Catchable\" does not mean the model was wrong** — it means a real, market-specific "
               "signal (barrels or a homer-prone matchup for power; a hittable/whiff-prone opposing "
               "pitcher for hits and strikeouts; platoon edge; park/weather) was present that the ranking "
               "under-weighted, worth reviewing. **\"Genuine long shot / over\"** means no such edge: the "
               "model was right to rank it low, and chasing these is the overfitting we avoid. Most misses "
               "are simply variance — that's baseball, not a flaw.")
else:
    st.caption("**\"Catchable\" does not mean the model was wrong** — it means the player was already "
               "trending up over their last few games before this one, a real signal the recency "
               "weighting hadn't fully caught up to yet. **\"Genuine outlier\"** means no such trend: "
               "the result sits above their established form with no warning sign, and chasing these "
               "after the fact is the overfitting the model avoids. Most misses are simply variance.")
 
# --- model accuracy --------------------------------------------------------
st.divider()
st.subheader("📊 How the model's leans did")
m1, m2, m3 = st.columns(3)
m1.metric("Plays graded", summary["graded"])
m2.metric("Hit rate", f"{summary['hit_rate']:.0%}" if summary["hit_rate"] is not None else "—")
m3.metric("Hits", summary["hits"])
 
if summary["tiers"]:
    st.markdown("**Hit rate by conviction tier** — if the model ranks well, stronger leans hit more often")
    st.dataframe(pd.DataFrame(summary["tiers"]).rename(
        columns={"tier": "Conviction", "n": "Plays", "hit_rate": "Hit rate"})
        .style.format({"Hit rate": "{:.0%}"}), hide_index=True, use_container_width=True)
 
# Letter-grade accuracy -- does Graded Picks' own A/B/C/D actually mean anything, using real
# settled outcomes. NOW SPORT-AGNOSTIC, a real change from when this first shipped: grading.py
# (not MLB's own projections.py) is where conviction_to_grade actually lives now, confirmed
# during a later cross-sport audit that the MLB-only version would have crashed Graded Picks
# outright for every non-MLB sport. No gate needed here anymore -- this works for any sport's
# own graded plays directly.
grade_accuracy = G.grade_accuracy_by_letter(graded)
if grade_accuracy:
    st.markdown("**Hit rate by Graded Picks letter grade** \u2014 does an A actually hit more "
               "than a C? The direct test of whether that page's own grades mean anything, "
               "not a hypothetical.")
    st.dataframe(pd.DataFrame(grade_accuracy).rename(
        columns={"letter": "Grade", "tier": "Label", "n": "Plays", "hit_rate": "Hit rate"})
        .style.format({"Hit rate": "{:.0%}"}), hide_index=True, use_container_width=True)

cal = summary["calibration"]
if cal:
    fig, ax = plt.subplots(figsize=(3.6, 3.0), dpi=110)
    ax.plot([0, 1], [0, 1], "--", color="gray", label="perfect", linewidth=1)
    ax.scatter([c["predicted"] for c in cal], [c["actual"] for c in cal],
               s=[max(20, c["n"] * 3) for c in cal], color="#7c3aed", alpha=0.75, zorder=3)
    ax.set_xlabel("Model predicted", fontsize=8)
    ax.set_ylabel("Actual hit rate", fontsize=8)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_title("Calibration (this slate)", fontsize=9)
    ax.tick_params(labelsize=7)
    ax.legend(loc="upper left", fontsize=7); ax.grid(alpha=0.2)
    fig.tight_layout()
    chart_col, _ = st.columns([2, 3])          # cap width to ~40% of the page
    with chart_col:
        try:
            st.pyplot(fig, use_container_width=False)   # fixed small size, don't stretch
        except TypeError:
            st.pyplot(fig)                              # older Streamlit: column still caps it
    plt.close(fig)
    st.caption("One slate is a tiny sample — points won't sit perfectly on the line. The Bet Log's "
               "calibration, accumulated over many bets, is the trustworthy version.")
 
# --- full graded board -----------------------------------------------------
st.divider()
st.subheader("Full graded board")
only = st.radio("Show", ["All graded", "Hits only", "Misses only"], horizontal=True)
 
_graded_all = [g for g in graded if g["Hit"] is not None]
 
 
def _render_graded(subset):
    g = pd.DataFrame(subset)
    if not g.empty:
        if only == "Hits only":
            g = g[g["Hit"]]
        elif only == "Misses only":
            g = g[~g["Hit"]]
    if g.empty:
        st.caption("No graded plays match this filter.")
        return
    g = g.sort_values("Conviction", ascending=False)
    g["Result"] = g["Hit"].map({True: "✓", False: "✗"})
    g["Why it missed"] = g.apply(
        lambda r: "" if r["Hit"] else R.explain_pick_miss(r["ModelProb"], r["Market"], r.get("Side", "")),
        axis=1)
    show = g[["Conviction", "Player", "Market", "Side", "Line", "ModelProb", "Actual",
              "Result", "Why it missed", "Why"]]
    styler = (show.rename(columns={"ModelProb": "Model %", "Why": "Why the model liked it"})
              .style.format({"Model %": "{:.0%}", "Conviction": "{:.2f}×", "Line": "{:g}",
                            "Actual": "{:.1f}"}, na_rep="—"))
    # Natural width + wide text columns -> horizontal scroll for the two long reason columns.
    try:
        st.dataframe(
            styler, use_container_width=False, hide_index=True, height=480,
            column_config={
                "Why it missed": st.column_config.TextColumn("Why it missed", width="large"),
                "Why the model liked it": st.column_config.TextColumn("Why the model liked it", width="large"),
                "Player": st.column_config.TextColumn("Player", width="medium"),
            })
    except (TypeError, AttributeError):
        st.dataframe(styler, use_container_width=False, hide_index=True, height=480)
 
 
_GRADED_TABS = [("All markets", None)] + [(f"{_MARKET_ICONS.get(m, '🔹')} {m}", m) for m in _active_markets]
gtabs = st.tabs([t[0] for t in _GRADED_TABS])
for tab, (_label, mkt) in zip(gtabs, _GRADED_TABS):
    with tab:
        subset = _graded_all if mkt is None else [g for g in _graded_all if g["Market"] == mkt]
        _render_graded(subset)
 
if only == "Misses only":
    st.caption("**Why so many high-conviction plays 'missed':** conviction is a *ratio* (model prob ÷ "
               "the typical rate for that market), so a high multiple is **not** a high probability — "
               "always read the Model % column. For HR especially, a 2.5–3.4× lean is still only a "
               "~28–37% chance, so the model itself expects **roughly 2 in 3 to miss**; a night where "
               "most do is normal variance for a high-variance market, not a broken model. The Bet Log's "
               "calibration over many slates — not one cold night — is the real test of whether the "
               "probabilities are honest.")
