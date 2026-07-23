"""
Model Dashboard — the marketing-facing proof page: real bets we've actually placed, and the
tool's own recommendations from last night's slate, each broken down by market as hit/miss
pie charts.

TWO GENUINELY DIFFERENT KINDS OF EVIDENCE, kept clearly separate on purpose, not blended into
one number:
  1. Real bets — sourced from the Bet Log, is_real_bet=True only. This is real money, real
     results, no rebuilding involved.
  2. The tool's own picks — last night's board rebuilt and graded against real results
     (the same machinery Retrospective already uses), filtered to C-or-better graded plays
     only, matching the same "this is a real recommendation" floor Suggested Parlays and
     Graded Picks already use elsewhere on this platform. Every candidate the model considered
     would dilute this into something close to noise; only the plays someone would have
     actually acted on are counted.

APPROXIMATE ON PURPOSE, SAME HONEST CAVEAT AS RETROSPECTIVE: rebuilding a past slate uses
CURRENT-season rates, not the exact point-in-time numbers from that specific night. Fine for
"last night" specifically (little time has passed), not a substitute for the Bet Log's own
point-in-time record.

GATING, FIXED DIRECTLY ON REQUEST AFTER A PLATFORM AUDIT: this page used to require the same
strict trading-access password as Bet Log/Track Record for the WHOLE page, even though only
element 1 (Real bets) actually touches real financial data -- elements 2-4 (tool's own picks,
player calibration, chalk test) are all rebuilt-board analysis, the same sensitivity level as
Retrospective, which is NOT behind that stricter gate. That meant this page's own stated
"marketing-facing proof page" identity was contradicted by its own gating: it was fully hidden
behind a private password most visitors would never have, AND (a real, separate bug) it was
NOT in owner_only_titles, so it still APPEARED in navigation for a public/Discord audience,
who could click it and hit a password wall for content most of which was never actually
sensitive -- the only page on this platform with that specific "visible then blocked" dead end,
unlike Bet Log/Track Record, which simply don't appear in navigation at all for that audience.
Fixed by gating the PAGE at the same level as Retrospective (require_live_engine, matching its
own real sensitivity), and moving the stricter trading-access password check down to guard
ONLY element 1, inline, right where the real financial data actually renders.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta

import sports
import betlog as B
import retro as R
import best_bets_data as BBD
import grading as G

_active = sports.active()
E, P = _active.engine, _active.projections

st.title("🏆 Model Dashboard")
st.caption(f"Real bets and the tool's own picks, by market — {_active.icon} {_active.label}")

if not sports.require_live_engine("Model Dashboard"):
    st.stop()

PALETTE = {"pos": "#16a34a", "neg": "#dc2626"}   # matches Track Record's own hit/miss colors


def _pie(hits: int, misses: int, title: str):
    fig = go.Figure(go.Pie(
        labels=["Hit", "Miss"], values=[hits, misses],
        marker=dict(colors=[PALETTE["pos"], PALETTE["neg"]]), hole=0.45,
        textinfo="label+percent", sort=False))
    fig.update_layout(template="plotly_white", title=dict(text=title, font=dict(size=14)),
                      height=260, margin=dict(l=10, r=10, t=40, b=10), showlegend=False)
    st.plotly_chart(fig, use_container_width=True)


def _pie_grid(entries, hit_key: str, miss_key: str, title_key: str):
    """entries: list of dicts each with a hit count, miss count, and a title -- renders one pie
    per entry in a 3-wide grid. Shared by both elements below so the two sections look and
    behave identically, not two subtly different implementations."""
    cols = st.columns(3)
    for i, e in enumerate(entries):
        with cols[i % 3]:
            _pie(e[hit_key], e[miss_key], e[title_key])


# =========================================================================== element 1: real bets
st.divider()
st.subheader("💵 Real bets — hit rate by market")
st.caption("Every real, placed bet we've logged, broken down by market. Real money, real "
          "results — nothing rebuilt or approximated here.")

# The stricter, separate trading-access password -- same gate Bet Log/Track Record use for the
# same real financial data -- checked HERE specifically, not for the whole page (see this file's
# own module docstring for why). Elements 2-4 below render normally either way.
if sports.require_trading_access("This section"):

    @st.cache_data(ttl=300, show_spinner=False)
    def _load_real_bets(sport_key: str):
        try:
            return B.list_bets(sport=sport_key, is_real_bet=True)
        except Exception:
            return []

    real_bets = _load_real_bets(_active.key)
    if real_bets:
        mkt = [m for m in B.market_breakdown(real_bets) if m["wins"] + m["losses"] > 0]
        if mkt:
            _pie_grid(mkt, "wins", "losses", "market")
        else:
            st.caption("No settled real bets yet for this sport — pies appear once results come in.")
    else:
        st.info("No real bets logged yet for this sport. Once real, placed bets are logged and "
               "settled, this section fills in automatically.")

# =========================================================================== element 2: the tool's own picks
st.divider()
st.subheader("🎯 The tool's own picks — how the tool's recommendations graded out")
st.caption("Rebuilt and graded against real results, filtered to C-or-better graded plays only "
          "— the same floor Suggested Parlays and Graded Picks already use to mean 'a real "
          "recommendation,' not every candidate the model ever considered.")

if _active.key == "MLB":
    fip_constant = st.number_input("FIP constant", value=E.FIP_CONSTANT_DEFAULT, step=0.01,
                                   key="dash_fip")

    @st.cache_data(ttl=600, show_spinner=False)
    def _load_graded_mlb(date_str_inner: str, fip_constant_inner: float):
        _, _, plays = BBD.build_mlb_board(date_str_inner, fip_constant_inner)
        results = E.get_player_results(date_str_inner)
        graded, _ = R.grade_slate(plays, results)
        return graded

    def _load_graded_for(date_str_inner: str):
        return _load_graded_mlb(date_str_inner, fip_constant)
else:
    @st.cache_data(ttl=600, show_spinner=False)
    def _load_graded_generic(sport_key: str, date_str_inner: str):
        sport = sports.get(sport_key)
        rows, meta = sport.engine.build_slate(date_str_inner)
        plays = sport.projections.build_best_bets(rows)
        results = sport.engine.get_player_results(date_str_inner)
        graded, _ = R.grade_slate(plays, results)
        return graded

    def _load_graded_for(date_str_inner: str):
        return _load_graded_generic(_active.key, date_str_inner)

view_mode = st.radio("View", ["Single slate", "Trend (multiple nights)"], horizontal=True,
                     key="dash_view_mode")

if view_mode == "Single slate":
    target = st.date_input("Slate to review", datetime.now() - timedelta(days=1), key="dash_slate_date")
    date_str = target.strftime("%Y-%m-%d")
    with st.spinner("Rebuilding that night's board..."):
        graded = _load_graded_for(date_str)
else:
    n_days = st.number_input("Nights back", min_value=1, max_value=30, value=7, step=1,
                             key="dash_trend_days")
    dates = R.trading_dates_ending_yesterday(int(n_days))
    graded = []
    progress = st.progress(0.0, text=f"Rebuilding {len(dates)} nights...")
    for i, d in enumerate(dates):
        graded.extend(_load_graded_for(d))
        progress.progress((i + 1) / len(dates), text=f"Rebuilt {d} ({i + 1}/{len(dates)})")
    progress.empty()
    st.caption(f"Pooled across {dates[0]} through {dates[-1]} ({len(dates)} nights).")

st.warning("**Approximate, for exploration.** Rebuilding a past slate uses *current*-season "
          "rates, not the exact point-in-time numbers from that specific night — fine for "
          "checking recent results, not a substitute for the Bet Log's own real, point-in-time "
          "record above.", icon="⚠️")

by_market = G.hit_miss_by_market(graded, min_grade_letter="C")
if by_market:
    _pie_grid(by_market, "hits", "misses", "label")

    st.markdown("**Hit rate by letter grade, within each market/side** — does an A actually hit "
               "more than a C in *this specific market and side*? The pie chart above pools "
               "every C-or-better grade into one hit/miss split, which can hide a real problem: "
               "a bucket where A's are near-perfect and C's are closer to a coin flip looks "
               "identical in aggregate to one where every grade performs about the same. This "
               "breaks it apart. Split by side too (not just market) — Over and Under for the "
               "same market carry different reference rates, so a shared letter grade means "
               "different real confidence on each side; pooling them would muddy this exact "
               "table. Includes D-grade and ungraded plays too, so the full A→D ordering is "
               "visible, not just the C-or-better subset the pie chart above is scoped to.")
    for m in by_market:
        bucket_plays = [g for g in graded
                        if g.get("Market") == m["market"] and g.get("Side") == m["side"]]
        breakdown = G.grade_accuracy_by_letter(bucket_plays)
        if breakdown:
            with st.expander(f"{m['label']} — by letter grade"):
                st.dataframe(pd.DataFrame(breakdown).rename(
                    columns={"letter": "Grade", "tier": "Label", "n": "Plays", "hit_rate": "Hit rate"})
                    .style.format({"Hit rate": "{:.0%}"}), hide_index=True, use_container_width=True)
else:
    st.caption("No C-or-better graded picks settled for this slate yet — try an earlier date, "
              "or results may not be posted for this slate yet.")

# =========================================================================== element 3: player calibration
st.divider()
st.subheader("🧑‍⚖️ Player calibration — model vs. reality, by player")
st.caption("A real, recurring pattern worth checking with data instead of gut feel: traders "
          "keeping an informal \"ban list\" of specific players who seem to keep missing on "
          "plays the model favored. This groups every SETTLED play in the window above by "
          "player (pooled across every market, the same way a real \"ban list\" itself pools "
          "across markets) and compares the model's own average probability against what "
          "actually happened. Uses the SAME graded plays already loaded above — Trend mode's "
          "wider, multi-night window will surface far more players than Single slate, where "
          "most players will have too few plays to clear the floor below.")

min_plays = st.number_input("Minimum settled plays to include a player", min_value=2, max_value=50,
                            value=8, step=1,
                            help="A real, stated floor against the exact small-sample problem "
                                "the \"ban list\" pattern itself is prone to — a player with "
                                "only 2-3 memorable misses isn't a real signal yet.")
calibration = R.player_calibration(graded, min_plays=int(min_plays))

if not calibration:
    st.info(f"No player has {int(min_plays)}+ settled plays in this window yet — try Trend mode "
           f"with more nights, or lower the minimum above.")
else:
    def _cal_df(rows):
        return (pd.DataFrame(rows)[["player", "n", "avg_model_prob", "actual_hit_rate", "gap"]]
                .rename(columns={"player": "Player", "n": "Plays", "avg_model_prob": "Model avg",
                                 "actual_hit_rate": "Actual hit rate", "gap": "Gap"}))

    cal_tab1, cal_tab2 = st.tabs(["📉 Most overrated by the model", "📈 Most underrated by the model"])
    with cal_tab1:
        st.caption("Positive gap = the model expected more than actually happened — the real "
                  "\"ban list\" direction.")
        overrated = [r for r in calibration if r["gap"] > 0][:15]
        if overrated:
            st.dataframe(_cal_df(overrated).style.format(
                {"Model avg": "{:.0%}", "Actual hit rate": "{:.0%}", "Gap": "{:+.0%}"}),
                hide_index=True, use_container_width=True)
        else:
            st.caption("No player in this window is running hot on the model's expectations — "
                      "nobody has a positive gap yet.")
    with cal_tab2:
        st.caption("Negative gap = the player quietly outperformed what the model expected of "
                  "them — the mirror image, an equally real finding.")
        underrated = [r for r in calibration if r["gap"] < 0][::-1][:15]
        if underrated:
            st.dataframe(_cal_df(underrated).style.format(
                {"Model avg": "{:.0%}", "Actual hit rate": "{:.0%}", "Gap": "{:+.0%}"}),
                hide_index=True, use_container_width=True)
        else:
            st.caption("No player in this window is outperforming the model's expectations yet "
                      "— nobody has a negative gap.")
    st.caption("⚠️ Same honest caveat as the rest of this page: Trend mode rebuilds past slates "
              "with CURRENT-season rates, not point-in-time ones. A real gap here is worth "
              "watching, not automatically acting on — even a real, systematic-looking gap over "
              "a modest sample can still be variance. This is a data point for the same "
              "judgment call a \"ban list\" already makes informally, not a replacement for it.")

# =========================================================================== element 4: slate-wide chalk test
if _active.key == "MLB":
    st.divider()
    st.subheader("📅🎯 Slate-wide chalk test")
    st.caption("Tests one specific, real, ONE-TIME claim from trader discussion, not a proven "
              "pattern: \"a slate with a lot of higher-tier starters tends to run chalky.\" "
              "Operationalized here as: does a day's average probable-starter FIP correlate "
              "with that same day's overall settled prop hit rate? If the hypothesis holds, "
              "expect a NEGATIVE correlation — better (lower) FIP pitching across the slate "
              "paired with a higher, \"chalkier\" hit rate. Real cost per day tested (a full "
              "board rebuild + grading, same as Trend mode above, plus one lightweight starter "
              "fetch) — nothing runs until you press the button below.")

    chalk_days = st.number_input("Days to test", min_value=10, max_value=30, value=14, step=1,
                                 key="chalk_n_days",
                                 help="Capped at 30 for the same real-cost reasons as Trend mode "
                                     "above; floored at 10 since a correlation from fewer days "
                                     "isn't reported as a real number (see below).")

    if st.button(f"🔄 Run the {int(chalk_days)}-day chalk test"):
        chalk_dates = R.trading_dates_ending_yesterday(int(chalk_days))
        daily_points = []
        progress = st.progress(0.0, text=f"Testing {len(chalk_dates)} night(s)...")
        for i, d in enumerate(chalk_dates):
            pitching_rows = E.build_pitching_slate(d)
            fips = [r["FIP"] for r in pitching_rows if r.get("FIP")]
            graded_day = _load_graded_for(d)
            settled_day = [g for g in graded_day if g.get("Hit") is not None]
            if fips and settled_day:
                daily_points.append({
                    "date": d,
                    "avg_starter_fip": sum(fips) / len(fips),
                    "hit_rate": sum(1 for g in settled_day if g["Hit"]) / len(settled_day),
                })
            progress.progress((i + 1) / len(chalk_dates), text=f"Tested {d} ({i + 1}/{len(chalk_dates)})")
        progress.empty()

        result = R.slate_chalk_correlation(daily_points, min_days=10)
        if result["correlation"] is None:
            st.info(result["note"] or "Not enough usable data to compute a real correlation.")
        else:
            r = result["correlation"]
            rc1, rc2 = st.columns(2)
            rc1.metric("Correlation (r)", f"{r:+.3f}")
            rc2.metric("Nights tested", result["n_days"])
            if r < -0.3:
                st.markdown("A real negative relationship — **consistent with** the hypothesis "
                           "(tougher slate-wide pitching paired with a chalkier day). "
                           "Consistent with, not proof of.")
            elif r > 0.3:
                st.markdown("A real positive relationship — this **contradicts** the hypothesis "
                           "as originally stated.")
            else:
                st.markdown("Close to zero — **no clear linear relationship** either way in "
                           "this window.")
            chart_df = (pd.DataFrame(daily_points)[["avg_starter_fip", "hit_rate"]]
                       .rename(columns={"avg_starter_fip": "Avg starter FIP",
                                        "hit_rate": "Day's hit rate"}))
            st.scatter_chart(chart_df, x="Avg starter FIP", y="Day's hit rate")
        st.caption("⚠️ Correlation, not causation, from a modest number of days on a genuinely "
                  "noisy real-world process — read this as suggestive at best, never proof, "
                  "regardless of which way it comes out. Same current-season-rates caveat as "
                  "Trend mode above.")
