"""
Model Performance — Investor Relations (Nov 6). Owner only.

The evidence report for an investor: does the model have an edge, and how sure can anyone be yet? Every number carries
its sample size and a 95% range, and each section says plainly what it does and doesn't show.

Nov 22 (owner: should the counters start today, since the platform changed so much since October? -- "your call"): the
headline counts from the current platform's start (investor.ERA, Nov 21: the picks-as-shown ledger, rules frozen and
versioned). Everything earlier stays, in a labeled "Earlier builds" section -- a wiped record costs more trust in
diligence than a weak early number.
"""
from datetime import datetime, timedelta

import pandas as pd
import pytz
import streamlit as st

import props_engine as PE
import components as C
import investor as I

C.base_css()
C.page_header("📊", "Model Performance",
              "Investor Relations · the evidence for the model's edge — with sample sizes, ranges and caveats.")

today = datetime.now(pytz.timezone("US/Eastern")).date()
_era = datetime.fromisoformat(I.ERA).date()
st.caption(f"As of {today:%B %-d, %Y}. Every figure is computed from records kept automatically as games are played; "
           "nothing is entered by hand or edited after the fact.")


def pct(x, sign=False):
    return "—" if x is None else (f"{x:+.1%}" if sign else f"{x:.0%}")


def rng(lo, hi):
    return "—" if lo is None else f"{lo:.0%}–{hi:.0%}"


@st.cache_data(ttl=900, show_spinner="Gathering the record…")
def load(end: str):
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
    try:
        cur = I.current_record(end)
    except Exception:                                           # noqa: BLE001
        cur = {"strong": None, "money": None, "since": I.ERA}
    return calls, reports, bets, cur


calls, reports, bets, cur = load(today.isoformat())
strong, money = cur["strong"], cur["money"]
new_calls = [r for r in calls if str(r.get("call_date") or r.get("date") or "") >= I.ANALYST_ERA]
old_calls = [r for r in calls if str(r.get("call_date") or r.get("date") or "") < I.ANALYST_ERA]
lc = I.locked_calls(new_calls)
rm = I.real_money(bets, since=I.ERA)

# ---------------------------------------------------------------- headline
st.markdown(f"### The current platform · since {_era:%B %-d, %Y}")
st.caption(f"The record starts {_era:%b %-d}: the first slate where every pick the platform showed was saved before its "
           "game, graded afterward, and chosen by rules that are frozen and versioned (a rule change starts a new "
           "record instead of rewriting the old one). Everything before is kept below under **Earlier builds**.")
m1, m2, m3, m4 = st.columns(4)
if strong:
    m1.metric("Strongest list", f"{strong['hits']}–{strong['misses']}",
              f"{strong['units']:+.2f}u at the prices shown" if strong.get("priced") else None, delta_color="off")
else:
    m1.metric("Strongest list", "—", "no graded slate yet", delta_color="off")
if money:
    m2.metric("💰 picks", f"{money['hits']}–{money['misses']}",
              f"{money['units']:+.2f}u at the prices shown" if money.get("priced") else None, delta_color="off")
else:
    m2.metric("💰 picks", "—", "no graded slate yet", delta_color="off")
_b = strong if strong and strong.get("clv_moved") else None
m3.metric("Beat the closing line", pct(_b["beat_rate"]) if _b else "—",
          f"{_b['clv_moved']} strongest picks whose price moved" if _b else "no moves graded yet", delta_color="off")
m4.metric("Analyst calls locked", f"{lc['locked']:,}", f"since {datetime.fromisoformat(I.ANALYST_ERA):%b %-d}",
          delta_color="off")

need = I.bets_for_edge(0.03)
st.info(f"**Where this stands:** the current record is days old. A real 3% edge at typical prices takes roughly "
        f"**{need:,} bets** to separate from luck with 95% confidence. The order of evidence, strongest first: beating "
        "the closing line and honest chances (they show up within a few hundred picks), then hit rates, then money won "
        "(the noisiest).")

