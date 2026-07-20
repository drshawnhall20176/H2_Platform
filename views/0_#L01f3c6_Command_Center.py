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
 
import retro as R
import betlog as B
import sports
import best_bets_data as BBD
import grading
import quick_log
 
_active = sports.active()
 
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
 
st.markdown(f"""
<div class="h2-hero">
  <h1>🏆 H2 Sports — Command Center</h1>
  <p>Trade sports, don't bet sports. A layered model that prices every prop, sizes with
     discipline, and proves itself with closing-line value and calibration. — {_active.icon} {_active.label}</p>
</div>
""", unsafe_allow_html=True)

if not sports.require_live_engine("Command Center"):
    st.stop()

# Icon per market, for the tab strips below — falls back to a generic icon for anything not
# listed (future sports don't need an entry here to render correctly, just less decoratively).
_MARKET_ICONS = {
    "Batter HR": "🏠", "Pitcher Strikeouts": "⚡", "Batter Total Bases": "📊",
    "Batter Total Hits": "✅", "Batter Strikeouts": "🌀", "Pitcher Outs": "🎯", "Pitcher Walks": "🚶",
    "Batter Runs": "🏃", "Batter RBIs": "💪", "Batter Stolen Bases": "💨", "Pitcher Earned Runs": "🛡️",
    "Points": "🏀", "Rebounds": "🔁", "Assists": "🤝", "Threes Made": "3️⃣",
}


# ---------- loaders ----------
def _board_mlb(date_str):
    return BBD.load_mlb_best_bets_board(date_str, BBD.E.FIP_CONSTANT_DEFAULT)


def _board_generic(sport_key, date_str):
    return BBD.load_generic_best_bets_board(sport_key, date_str)


def _board(sport_key, date_str):
    return _board_mlb(date_str) if sport_key == "MLB" else _board_generic(sport_key, date_str)


@st.cache_data(ttl=300, show_spinner=False)
def today_board(sport_key, date_str):
    plays, meta = _board(sport_key, date_str)
    return plays, len(meta)


@st.cache_data(ttl=900, show_spinner=False)
def yesterday_catches(sport_key, date_str, markets):
    plays, _ = _board(sport_key, date_str)
    results = sports.get(sport_key).engine.get_player_results(date_str)
    return {m: R.market_report(plays, results, m)["caught"] for m in markets}, len(results)


today = datetime.now().strftime("%Y-%m-%d")
yest = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

with st.spinner("Loading tonight's board..."):
    try:
        plays, n_games = today_board(_active.key, today)
    except Exception:
        plays, n_games = [], 0

bets = B.list_bets(sport=_active.key)
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

# Owner-only data-health pointer — the Data Health page itself is gated the same way, so this
# stays hidden for a public/Discord audience rather than linking to a page they can't open.
if st.secrets.get("AUDIENCE", "owner") == "owner":
    import data_freshness as DF
    _dh_results = DF.check_all_sources()
    _dh_overall = DF.overall_status(_dh_results)
    _DH_ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
    st.page_link("views/17_Data_Health.py",
                label=f"{_DH_ICON[_dh_overall]} Data health — see what's behind these numbers →",
                icon="🩺")
 
# ---------- the model pipeline (the pitch) ----------
st.markdown("##### How every play is built")
if _active.key == "MLB":
    st.markdown(
        '<span class="pipe">Matchup (odds-ratio)</span><span class="pipe-arrow">→</span>'
        '<span class="pipe">Handedness splits</span><span class="pipe-arrow">→</span>'
        '<span class="pipe">Statcast expected power</span><span class="pipe-arrow">→</span>'
        '<span class="pipe">Weather & wind</span><span class="pipe-arrow">→</span>'
        '<span class="pipe">Live EV vs market</span><span class="pipe-arrow">→</span>'
        '<span class="pipe">Kelly sizing</span><span class="pipe-arrow">→</span>'
        '<span class="pipe">Logged · CLV · calibration</span>',
        unsafe_allow_html=True)
else:
    st.markdown(
        '<span class="pipe">Last 10 games</span><span class="pipe-arrow">→</span>'
        '<span class="pipe">Bootstrap resample</span><span class="pipe-arrow">→</span>'
        '<span class="pipe">Rotation-minutes filter</span><span class="pipe-arrow">→</span>'
        '<span class="pipe">Live EV vs market</span><span class="pipe-arrow">→</span>'
        '<span class="pipe">Kelly sizing</span><span class="pipe-arrow">→</span>'
        '<span class="pipe">Logged · CLV · calibration</span>',
        unsafe_allow_html=True)
    st.caption("v1 model — opponent defense and pace aren't incorporated yet.")
 
st.divider()
left, right = st.columns([3, 2])
 
