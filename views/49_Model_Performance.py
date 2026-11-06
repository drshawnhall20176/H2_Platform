"""
Model Performance — Investor Relations (Nov 6). Owner only.

The evidence report for an investor: does the model have an edge, and how sure can anyone be yet? Every number carries
its sample size and a 95% range, and each section says plainly what it does and doesn't show. Built from records the
platform already keeps (investor.py): the locked Analyst Desk calls, each sport's latest morning review, closing-line
value, and the real-money Bet Log.
"""
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

import components as C
import investor as I

C.base_css()
C.page_header("📊", "Model Performance",
              "Investor Relations · the evidence for the model's edge — with sample sizes, ranges and caveats.")
today = datetime.now(pytz.timezone("US/Eastern")).date()
st.caption(f"As of {today:%B %-d, %Y}. Every figure is computed from records kept automatically as games are played; "
           "nothing is entered by hand or edited after the fact.")


def pct(x, sign=False):
    return "—" if x is None else (f"{x:+.1%}" if sign else f"{x:.0%}")


def rng(lo, hi):
    return "—" if lo is None else f"{lo:.0%}–{hi:.0%}"


@st.cache_data(ttl=900, show_spinner="Gathering the record…")
def load():
    import analyst_ledger as AL
    import betlog as B
    import model_store as MS
    try:
        calls = AL.fetch_calls()
    except Exception:                                           # noqa: BLE001
        calls = []
    reports = {}
    for sp in I.SPORTS:
        try:
            ms = MS.daily_review_mornings(sp)
            if ms:
                reports[sp] = MS.load_daily_review(sp, ms[0]) or {}
        except Exception:                                       # noqa: BLE001
            continue
    try:
        bets = B.list_bets()
    except Exception:                                           # noqa: BLE001
        bets = []
    return calls, reports, bets


calls, reports, bets = load()
lc = I.locked_calls(calls)
tags = I.use_tags(reports)
clv = I.closing_line(bets)
rm = I.real_money(bets)

# ---------------------------------------------------------------- headline
st.markdown("### At a glance")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Locked calls graded", f"{lc['n']:,}", f"hit {pct(lc['hit'])} vs model said {pct(lc['said'])}", delta_color="off")
graded_reads = sum(t["n"] for t in tags)
m2.metric("Model reads graded (30 days)", f"{graded_reads:,}", f"{len(reports)} sports", delta_color="off")
m3.metric("Beat the closing line", pct(clv["beat"]), f"{clv['moved']} priced moves since {clv['since']}", delta_color="off")
m4.metric("Real-money singles", f"{rm['singles']}", f"since {rm['first'] or '—'}", delta_color="off")
need = I.bets_for_edge(0.03)
st.info(f"**Where this stands:** the platform has been grading itself since late October. A real 3% edge at typical "
        f"prices takes roughly **{need:,} bets** to separate from luck with 95% confidence, so most figures below are "
        "early readings, labeled as such. The order of evidence, strongest first: calibration and closing-line value "
        "(they show up within hundreds of bets), then hit rates by tag, then money won (the noisiest).")

# ---------------------------------------------------------------- 1. locked calls
st.markdown("### 1 · Locked, public calls")
st.caption("Every Analyst Desk call is written to a ledger before the game starts and can't be changed afterward; the "
           "full record downloads as a CSV with a fingerprint on the Analyst Record page. The test: does the hit rate "
           "match the chance the model stated?")
st.caption("Context: until Nov 6 the Desk also locked calls from an older fallback model whose chances ran high (NBA: "
           "51% hit vs 61% stated over 976). The current props model's calls were honest (59% vs 57% over 296), and "
           "from Nov 6 the Desk locks only those. The record keeps every earlier call — nothing is removed.")
if lc["n"]:
    st.markdown(f"**{lc['n']:,} graded** of {lc['locked']:,} locked ({lc['first']} → {lc['last']}): hit "
                f"**{pct(lc['hit'])}** (95% range {rng(lc['lo'], lc['hi'])}) against **{pct(lc['said'])}** stated.")
    st.dataframe(pd.DataFrame([{"Sport": r["sport"], "Graded": r["n"], "Hit": r["hit"], "Model said": r["said"],
                                "95% range": rng(r["lo"], r["hi"])} for r in lc["by_sport"]]),
                 hide_index=True, width="stretch",
                 column_config={"Hit": st.column_config.NumberColumn(format="percent"),
                                "Model said": st.column_config.NumberColumn(format="percent")})
else:
    st.caption("No graded locked calls yet.")