# ---------------------------------------------------------------- 1. picks as shown
st.markdown("### 1 · Every pick the platform showed")
st.caption("The Command Center's strongest list and every 💰 pick, saved the first time they appear before the game and "
           "graded the next morning at the price shown. Nothing is added after a game starts or removed after it loses.")
rows = []
for name, r in (("Strongest list", strong), ("💰 picks (props and game lines)", money)):
    if not r:
        continue
    rows.append({"List": name, "Graded": r["n"], "Record": f"{r['hits']}–{r['misses']}", "Hit": r["hit_rate"],
                 "Price needed": r.get("needed"), "95% range": rng(r.get("lo"), r.get("hi")),
                 "Units (1u a pick)": round(r["units"], 2) if r.get("priced") else None,
                 "Reading": I.verdict(r["n"], r["hit_rate"], r.get("needed"), r.get("lo"))})
if rows:
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"Hit": st.column_config.NumberColumn(format="percent"),
                                "Price needed": st.column_config.NumberColumn(format="percent")})
    st.caption("A pick can be on both lists, so the two rows aren't added together.")
else:
    st.caption("No graded slate yet — the first one is graded the morning after it's played.")

# ---------------------------------------------------------------- 2. closing line
st.markdown("### 2 · Beating the closing line")
st.caption("The closing price is the market's final, sharpest estimate. Since Nov 22 each shown pick's close is captured "
           "in the last minutes before its game. Getting a better number than the close, consistently, is the standard "
           "early proof of an edge — it shows up long before profit does. 50% = no edge.")
crow = []
for name, r in (("Strongest list", strong), ("💰 picks", money)):
    if r and r.get("clv_moved"):
        crow.append({"List": name, "Prices that moved": r["clv_moved"], "Beat the close": r["beat_rate"],
                     "95% range": rng(r.get("beat_lo"), r.get("beat_hi")),
                     "Average": f"{r['clv_avg']:+.1f}%" if r.get("clv_avg") is not None else "—"})
if crow:
    st.dataframe(pd.DataFrame(crow), hide_index=True, width="stretch",
                 column_config={"Beat the close": st.column_config.NumberColumn(format="percent")})
    if max(c["Prices that moved"] for c in crow) < 200:
        st.caption("Early: a few hundred moves are needed before this reads as evidence.")
else:
    st.caption("No closing prices graded yet for the current record.")

# ---------------------------------------------------------------- 3. calibration
st.markdown("### 3 · Are the stated chances honest?")
st.caption("Reads grouped by the chance the model gave them: when it says 60%, do they hit about 60%? Honest chances "
           "are what make every other number trustworthy — and what members size their bets on. Last 30 days, from each "
           "sport's latest morning review.")
cal = I.calibration(reports)
if cal:
    st.dataframe(pd.DataFrame([{"Sport": c["sport"], "Model said": c["range"], "Reads": c["n"], "Average said": c["said"],
                                "Actually hit": c["hit"]} for c in cal]),
                 hide_index=True, width="stretch",
                 column_config={"Average said": st.column_config.NumberColumn(format="percent"),
                                "Actually hit": st.column_config.NumberColumn(format="percent")})
    st.caption("Since Nov 21 the chance shown on a pick is the earned chance: the books' chance plus only the part of the "
               "model's disagreement its record has earned.")
else:
    st.caption("No morning reviews yet.")

# ---------------------------------------------------------------- 4. analyst calls
st.markdown("### 4 · Analyst Desk calls")
st.caption(f"Since {datetime.fromisoformat(I.ANALYST_ERA):%b %-d} the Desk locks every covered sport's calls on a "
           "schedule, before each game, and can't change them afterward; the full record downloads as a CSV with a "
           "fingerprint on the Analyst Record page. The test: does the hit rate match the chance the model stated?")
if lc["n"]:
    st.markdown(f"**{lc['n']:,} graded** of {lc['locked']:,} locked: hit **{pct(lc['hit'])}** "
                f"(95% range {rng(lc['lo'], lc['hi'])}) against **{pct(lc['said'])}** stated.")
    st.dataframe(pd.DataFrame([{"Sport": r["sport"], "Graded": r["n"], "Hit": r["hit"], "Model said": r["said"],
                                "95% range": rng(r["lo"], r["hi"])} for r in lc["by_sport"]]),
                 hide_index=True, width="stretch",
                 column_config={"Hit": st.column_config.NumberColumn(format="percent"),
                                "Model said": st.column_config.NumberColumn(format="percent")})
