"""
My Coach (Nov 8) — simple tables from your own settled bets that point you toward better choices. Owner only.
Numbers: coach.py. Updates every morning as the review settles last night's bets.
"""
import pandas as pd
import streamlit as st

import betlog as B
import coach as CO
import components as C

C.base_css()
C.page_header("🧑‍🏫", "My Coach", "What's working, what isn't, and simple rules for your next bet — from your own bets.")

period = st.radio("Look at", ["Last 7 days", "Last 30 days", "All time"], index=1, horizontal=True, key="coach_period")
days = {"Last 7 days": 7, "Last 30 days": 30, "All time": None}[period]
try:
    bets = CO.in_period(B.list_bets(), days)
except Exception:                                               # noqa: BLE001
    bets = []

PCT = st.column_config.NumberColumn(format="percent")
MONEY = st.column_config.NumberColumn(format="$%.2f")
CFG = {"Win %": PCT, "Need to win": PCT, "Money": MONEY, "Model said": PCT}


def show(rows, cols=None):
    if not rows:
        st.caption("Nothing here yet for this period.")
        return
    df = pd.DataFrame(rows)
    if cols:
        df = df[[c for c in cols if c in df]]
    st.dataframe(df, hide_index=True, width="stretch", column_config=CFG)


with st.expander("📖 How to read these tables", expanded=False):
    st.markdown(
        "- **Record**: wins–losses.\n"
        "- **Win %**: how often you won.\n"
        "- **Need to win**: how often the price needs you to win just to break even. At −110 that's 52%; at −150 it's 60%.\n"
        "  If *Win %* is below *Need to win*, that kind of bet loses money over time even when it wins more than it loses.\n"
        "- **Money**: what you actually won or lost.\n"
        "- **Verdict**: 🟢 keep doing it · 🟡 close, watch the price · 🔴 stop or bet smaller · ⚪ fewer than "
        f"{CO.MIN_N} bets, too early to judge.")

st.markdown("#### ✅ Your rules for the next bet")
for r in CO.rules(bets):
    st.markdown(f"- {r}")

st.markdown("#### 📋 Your report card")
st.caption("Each line is one kind of choice. The model lines count every pick you made, parlay legs included; "
           "their money is from single bets only.")
show(CO.report_card(bets), ["What", "Bets", "Record", "Win %", "Need to win", "Money", "Verdict"])

best, worst = CO.best_and_worst(bets)
c1, c2 = st.columns(2)
with c1:
    st.markdown("#### 💰 Where you make money")
    show(best, ["What", "Record", "Money", "Verdict"])
with c2:
    st.markdown("#### 🕳️ Where you lose money")
    show(worst, ["What", "Record", "Money", "Verdict"])
st.caption("Sport and market, 3 or more bets.")

st.markdown("#### ⚔️ When you went against the model")
st.caption("Picks where the model gave your side less than a 50% chance.")
am = CO.against_model(bets)
show(am["by_sport"], ["What", "Bets", "Record", "Win %", "Money", "Verdict"])
if am["recent"]:
    with st.expander("The most recent ones"):
        show(am["recent"])

st.markdown("#### 🏷️ Price check")
st.caption("Single bets by the price you took. Heavier prices need you to win more often.")
show(CO.price_check(bets), ["What", "Bets", "Record", "Win %", "Need to win", "Money", "Verdict"])

with st.expander("📚 Everything, by sport and market"):
    show(CO.by_group(bets), ["What", "Bets", "Record", "Win %", "Need to win", "Money", "Verdict"])
