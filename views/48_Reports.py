"""
Reports — P&L statements for any period, from the Bet Log (Nov 6). Owner only.

Pick a period; the page shows the statement (starting balance -> winnings / losses -> deposits / withdrawals -> ending
balance), breakdowns by sport, bet type, strategy and month, a tax summary, and the ledger, with CSV and PDF downloads.
Real-money bets only; deposits and withdrawals come from the Progression Plan. Numbers: reports.py.
"""
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

import betlog as B
import components as C
import model_store as MS
import progression as P
import reports as R

C.base_css()
C.page_header("📑", "Reports", "P&L statements from the Bet Log — any period, with CSV and PDF downloads.")

today = datetime.now(pytz.timezone("US/Eastern")).date()
plan = dict(P.DEFAULTS, **(MS.get_setting(P.SETTINGS_KEY, {}) or {}))

c1, c2 = st.columns([2, 3])
kind = c1.selectbox("Period", ["This month", "Last month", "This quarter", "Year to date", "Last year", "All time",
                               "Custom"], key="rp_period")
custom = None
if kind == "Custom":
    custom = c2.date_input("Dates", value=(today.replace(day=1), today), key="rp_dates")
    if not isinstance(custom, (list, tuple)) or len(custom) != 2:
        st.info("Pick a start and an end date.")
        st.stop()
start, end = R.period(kind, today, custom)
if kind == "All time":
    start = str(plan.get("start_date") or start)[:10]

try:
    bets = B.list_bets()
except Exception:                                               # noqa: BLE001
    bets = []
s = R.statement(bets, start, end, plan)


def money(x):
    return f"${x:,.2f}" if x >= 0 else f"−${-x:,.2f}"


st.markdown(f"#### Statement · {start} → {end}")
st.caption("Real-money bets only, dated by game night. Parlays count once. Deposits and withdrawals are recorded on the "
           "Progression Plan; they change the balance but are never profit.")
left, right = st.columns([3, 2])
with left:
    lines = [("Starting balance", s["starting_balance"], True),
             ("Gross winnings", s["winnings"], False),
             ("Gross losses", -s["losses_amt"], False),
             ("Net betting result", s["net"], True),
             ("Deposits", s["deposits"], False),
             ("Withdrawals", -s["withdrawals"], False),
             ("Ending balance", s["ending_balance"], True)]
    body = "\n".join(f"| **{lbl}** | **{money(v)}** |" if bold else f"| &nbsp;&nbsp;&nbsp;{lbl} | {money(v)} |"
                     for lbl, v, bold in lines)
    st.markdown("| | |\n|---|---:|\n" + body)
with right:
    st.metric("Net betting result", money(s["net"]),
              None if s["roi"] is None else f"{s['roi']:+.1%} on {money(s['staked'])} staked")
    st.metric("Record", f"{s['wins']}–{s['losses']}–{s['pushes']}", f"{s['bets']} settled", delta_color="off")
    if s["open"]["bets"]:
        st.caption(f"Still open in this period: {s['open']['bets']} bet(s), {money(s['open']['staked'])} staked "
                   "(not in the totals until they settle).")

if not s["bets"] and not s["transfers"]:
    st.info("No settled real-money bets in this period.")


def table(rows, first="Group"):
    if not rows:
        return
    df = pd.DataFrame([{first: r["name"], "Bets": r["bets"], "W–L–P": f"{r['wins']}–{r['losses']}–{r['pushes']}",
                        "Staked": r["staked"], "Winnings": r["winnings"], "Losses": r["losses_amt"], "Net": r["net"],
                        "ROI": r["roi"]} for r in rows])
    st.dataframe(df, hide_index=True, width="stretch",
                 column_config={k: st.column_config.NumberColumn(format="$%.2f")
                                for k in ("Staked", "Winnings", "Losses", "Net")}
                 | {"ROI": st.column_config.NumberColumn(format="percent")})


t1, t2, t3, t4, t7, t5, t6 = st.tabs(["By sport", "By bet type", "By strategy", "By month", "🧭 You vs the model",
                                     "🧾 Tax summary", "📖 Ledger"])
with t1:
    table(s["by_sport"], "Sport")
with t2:
    table(s["by_type"], "Type")
with t3:
    table(s["by_strategy"], "Strategy")
    st.caption("Strategy = the tag a bet was logged under (platform-test, live-tennis, game-lab ...).")
with t4:
    table(s["by_month"], "Month")
with t7:                                                        # Nov 8: where your own picks win and lose
    import pick_records as PR
    yours = PR.your_picks([b for b in bets if start <= str(b.get("slate_date") or "")[:10] <= end])
    if yours:
        st.dataframe(pd.DataFrame(yours), hide_index=True, width="stretch",
                     column_config={"Win %": st.column_config.NumberColumn(format="percent"),
                                    "Staked": st.column_config.NumberColumn(format="$%.2f"),
                                    "P/L": st.column_config.NumberColumn(format="$%.2f")})
        st.caption("Your settled real bets, grouped by the model's chance on that exact pick when it was logged. "
                   "Parlay legs are graded one by one (their money is in the Parlay row). If the 60%+ band wins and "
                   "the lower bands lose, the edge is in sticking to the model's strongest reads — and a 60% pick "
                   "still loses 4 times in 10, so judge a band over 30+ bets, not one night.")
    else:
        st.info("No settled real-money bets in this period.")
with t5:
    st.markdown(f"| | |\n|---|---:|\n| Gambling winnings (reported as income) | {money(s['tax']['winnings'])} |\n"
                f"| Gambling losses (itemized deduction only) | {money(s['tax']['losses'])} |\n"
                f"| Deductible losses, capped at winnings | {money(s['tax']['deductible_cap'])} |")
    st.caption("US returns ask for winnings and losses separately, not the net: winnings are income, and losses are "
               "deductible only if you itemize, up to the amount of winnings. Recent law changes may limit the "
               "deduction further — this is a summary for whoever prepares your return, not tax advice. Keep your "
               "sportsbook statements too.")
with t6:
    if s["ledger"]:
        df = pd.DataFrame(s["ledger"])
        st.dataframe(df[["date", "sport", "type", "bet", "odds", "stake", "result", "pnl", "strategy"]],
                     hide_index=True, width="stretch",
                     column_config={"stake": st.column_config.NumberColumn(format="$%.2f"),
                                    "pnl": st.column_config.NumberColumn("P&L", format="$%.2f")})
    for t in s["transfers"]:
        st.caption(f"{t['date']}: {'deposit' if t['amount'] > 0 else 'withdrawal'} {money(abs(t['amount']))}")

d1, d2 = st.columns(2)
name = f"h2_pnl_{start}_to_{end}"
d1.download_button("⬇️ Ledger (CSV)", R.ledger_csv(s), file_name=f"{name}.csv", mime="text/csv", width="stretch")
try:
    pdf = R.statement_pdf(s)
    d2.download_button("⬇️ Statement (PDF)", pdf, file_name=f"{name}.pdf", mime="application/pdf", width="stretch")
except Exception as exc:                                        # noqa: BLE001
    d2.caption(f"PDF unavailable ({type(exc).__name__}).")