else:
    st.caption(f"{lc['locked']:,} locked, none graded yet — the first are graded the morning after their games.")

# ---------------------------------------------------------------- 5. real money
st.markdown("### 5 · Real money (labeled: the noisiest measure)")
st.caption("The owner's own bets at small, flat stakes while the record is proven. Over a short window this mostly "
           "reflects luck — shown for completeness, not as the evidence.")
if rm["settled"]:
    st.markdown(f"Since {_era:%b %-d}: **{rm['settled']} settled bets**, ROI **{pct((rm['roi'] or 0) / 100, True)}**. "
                f"Singles: {rm['singles']}, hit {pct(rm['singles_hit'])} (95% range {rng(rm['lo'], rm['hi'])}).")
else:
    st.caption(f"No real-money bets settled since {_era:%b %-d}.")

# ---------------------------------------------------------------- earlier builds
with st.expander(f"🗂️ Earlier builds (October – {(_era - timedelta(days=1)):%b %-d}) — kept, not counted above"):
    st.caption("The platform's record before the current rules. Kept in full so anyone can see how the model got here; "
               "not mixed into the numbers above, because the rules that chose these picks have since changed.")
    olc = I.locked_calls(old_calls)
    if olc["n"]:
        st.markdown(f"**Analyst Desk, {olc['first']} → {olc['last']}:** {olc['n']:,} graded of {olc['locked']:,} "
                    f"locked, hit **{pct(olc['hit'])}** (95% range {rng(olc['lo'], olc['hi'])}) against "
                    f"**{pct(olc['said'])}** stated. Locked only on days the Desk was opened (24 of 43 days), so it isn't "
                    "a complete daily record. Until Nov 6 it also held an older fallback model whose chances ran high "
                    "(NBA: 51% hit vs 61% stated over 976).")
    tags = I.use_tags(reports)
    if tags:
        st.markdown("**Recommendations by tag, last 30 days** (the board's reads, not only the picks shown):")
        st.dataframe(pd.DataFrame([{"Sport": t["sport"], "Use": t["use"], "Graded": t["n"], "Hit": t["hit"],
                                    "Model said": t["said"], "95% range": rng(t["lo"], t["hi"])}
                                   for t in tags if not PE.is_pass(t["use"])]),
                     hide_index=True, width="stretch",
                     column_config={"Hit": st.column_config.NumberColumn(format="percent"),
                                    "Model said": st.column_config.NumberColumn(format="percent")})
    clv = I.closing_line(bets)
    if clv["n"]:
        st.markdown(f"**Bet Log closing line since {clv['since']}:** {clv['n']} bets with a closing price; of "
                    f"{clv['moved']} that moved, beat the close **{pct(clv['beat'])}** (95% range "
                    f"{rng(clv['lo'], clv['hi'])}), average {clv['avg']:+.2f}%.")
    _old = I.closing_line(bets, since=None)
    st.caption(f"All-time Bet Log closing line ({_old['n']} bets): beat the close {pct(_old['beat'])} of moved prices — "
               "mostly summer MLB bets whose entry and close were taken at different lines, so not like for like; "
               f"{_old['dropped']} pairs priced beyond ±{I.MAX_ODDS} are left out.")
    arm = I.real_money(bets)
    if arm["settled"]:
        st.caption(f"All-time real money, {arm['first']} → {arm['last']}: {arm['settled']} settled bets, ROI "
                   f"{pct((arm['roi'] or 0) / 100, True)}.")

st.markdown("---")
st.caption("Methodology: hit-rate ranges are 95% Wilson intervals. Voids (player didn't play) and pushes are excluded. "
           "Parlays count once. 'Model said' is the chance the model stated before the game. Sources: the picks-as-shown "
           "ledger, the Analyst Record ledger, the Postgame Review morning reports, and the Bet Log.")
