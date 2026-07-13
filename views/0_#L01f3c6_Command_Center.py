"""
Command Center — the executive overview.
 
One screen that tells the story: a rigorous, layered model that prices every prop, sizes
with discipline, and — the differentiator — holds itself accountable with CLV and calibration.
 
HONESTY IS THE DESIGN. Proof panels render the FRAMEWORK with honest empty states until real
bets are logged. Nothing here is a fabricated track record. Where a number would be a forward
claim, it reads "tracking since inception" until the Bet Log fills it in for real.
"""
 
import streamlit as st
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import pandas as pd
from datetime import datetime, timedelta
import plotly.graph_objects as go
 
import mlb_engine as E
import projections as P
import statcast_data as SC
import weather as WX
import retro as R
import betlog as B
 
 
st.markdown("""
<style>
.h2-hero {background:linear-gradient(110deg,#0f172a,#1e293b);padding:22px 26px;border-radius:14px;
          color:#f8fafc;margin-bottom:6px;}
.h2-hero h1 {margin:0;font-size:30px;letter-spacing:-0.5px;}
.h2-hero p {margin:4px 0 0;color:#94a3b8;font-size:15px;}
.pipe {display:inline-block;background:#1e293b;color:#e2e8f0;border:1px solid #334155;
       padding:6px 12px;border-radius:999px;margin:3px 4px;font-size:13px;}
.pipe-arrow {color:#64748b;margin:0 2px;}
</style>
""", unsafe_allow_html=True)
 
st.markdown("""
<div class="h2-hero">
  <h1>🏆 H2 Sports — Command Center</h1>
  <p>Trade sports, don't bet sports. A layered model that prices every prop, sizes with
     discipline, and proves itself with closing-line value and calibration.</p>
</div>
""", unsafe_allow_html=True)
 
 
# ---------- loaders ----------
@st.cache_data(ttl=3600, show_spinner=False)
def _statcast():
    return SC.load()
 
 
@st.cache_data(ttl=1800, show_spinner=False)
def _weather(keys):
    out = {}
    for vid, gdate, vname in keys:
        if vid is not None and vid not in out:
            try:
                out[vid] = WX.get_game_weather(vid, gdate, vname)
            except Exception:
                out[vid] = None
    return out
 
 
def _board(date_str):
    rows, meta = E.build_slate(date_str)
    sc, k = _statcast()
    wx = _weather(tuple((m.get("venue_id"), m.get("game_date"), m.get("venue")) for m in meta))
    for r in rows:
        w = wx.get(r.get("_venue_id"))
        r["_weather_hr"] = w["hr_factor"] if w else 1.0
    P.enrich_hitter_rows(rows, seed=7, statcast=sc, statcast_k=k)
    pr = P.build_pitcher_projection_rows(rows, meta, seed=11)
    return P.build_best_bets(rows, pr), meta
 
 
@st.cache_data(ttl=300, show_spinner=False)
def today_board(date_str):
    plays, meta = _board(date_str)
    return plays, len(meta)
 
 
@st.cache_data(ttl=900, show_spinner=False)
def yesterday_catches(date_str):
    plays, _ = _board(date_str)
    results = E.get_player_results(date_str)
    return {
        "Batter HR": R.homer_report(plays, results)["caught"],
        "Pitcher Strikeouts": R.pitcher_k_report(plays, results)["caught"],
        "Batter Total Bases": R.batter_tb_report(plays, results)["caught"],
        "Batter Total Hits": R.batter_hits_report(plays, results)["caught"],
    }, len(results)
 
 
today = datetime.now().strftime("%Y-%m-%d")
yest = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
 
with st.spinner("Loading tonight's board..."):
    try:
        plays, n_games = today_board(today)
    except Exception:
        plays, n_games = [], 0
 
bets = B.list_bets()
s = B.summary(bets)
 
# ---------- KPI row ----------
top = plays[0] if plays else None
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Tonight's games", n_games)
k2.metric("Model plays", len(plays))
k3.metric("Top lean", f"{top['Conviction']:.1f}×" if top else "—",
          help=f"{top['Player']} {top['Market']} {top['Side']}" if top else None)
k4.metric("Beat-close rate", f"{s['beat_close_rate']:.0f}%" if s["beat_close_rate"] is not None else "—",
          help="Share of bets that beat the closing line. The core proof metric.")
k5.metric("Avg CLV", f"{s['avg_clv']:+.2f}%" if s["avg_clv"] is not None else "—")
 
# ---------- the model pipeline (the pitch) ----------
st.markdown("##### How every play is built")
st.markdown(
    '<span class="pipe">Matchup (odds-ratio)</span><span class="pipe-arrow">→</span>'
    '<span class="pipe">Handedness splits</span><span class="pipe-arrow">→</span>'
    '<span class="pipe">Statcast expected power</span><span class="pipe-arrow">→</span>'
    '<span class="pipe">Weather & wind</span><span class="pipe-arrow">→</span>'
    '<span class="pipe">Live EV vs market</span><span class="pipe-arrow">→</span>'
    '<span class="pipe">Kelly sizing</span><span class="pipe-arrow">→</span>'
    '<span class="pipe">Logged · CLV · calibration</span>',
    unsafe_allow_html=True)
 
st.divider()
left, right = st.columns([3, 2])
 
# ---------- tonight's top plays ----------
with left:
    st.subheader("⭐ Tonight's top leans")
    if plays:
        _TOP_TABS = [("All", None), ("🏠 HR", "Batter HR"), ("⚡ K", "Pitcher Strikeouts"),
                     ("📊 TB", "Batter Total Bases"), ("✅ Hits", "Batter Total Hits")]
        _ttabs = st.tabs([t[0] for t in _TOP_TABS])
        for _tb, (_lab, _mkt) in zip(_ttabs, _TOP_TABS):
            with _tb:
                if _mkt is None:
                    # "All" = a cross-market summary, NOT a raw conviction sort. Since HR is the
                    # rarest event it always wins conviction, so sorting everything by conviction
                    # just reproduces the HR tab. Instead show the best 2 leans from each market.
                    picks, seen = [], {}
                    for p in plays:                       # plays are already conviction-sorted
                        m = p["Market"]
                        if seen.get(m, 0) < 2:
                            picks.append(p)
                            seen[m] = seen.get(m, 0) + 1
                    subset = sorted(picks, key=lambda p: -p.get("Conviction", 0))
                    st.caption("Best two leans from each market — so this isn't just the HR tab again.")
                else:
                    subset = [p for p in plays if p["Market"] == _mkt][:8]
                if subset:
                    tdf = pd.DataFrame(subset)[["Conviction", "Player", "Market", "Side",
                                                "Line", "ModelProb", "Why"]]
                    st.dataframe(
                        tdf.rename(columns={"ModelProb": "Model %", "Why": "Reasoning"})
                        .style.format({"Model %": "{:.0%}", "Conviction": "{:.2f}×", "Line": "{:g}"})
                        .theme_gradient(cmap="Greens", subset=["Conviction"]),
                        hide_index=True, use_container_width=True, height=330)
                else:
                    st.caption("No leans in this market on tonight's board.")
        st.caption("Model conviction, not guaranteed value — priced against the live market on the Edge Board.")
    else:
        st.info("No games on the board right now. Top leans appear here on an active slate.")
 
# ---------- proof panel (the hero) ----------
with right:
    st.subheader("🧾 The proof")
    clv_bets = [b for b in bets if b.get("close_odds") is not None and b.get("entry_odds") is not None]
    if clv_bets:
        clv_bets = sorted(clv_bets, key=lambda b: b.get("ts_placed", ""))
        running, tot = [], 0.0
        for i, b in enumerate(clv_bets, 1):
            tot += B.clv_pct(b["entry_odds"], b["close_odds"]) or 0
            running.append(tot / i)
        fig = go.Figure(go.Scatter(y=running, mode="lines+markers", line=dict(color="#22c55e")))
        fig.add_hline(y=0, line_dash="dash", line_color="#64748b")
        fig.update_layout(height=240, margin=dict(l=10, r=10, t=24, b=10),
                          title="Average CLV over time (%)", template="plotly_white")
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"Positive and climbing = beating the market. {len(clv_bets)} bets with closing lines.")
    else:
        st.info("**Tracking since inception.** CLV and calibration populate here as bets are logged "
                "and settled — this is the honest, forward-tested track record, not a backtest. "
                "Log plays from the Edge Board to begin.", icon="🧭")
 
    cal = B.calibration(bets, n_bins=5) if bets else []
    if cal:
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines",
                                  line=dict(dash="dash", color="#94a3b8"), showlegend=False))
        fig2.add_trace(go.Scatter(x=[c["predicted"] for c in cal], y=[c["actual"] for c in cal],
                                  mode="markers", marker=dict(size=12, color="#7c3aed"), showlegend=False))
        fig2.update_layout(height=240, margin=dict(l=10, r=10, t=24, b=10),
                           title="Calibration: predicted vs actual", template="plotly_white",
                           xaxis_range=[0, 1], yaxis_range=[0, 1])
        st.plotly_chart(fig2, use_container_width=True)
 
# ---------- model-caught highlight (yesterday) ----------
st.divider()
st.subheader("🎯 The model caught these — last night's non-obvious plays")
st.caption("Players whose result cleared the line AND sat in the model's top plays before the game. "
           "Surfaced by matchup, platoon, Statcast, and weather — not name value. (Exploratory; see Retrospective.)")
try:
    catches, _ = yesterday_catches(yest)
except Exception:
    catches = {}
 
_CAUGHT_TABS = [("🏠 HR", "Batter HR", "HR", "Model HR%"),
                ("⚡ Pitcher K", "Pitcher Strikeouts", "K", "Model %"),
                ("📊 Total Bases", "Batter Total Bases", "TB", "Model %"),
                ("✅ Hits", "Batter Total Hits", "Hits", "Model %")]
_ctabs = st.tabs([t[0] for t in _CAUGHT_TABS])
for _tb, (_lab, _mkt, _val, _plabel) in zip(_ctabs, _CAUGHT_TABS):
    with _tb:
        caught = catches.get(_mkt, [])
        if caught:
            cdf = pd.DataFrame(caught[:6])
            cdf["Pre-game rank"] = cdf.apply(lambda r: f"#{r['Rank']} of {r['OfTotal']}", axis=1)
            cols = [c for c in ["Player", _val, "Line", "ModelProb", "Pre-game rank"] if c in cdf.columns]
            st.dataframe(
                cdf[cols].rename(columns={"ModelProb": _plabel})
                .style.format({_plabel: "{:.0%}", "Line": "{:g}"}, na_rep="—"),
                hide_index=True, use_container_width=True)
        else:
            st.caption("Nothing cleared the line in the model's top plays for this market last night, "
                       "or results aren't final yet.")
 
st.divider()
st.caption("⚖️ For analysis and entertainment. Not financial advice and not a guarantee — outcomes "
           "are uncertain and variance is real. Proof metrics reflect logged activity only; empty "
           "panels mean no track record yet, by design. Bet responsibly.")
