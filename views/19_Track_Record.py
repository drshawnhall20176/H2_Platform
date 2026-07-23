"""
Track Record — the proof page.

Plain-English, honesty-forward evidence that the model finds real value: our CLV curve,
per-market strengths/weaknesses, calibration, and *historical* graded selections. All numbers
come straight from the logged bet database — nothing here is hand-picked or mocked.

OWNER-ONLY as of 2026-07-18 — NOT primarily a monetization call, unlike Matchup Lab's own move to
owner-only the same day. There isn't yet enough real graded bet history logged for this page to
show anything meaningful, so a public visitor would just find an empty page — gated because it
currently has nothing to demonstrate, not because the content is being held back on purpose. This
doesn't reverse the earlier analytical case for showing it publicly once it DOES have real
history: a track record only shows historical, already-graded results, genuinely different from
handing over tonight's live board — that reasoning still holds, and is exactly why this is worth
revisiting (and likely un-gating) once there's enough real logged history for it to actually
demonstrate something. Closer to "not ready yet" than "not for you."

VS BET LOG, CLARIFIED DIRECTLY ON REQUEST AFTER A PLATFORM AUDIT: same real evidence, same
logged-bet data underneath both pages -- genuinely overlapping, not a mistake. This page is the
polished, narrative presentation for an audience who wants the story the numbers tell; Bet Log
is the full working ledger (log a bet, settle it, see raw numbers update) for actually managing
the record. See Bet Log's own docstring for the same note from its side.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import sports
import betlog as B
import retro as R


PALETTE = {"pos": "#16a34a", "neg": "#dc2626", "model": "#2563eb", "muted": "#94a3b8",
           "grid": "#e5e7eb"}


@st.cache_data(ttl=300, show_spinner=False)
def _load_bets(sport_key: str):
    # Real, placed wagers ONLY -- this feeds every section on this page that talks about real
    # money (CLV, P&L, "Record"). A tracking-only logged prediction (is_real_bet=False, added
    # directly on request for validating the model's own stated probabilities without real
    # stake) has no real entry/close odds anyway, so it was already inert here -- but filtering
    # explicitly, not relying on that as an implicit safety net, keeps this page's own "every
    # bet we log, graded against the closing line" promise honest by construction, not by luck.
    try:
        return B.list_bets(sport=sport_key, is_real_bet=True)
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def _load_all_tracked(sport_key: str):
    # BOTH real bets AND tracking-only predictions -- used ONLY by the hit/miss section below.
    # The calibration question ("the model said X%, did it happen?") is equally real evidence
    # whether real money was on it or not; a real $50 win and a $0 logged-only win are both
    # genuine confirmations of the model's own stated probability. Kept as a clearly separate
    # loader (not folded into _load_bets above) so it can never accidentally leak into the
    # real-money sections this page's own header promises are about real, placed wagers.
    try:
        return B.list_bets(sport=sport_key)
    except Exception:
        return []


_active = sports.active()
st.title(f"📊 Track Record  ·  {_active.icon} {_active.label}")
st.markdown("**Every bet we log, graded against the closing line — no cherry-picking, no deleting "
            "the losers.** This is our forward-tested record, updated as results come in. "
            "The single number we care about most is **CLV** (closing-line value): whether we "
            "consistently get better prices than where the market closes. Beating the close is the "
            "most reliable early sign of a real edge — long before win-rate or profit stabilize.")
st.page_link("views/18_#L01f4d2_Bet_Log.py",
             label="📒 Want the full working ledger behind these numbers? See Bet Log →", icon="📒")

if not sports.require_trading_access("Track Record"):
    st.stop()


bets = _load_bets(_active.key)
all_tracked = _load_all_tracked(_active.key)
if not all_tracked:
    st.info(f"📈 We're building our {_active.label} track record. Once bets are logged and settled, "
            "the proof shows up here — CLV, per-market performance, and calibration. Switch sports "
            "in the sidebar to see another league's record.")
    st.stop()

summ = B.summary(bets)
mkt = B.market_breakdown(bets)
cal = B.calibration(bets)
series = B.clv_series(bets)
clv_n = summ.get("clv_n") or 0

# ------------------------------------------------------------------ hero strip
st.divider()
h1, h2, h3, h4 = st.columns(4)
h1.metric("Avg CLV", f"{summ['avg_clv']:+.2f}%" if summ["avg_clv"] is not None else "—",
          help="Average closing-line value across all tracked bets. Positive = we beat the "
               "market's closing price on average. This is our headline signal.")
h2.metric("Bets tracked (with closing lines)", clv_n,
          help="How many bets have a recorded closing line — our real sample size. We show it "
               "openly; it tells you exactly how much to trust the numbers.")
h3.metric("Beat-close rate", f"{summ['beat_close_rate']:.0f}%" if summ["beat_close_rate"] is not None else "—",
          help="Share of bets that beat the closing line.")
h4.metric("Record (settled)", f"{summ['wins']}–{summ['losses']}",
          help="Wins–losses on settled bets. Win-rate is noisier than CLV over small samples, so "
               "we lead with CLV.")

if clv_n < 30:
    st.info(f"🌱 **Early sample ({clv_n} bets with closing lines).** Read the *direction and "
            "stability* of these numbers, not the exact decimal — a few dozen bets is a promising "
            "start, not a verdict. We'd want 100+ before calling anything proven.")
elif clv_n < 100:
    st.caption(f"Sample: {clv_n} bets with closing lines — enough to see the trend, still growing "
               "toward a fully settled read.")

# ------------------------------------------------------------------ CLV curve
st.divider()
st.subheader("📈 Closing-line value over time")
st.caption("Our cumulative average CLV as bets accumulate. Positive and stable = a real, "
           "repeatable edge — this is the closest thing we have to an equity curve.")
if len(series) >= 2:
    xs = [s["n"] for s in series]
    cum = [s["cum_avg"] for s in series]
    raw = [s["clv"] for s in series]
    win = min(10, max(3, len(series) // 4))          # light trailing smoother
    roll = [round(sum(raw[max(0, i - win + 1):i + 1]) / len(raw[max(0, i - win + 1):i + 1]), 2)
            for i in range(len(raw))]
    fig = go.Figure()
    fig.add_hline(y=0, line=dict(color=PALETTE["muted"], width=1, dash="dash"))
    fig.add_trace(go.Scatter(x=xs, y=cum, mode="lines", name="Cumulative avg CLV",
                             line=dict(color=PALETTE["pos"], width=3)))
    fig.add_trace(go.Scatter(x=xs, y=roll, mode="lines", name=f"Recent form ({win}-bet)",
                             line=dict(color=PALETTE["model"], width=1.5, dash="dot")))
    fig.update_layout(template="plotly_white", height=360, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis_title="Bets tracked", yaxis_title="Avg CLV (%)",
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0))
    st.plotly_chart(fig, use_container_width=True)
else:
    st.caption("The CLV curve appears once a few bets with closing lines are in.")

# ------------------------------------------------------------------ per-market strength
st.divider()
st.subheader("🎯 Where our edge lives — by market")
st.caption("Average CLV for each prop type. This is the honest map of our strengths and "
           "weaknesses: the markets where we consistently beat the close are where we're sharpest. "
           "We show it because knowing our own edges is the mark of a real model, not a tout.")
priced = [m for m in mkt if m["avg_clv"] is not None]
if priced:
    priced_sorted = sorted(priced, key=lambda m: m["avg_clv"])   # ascending for horizontal bars
    labels = [m["market"] for m in priced_sorted]
    vals = [m["avg_clv"] for m in priced_sorted]
    colors = [PALETTE["pos"] if v >= 0 else PALETTE["neg"] for v in vals]
    txt = [f"{v:+.1f}%  (n={m['clv_n']})" for v, m in zip(vals, priced_sorted)]
    figm = go.Figure(go.Bar(x=vals, y=labels, orientation="h", marker_color=colors,
                            text=txt, textposition="outside"))
    figm.add_vline(x=0, line=dict(color=PALETTE["muted"], width=1))
    figm.update_layout(template="plotly_white", height=max(280, 46 * len(labels)),
                       margin=dict(l=10, r=60, t=10, b=10), xaxis_title="Avg CLV (%)")
    st.plotly_chart(figm, use_container_width=True)

    small = [m for m in priced_sorted if m["clv_n"] < 5]
    if small:
        st.caption("⚠️ Markets with small samples (n<5) are directional only — one or two bets can "
                   "swing them. They'll settle as the sample grows.")

# full table (transparency)
with st.expander("Full per-market breakdown"):
    rows = [{"Market": m["market"], "Bets": m["bets"], "Settled": m["settled"],
             "Record": f"{m['wins']}–{m['losses']}",
             "Hit rate": (f"{m['hit_rate']*100:.0f}%" if m["hit_rate"] is not None else "—"),
             "Avg CLV": (f"{m['avg_clv']:+.1f}%" if m["avg_clv"] is not None else "—"),
             "CLV sample": m["clv_n"]} for m in mkt]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

# ------------------------------------------------------------------ calibration
st.divider()
st.subheader("🎚️ Are our probabilities honest?")
st.caption("When we say a play is 60%, does it hit ~60% of the time? Points on the dashed line = "
           "well-calibrated. We show the warts too: if our longshots run hot, you'll see it here.")
if cal and sum(c["n"] for c in cal) >= 8:
    figc = go.Figure()
    figc.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines", name="perfect",
                              line=dict(color=PALETTE["muted"], width=1.5, dash="dash")))
    figc.add_trace(go.Scatter(
        x=[c["predicted"] for c in cal], y=[c["actual"] for c in cal], mode="markers",
        name="our buckets",
        marker=dict(size=[max(10, min(40, c["n"] * 4)) for c in cal], color=PALETTE["model"],
                    opacity=0.75, line=dict(width=1, color="white")),
        text=[f"n={c['n']}" for c in cal], hovertemplate="predicted %{x:.0%}<br>actual %{y:.0%}<br>%{text}"))
    figc.update_layout(template="plotly_white", height=380, margin=dict(l=10, r=10, t=10, b=10),
                       xaxis=dict(title="We predicted", range=[0, 1], tickformat=".0%"),
                       yaxis=dict(title="It actually happened", range=[0, 1], tickformat=".0%"),
                       showlegend=False)
    st.plotly_chart(figc, use_container_width=True)
    st.caption("Bubble size = number of bets in that probability range. This chart needs volume to "
               "mean much — it sharpens as the sample grows.")
else:
    st.caption("The calibration chart appears once enough settled bets accumulate to bucket them.")

# ------------------------------------------------------------------ hit/miss (all tracked predictions)
st.divider()
st.subheader("🥧 Hit rate — every prediction we've tracked")
n_real = sum(1 for b in all_tracked if bool(b.get("is_real_bet") if b.get("is_real_bet") is not None else True))
n_tracking = len(all_tracked) - n_real
tracked_summary = B.summary(all_tracked)
tracked_settled = tracked_summary["wins"] + tracked_summary["losses"]
if n_tracking > 0:
    st.caption(f"Includes both real, placed bets ({n_real}) and predictions we logged just to check "
              f"the model's own stated probability against what happened, with no real money on "
              f"them ({n_tracking}) — a wider, honest read of whether the model's calls hold up, not "
              f"just the ones we backed with a stake. The sections above (CLV, P&L) are real-money "
              f"only; this one is broader on purpose.")
if tracked_settled >= 4:
    figh = go.Figure(go.Pie(
        labels=["Hit", "Miss"], values=[tracked_summary["wins"], tracked_summary["losses"]],
        marker=dict(colors=[PALETTE["pos"], PALETTE["neg"]]), hole=0.45,
        textinfo="label+percent", sort=False))
    figh.update_layout(template="plotly_white", height=320, margin=dict(l=10, r=10, t=10, b=10),
                       showlegend=False)
    st.plotly_chart(figh, use_container_width=True)
    st.caption(f"{tracked_summary['wins']}–{tracked_summary['losses']} across {tracked_settled} settled, "
              f"tracked predictions.")
else:
    st.caption("The hit/miss chart appears once a handful of tracked predictions have settled.")

# ------------------------------------------------------------------ receipts (historical, safe to show)
st.divider()
st.subheader("🧾 Recent results — the receipts")
st.caption("A rolling window of settled selections with how they graded. These are *past* calls "
           "(the games are over), shown for transparency. 🟢 hit · 🔴 miss.")
settled = [b for b in bets if B._result(b) in ("win", "loss")]
settled.sort(key=lambda b: b.get("ts_placed") or "", reverse=True)
if settled:
    rec = []
    for b in settled[:20]:
        res = B._result(b)
        clv = B.clv_pct(b.get("entry_odds"), b.get("close_odds"))
        line = b.get("line")
        rec.append({
            "": "🟢" if res == "win" else "🔴",
            "Player": b.get("player", "—"),
            "Market": b.get("market", "—"),
            "Pick": f"{b.get('side','')} {line:g}" if line is not None else b.get("side", ""),
            "Model %": (f"{b['model_prob']*100:.0f}%" if b.get("model_prob") is not None else "—"),
            "CLV": (f"{clv:+.1f}%" if clv is not None else "—"),
        })
    st.dataframe(pd.DataFrame(rec), hide_index=True, use_container_width=True)
else:
    st.caption("Settled selections show up here as results come in.")

# ------------------------------------------------------------------ footer / teaser + disclaimer
st.divider()
st.info("🔒 **This is our tracked record on past selections.** Tonight's live board — the model's "
        "current plays, priced against the market — is available to members. This page is the "
        "evidence; the subscription is the edge.")
st.caption("⚖️ For analysis and entertainment. Past performance does not guarantee future results — "
           "variance is real, and no bet is a lock. We track everything honestly precisely because "
           "the numbers, not hype, are the point. Bet responsibly.")