# ---------- tonight's top plays ----------
with left:
    st.subheader("⭐ Tonight's top leans")
    # Owner-only Graded Picks pointer — Graded Picks itself is gated the same way (moved to
    # owner-only directly on request, to guarantee no broken public links as the subscriber
    # split hardens), so this stays hidden for a public/Discord audience rather than linking to
    # a page they can't open, the same pattern already used just below for Data Health.
    if st.secrets.get("AUDIENCE", "owner") == "owner":
        st.page_link("views/16_Graded_Picks.py", label="See the full slate, graded game by game →",
                    icon="🏅")
    if plays:
        # A REAL, CONFIRMED FIX, not the original design -- this used to sort by raw Conviction
        # directly, which can genuinely INVERT against the letter-grade system every other page
        # (Graded Picks, Suggested Parlays, Speculative Basket) already uses: a raw 2.5x on HR
        # (ceiling ~9.09, a "B") can outrank a raw 1.8x on a near-50%-reference market (ceiling
        # ~2.0, a genuine "A") purely because HR's own raw numbers run bigger, even though the
        # SECOND play is the stronger one by every other page's own grading logic. Grading every
        # play here too, and sorting/filtering by the SAME ceiling-normalized rank_value grading.
        # conviction_to_grade already exposes for exactly this reason, means "Tonight's top
        # leans" now agrees with what Graded Picks itself would show for the same slate --
        # intra-page consistency, not a second, silently different ranking of "the same" model.
        # A REAL, CONFIRMED FIX, not the original design -- Top Leans used to sort by rank_value
        # (the ceiling-normalized Conviction metric), which is the wrong number for what a "top
        # lean" actually means to a real person. Confirmed directly with a real, reported
        # example: a genuine longshot Triples play (11% real chance of happening, an 89% chance
        # it doesn't) can carry a raw Conviction of 4.44x purely because Triples' reference rate
        # is so low (~2.5%) that even a modest real probability looks huge relative to it --
        # rank_value would still rate this a real, valid grade, but "leans" colloquially means
        # "I lean toward this happening," which is a probability question, not an edge-relative-
        # to-typical one. This is the SAME real distinction already built into Suggested Parlays'
        # Safer/Steady tiers -- Top Leans just never got the same treatment. Graded Picks itself
        # stays rank_value-sorted on purpose (its entire identity IS the letter-grade system),
        # but this widget's own name and purpose are different. See grading.build_top_leans' own
        # docstring for the full reasoning -- pulled out of this view for the same reason every
        # other piece of real logic on this platform lives in grading.py, not trusted by eye in
        # the browser.
        _TOP_TABS = [("All", None)] + [(f"{_MARKET_ICONS.get(m, '🔹')} {m}", m)
                                       for m in _active.market_map.keys()]
        _ttabs = st.tabs([t[0] for t in _TOP_TABS])
        for _tb, (_lab, _mkt) in zip(_ttabs, _TOP_TABS):
            with _tb:
                if _mkt is None:
                    subset = grading.build_top_leans(plays, per_market=2)
                    st.caption("Best two leans from each market — so this isn't just one market's tab again.")
                else:
                    subset = [p for p in grading.build_top_leans(plays, per_market=8)
                             if p["Market"] == _mkt][:8]
                if subset:
                    for p in subset:
                        p["Grade"] = p["_grade"]["letter"]
                    tdf = pd.DataFrame(subset)[["Grade", "ModelProb", "Player", "Market", "Side",
                                                "Line", "Conviction", "Why"]]
                    st.dataframe(
                        tdf.rename(columns={"ModelProb": "Model %", "Why": "Reasoning"})
                        .style.format({"Model %": "{:.0%}", "Conviction": "{:.2f}×", "Line": "{:g}"})
                        .theme_gradient(cmap="Greens", subset=["Model %"]),
                        hide_index=True, use_container_width=True, height=330)
                else:
                    st.caption("No leans in this market on tonight's board.")
        st.caption("Ranked by real probability of hitting (Model %), among plays that already "
                  "clear a real grade — not by Conviction alone, which measures edge relative to "
                  "a market-typical rate and can run high on a genuine longshot in a rare-event "
                  "market. Grade still reflects the same methodology as Graded Picks.")
        # Quick-log widget, added directly on request: during a real, narrow pick-making window,
        # having to separately re-enter a pick into Bet Log is real friction that gets skipped in
        # favor of just making the pick. Uses the same curated "best 2 per market" set shown in
        # the All tab -- the most representative summary of tonight's top leans, not a separate
        # widget per market tab (which would mean 15+ redundant copies). Owner-only (quick_log
        # itself enforces this, so this stays hidden for a public/Discord audience even though
        # Command Center itself is a public page).
        quick_log.render_quick_log(grading.build_top_leans(plays, per_market=2), today,
                                   _active.key, key_prefix="top_leans")
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
if _active.key == "MLB":
    st.caption("Players whose result cleared the line AND sat in the model's top plays before the game. "
               "Surfaced by matchup, platoon, Statcast, and weather — not name value. (Exploratory; see Retrospective.)")
else:
    st.caption("Players whose result cleared the line AND sat in the model's top plays before the game. "
               "Surfaced by recent form, not name value. (Exploratory; see Retrospective.)")
try:
    catches, _ = yesterday_catches(_active.key, yest, tuple(_active.market_map.keys()))
except Exception:
    catches = {}

_caught_markets = list(_active.market_map.keys())
_ctabs = st.tabs([f"{_MARKET_ICONS.get(m, '🔹')} {m}" for m in _caught_markets])
for _tb, _mkt in zip(_ctabs, _caught_markets):
    with _tb:
        caught = catches.get(_mkt, [])
        if caught:
            cdf = pd.DataFrame(caught[:6])
            cdf["Pre-game rank"] = cdf.apply(lambda r: f"#{r['Rank']} of {r['OfTotal']}", axis=1)
            cols = [c for c in ["Player", "Value", "Line", "ModelProb", "Pre-game rank"] if c in cdf.columns]
            cdf = cdf[cols].rename(columns={"ModelProb": "Model %", "Value": _mkt})
            fmt = {"Model %": "{:.0%}", "Line": "{:g}", _mkt: "{:.1f}"}
            st.dataframe(cdf.style.format({k: v for k, v in fmt.items() if k in cdf.columns}, na_rep="—"),
                        hide_index=True, use_container_width=True)
        else:
            st.caption("Nothing cleared the line in the model's top plays for this market last night, "
                       "or results aren't final yet.")

st.divider()
st.caption("⚖️ For analysis and entertainment. Not financial advice and not a guarantee — outcomes "
           "are uncertain and variance is real. Proof metrics reflect logged activity only; empty "
           "panels mean no track record yet, by design. Bet responsibly.")
