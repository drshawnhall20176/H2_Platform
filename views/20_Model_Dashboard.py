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
"""

import streamlit as st
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

if not sports.require_trading_access("Model Dashboard"):
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
st.subheader("🎯 The tool's own picks — how last night's slate graded out")
st.caption("Last night's board, rebuilt and graded against real results, filtered to C-or-better "
          "graded plays only — the same floor Suggested Parlays and Graded Picks already use to "
          "mean 'a real recommendation,' not every candidate the model ever considered.")

target = st.date_input("Slate to review", datetime.now() - timedelta(days=1), key="dash_slate_date")
date_str = target.strftime("%Y-%m-%d")

if _active.key == "MLB":
    fip_constant = st.number_input("FIP constant", value=E.FIP_CONSTANT_DEFAULT, step=0.01,
                                   key="dash_fip")

    @st.cache_data(ttl=600, show_spinner=False)
    def _load_graded_mlb(date_str_inner: str, fip_constant_inner: float):
        _, _, plays = BBD.build_mlb_board(date_str_inner, fip_constant_inner)
        results = E.get_player_results(date_str_inner)
        graded, _ = R.grade_slate(plays, results)
        return graded

    with st.spinner("Rebuilding last night's board..."):
        graded = _load_graded_mlb(date_str, fip_constant)
else:
    @st.cache_data(ttl=600, show_spinner=False)
    def _load_graded_generic(sport_key: str, date_str_inner: str):
        sport = sports.get(sport_key)
        rows, meta = sport.engine.build_slate(date_str_inner)
        plays = sport.projections.build_best_bets(rows)
        results = sport.engine.get_player_results(date_str_inner)
        graded, _ = R.grade_slate(plays, results)
        return graded

    with st.spinner("Rebuilding last night's board..."):
        graded = _load_graded_generic(_active.key, date_str)

st.warning("**Approximate, for exploration.** Rebuilding a past slate uses *current*-season "
          "rates, not the exact point-in-time numbers from that specific night — fine for "
          "checking last night, not a substitute for the Bet Log's own real, point-in-time "
          "record above.", icon="⚠️")

by_market = G.hit_miss_by_market(graded, min_grade_letter="C")
if by_market:
    _pie_grid(by_market, "hits", "misses", "market")
else:
    st.caption("No C-or-better graded picks settled for this slate yet — try an earlier date, "
              "or results may not be posted for this slate yet.")
