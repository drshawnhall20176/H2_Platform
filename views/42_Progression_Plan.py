"""
Progression Plan — the slow-build framework for running the platform as a business (Nov 3). Owner only.

Reads the Bet Log (real-money bets only, every sport) against a plan the owner sets once: starting bankroll and date,
unit size as a share of the bankroll, target ROI and the monthly income goal. Shows which stage the record has earned
(Prove -> Scale -> Go), the gates still open, the bankroll path, month-by-month results, discipline checks and the
math behind the income goal. The Bet Log stays the ledger; nothing is entered twice. Numbers: progression.py.
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import betlog as B
import components as C
import model_store as MS
import progression as P

C.base_css()
C.page_header("🧭", "Progression Plan",
              "Build it slowly: flat stakes on quality singles, judged by the month, with stakes going up only "
              "after the record earns it.")

saved = MS.get_setting(P.SETTINGS_KEY, {}) or {}
s = dict(P.DEFAULTS, **saved)

with st.expander("⚙️ Your plan", expanded=not saved):
    with st.form("prog_plan"):
        c1, c2, c3 = st.columns(3)
        start_bankroll = c1.number_input("Starting bankroll ($)", min_value=0.0, value=float(s["start_bankroll"]), step=100.0)
        start_date = c2.date_input("Plan start date", value=pd.to_datetime(s["start_date"]).date())
        unit_pct = c3.number_input("Unit (% of bankroll per bet)", min_value=0.25, max_value=5.0,
                                   value=float(s["unit_pct"]) * 100, step=0.25) / 100
        c4, c5, c6 = st.columns(3)
        monthly_goal = c4.number_input("Monthly income goal ($)", min_value=0.0, value=float(s["monthly_goal"]), step=250.0)
        target_roi = c5.number_input("Target ROI (%)", min_value=0.5, max_value=10.0,
                                     value=float(s["target_roi"]) * 100, step=0.5) / 100
        bets_pm = c6.number_input("Singles per month", min_value=10, max_value=2000, value=int(s["bets_per_month"]), step=10)
        scaled_from = st.text_input("Scaling started (YYYY-MM, leave blank until you reach Stage 2)",
                                    value=str(s.get("scaled_from") or ""))
        if st.form_submit_button("Save plan"):
            new = {"start_bankroll": start_bankroll, "start_date": start_date.isoformat(), "unit_pct": unit_pct,
                   "monthly_goal": monthly_goal, "target_roi": target_roi, "bets_per_month": int(bets_pm),
                   "scaled_from": scaled_from.strip() or None}
            if MS.save_setting(P.SETTINGS_KEY, new):
                st.success("Saved.")
                s = dict(P.DEFAULTS, **new)
            else:
                st.error("Couldn't save the plan.")

try:
    bets = B.list_bets(is_real_bet=True)
except Exception:                                               # noqa: BLE001
    bets = []
r = P.plan(s, bets)

STAGES = {1: ("1 · Prove", "Small flat stakes until 1,000 settled singles show a real edge."),
          2: ("2 · Scale", "Stakes follow the bankroll. Hold here until a year of months supports the income goal."),
          3: ("3 · Go", "The record supports the income goal at this size.")}
name, why = STAGES[r["stage"]]
st.markdown(f"### Stage {name}")
st.caption(why)


def _pct(x, sign=False):
    return "—" if x is None else (f"{x:+.1%}" if sign else f"{x:.0%}")


m1, m2, m3, m4 = st.columns(4)
m1.metric("Bankroll", f"${r['bankroll']:,.0f}", f"{r['profit']:+,.0f} since start")
m2.metric("Unit (next bet)", f"${r['unit']:,.2f}", f"{s['unit_pct']:.2%} of bankroll", delta_color="off")
m3.metric("Singles ROI", _pct(r["singles_roi"], True), f"{r['singles']} settled", delta_color="off")
m4.metric("Largest drawdown", _pct(r["max_dd"]) if r["path"] else "—")


def _gate_table(gates):
    rows = []
    for g in gates:
        v, need = g["value"], g["need"]
        if isinstance(need, float) and need < 5:
            show_v, show_n = _pct(v), f"{'≥' if g['how'] == '>=' else '≤'} {need:.0%}"
        else:
            show_v, show_n = "—" if v is None else f"{v:,.0f}", f"≥ {need:,}"
        rows.append({"Gate": g["label"], "Now": show_v, "Needed": show_n, "Met": "✅" if g["ok"] else "⬜"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


st.markdown("##### Gates to Stage 2 (Scale)")
_gate_table(r["prove"])
done = sum(1 for g in r["prove"] if g["ok"])
st.progress(done / len(r["prove"]), text=f"{done} of {len(r['prove'])} met")
if r["stage"] >= 2:
    st.markdown("##### Gates to Stage 3 (Go)")
    _gate_table(r["scale"])

if r["path"]:
    st.markdown("##### Bankroll")
    df = pd.DataFrame(r["path"])
    fig = go.Figure(go.Scatter(x=df["date"], y=df["bankroll"], mode="lines", line=dict(width=2)))
    fig.add_hline(y=float(s["start_bankroll"]), line_dash="dot", annotation_text="start")
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="$")
    st.plotly_chart(fig, width="stretch")

st.markdown("##### Month by month")
if r["months"]:
    st.dataframe(pd.DataFrame([{"Month": m["month"], "Bets": m["bets"], "Singles": m["singles"],
                                "Staked": f"${m['staked']:,.0f}", "Profit": f"${m['profit']:+,.0f}",
                                "ROI": _pct(m["roi"], True), "Singles ROI": _pct(m["singles_roi"], True),
                                "Beat the close": _pct(m["beat_close"]), "Parlay $ share": _pct(m["parlay_money"])}
                               for m in reversed(r["months"])]), hide_index=True, width="stretch")
else:
    st.caption("No settled real-money bets since the plan's start date yet.")

st.markdown("##### Discipline")
d = r["discipline"]
c1, c2 = st.columns(2)
c1.metric("Parlays' share of money staked", _pct(d["parlay_share"]),
          "within plan" if d["parlay_ok"] else f"over the {P.PARLAY_MONEY_CAP:.0%} cap", delta_color="off")
c2.metric(f"Singles over {P.OVERSIZE_UNITS:g} units", d["oversize"], delta_color="off")
if r["parlays"]:
    st.caption(f"Parlays: {r['parlays']} settled, ROI {_pct(r['parlay_roi'], True)}. Singles are the plan; "
               "parlays stay small.")

st.markdown("##### The income goal, in numbers")
g = r["goal"]
if g["turnover"]:
    st.markdown(
        f"- **${g['monthly']:,.0f} a month** at **{g['target_roi']:.1%}** ROI takes about **${g['turnover']:,.0f}** wagered a "
        f"month: {g['bets_per_month']} singles at about **${g['per_bet']:,.0f}** each.\n"
        f"- At {s['unit_pct']:.2%} a bet, that size needs a bankroll of about **${g['bankroll_needed']:,.0f}** "
        f"(today: ${r['bankroll']:,.0f}).\n"
        + (f"- Recent pace: **${g['pace']:+,.0f} a month** (last {min(3, len([m for m in r['months']]))} full months)."
           if g["pace"] is not None else "- Recent pace: no full month on record yet."))
t = r["tax"]
st.caption(f"Tax note (estimate only, not tax advice): since 2026 only 90% of gambling losses are deductible. Losing "
           f"stakes this year: ${t['losing_stakes']:,.0f}, so about ${t['nondeductible']:,.0f} can't be deducted and is "
           "taxed as if won. Check with a tax professional before scaling.")