# ---------------------------------------------------------------- 2. use tags
st.markdown("### 2 · Recommendations by tag")
st.caption("Every player-prop read is snapshotted at kickoff and graded against the box score the next morning. The "
           "Use tag is what the platform told members to do with it. A 🎟️ parlay leg needs ~60%; a 🎯 single needs to "
           "beat the price (~52% at −110). Last 30 days, from each sport's latest morning review.")
if tags:
    df = pd.DataFrame([{"Sport": t["sport"], "Use": t["use"], "Graded": t["n"], "Hit": t["hit"], "Model said": t["said"],
                        "95% range": rng(t["lo"], t["hi"]),
                        "Reading": I.verdict(t["n"], t["hit"],
                                             0.60 if "Parlay" in str(t["use"]) else (0.524 if "Single" in str(t["use"])
                                                                                    else None), t["lo"])}
                       for t in tags if t["use"] != "⛔ Pass"])
    st.dataframe(df, hide_index=True, width="stretch",
                 column_config={"Hit": st.column_config.NumberColumn(format="percent"),
                                "Model said": st.column_config.NumberColumn(format="percent")})
    passes = [t for t in tags if t["use"] == "⛔ Pass"]
    if passes:
        n = sum(t["n"] for t in passes)
        h = sum((t["hit"] or 0) * t["n"] for t in passes) / n if n else None
        st.caption(f"⛔ Pass reads (the ones the platform told members to skip): {n:,} graded, hit {pct(h)} — the "
                   "comparison group.")
else:
    st.caption("No morning reviews yet.")

# ---------------------------------------------------------------- 3. calibration
st.markdown("### 3 · Are the stated chances honest?")
st.caption("Reads grouped by the chance the model gave them: when it says 60%, do they hit about 60%? Honest chances "
           "are what make every other number trustworthy — and what members size their bets on.")
cal = I.calibration(reports)
if cal:
    st.dataframe(pd.DataFrame([{"Sport": c["sport"], "Model said": c["range"], "Reads": c["n"], "Average said": c["said"],
                                "Actually hit": c["hit"]} for c in cal]),
                 hide_index=True, width="stretch",
                 column_config={"Average said": st.column_config.NumberColumn(format="percent"),
                                "Actually hit": st.column_config.NumberColumn(format="percent")})
    st.caption("Where a sport's chances ran high, the platform measures it and applies a correction — approved by the owner, "
               "and only after it holds up on games it wasn't fitted to.")

# ---------------------------------------------------------------- 4. closing line
st.markdown("### 4 · Beating the closing line")
st.caption("The closing price is the market's final, sharpest estimate. Getting a better price than the close, consistently, "
           "is the standard early proof of an edge — it shows up long before profit does.")
if clv["n"]:
    st.markdown(f"Since **{clv['since']}** (the current model): **{clv['n']} bets** with a closing price. Of the "
                f"{clv['moved']} whose price moved, the bet got the better number **{pct(clv['beat'])}** of the time "
                f"(95% range {rng(clv['lo'], clv['hi'])}; 50% = no edge); average **{clv['avg']:+.2f}%** per bet. "
                f"{clv['unchanged']} closed at the same price.")
    if clv["moved"] < 200:
        st.caption(f"Early: {clv['moved']} priced moves is well short of the few hundred this needs.")
else:
    st.caption("Closing prices haven't been captured for enough current-model bets yet.")
_old = I.closing_line(bets, since=None)
st.caption(f"Earlier record (all time, {_old['n']} bets): beat the close {pct(_old['beat'])} of the bets whose price moved. "
           "It is mostly summer MLB bets whose entry and closing prices were taken at different lines, so it isn't a "
           f"like-for-like comparison; {_old['dropped']} pairs priced beyond ±{I.MAX_ODDS} are left out.")

# ---------------------------------------------------------------- 5. real money
st.markdown("### 5 · Real money (labeled: the noisiest measure)")
st.caption("The owner's own bets at small, flat stakes while the record is proven. Over a short window this mostly "
           "reflects luck — shown for completeness, not as the evidence.")
if rm["settled"]:
    st.markdown(f"{rm['first']} → {rm['last']}: **{rm['settled']} settled bets**, ROI **{pct((rm['roi'] or 0) / 100, True)}**. "
                f"Singles: {rm['singles']}, hit {pct(rm['singles_hit'])} (95% range {rng(rm['lo'], rm['hi'])}).")
st.markdown("---")
st.caption("Methodology: hit-rate ranges are 95% Wilson intervals. Voids (player didn't play) and pushes are excluded. "
           "Parlays count once. 'Model said' is the chance the model stated before the game. Sources: the Analyst Record "
           "ledger, the Postgame Review morning reports, and the Bet Log.")
