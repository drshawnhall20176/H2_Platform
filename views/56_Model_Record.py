"""
Model Record — the proof page (Nov 16): how the model's own picks have graded over the last 30 days.

Only the model's record: nothing here comes from anyone's Bet Log, so it is safe for the public and commercial builds.
Numbers come from model_record.py (each sport's latest morning review and the Game Lab records). Read-only: it writes
nothing and spends no Odds API credits.
"""
import pandas as pd
import streamlit as st

import components as C
import model_record as MR
import sports

C.base_css()
C.page_header("📊", "Model Record",
              "How the model's picks have actually graded over the last 30 days, by sport and pick type. Every row "
              "shows how many picks it rests on and the 90% range around its hit rate.")

live = [s.key for s in sports.enabled_sports() if sports.in_season(s.key)]

# ---------- the report card (Nov 20): 💰 and 🔒 graded at the price they showed ----------
import props_engine as PE
import report_card as RC


@st.cache_data(ttl=900, show_spinner=False)
def _card(keys, day):
    return RC.card(list(keys), today=day)


C.section_header("🧾", "Report card: the picks we flag, at the prices we showed")
_rc = _card(tuple(k for k in live if sports.get(k).has_projections), PE._et_today())
if _rc:
    st.dataframe(pd.DataFrame(RC.table(_rc)), hide_index=True, width="stretch",
                 column_config={"Needed": st.column_config.TextColumn(help="The hit rate those prices needed to break "
                                                                           "even"),
                                "Beat the close": st.column_config.TextColumn(
                                    help="How often the line or price moved toward the pick before the game, among "
                                         "the picks whose number moved. The closing number is the sharpest there "
                                         "is: beating it more often than not is the earliest sign of a real edge.")})
    st.caption("Last 30 days. Every 💰 and 🔒 pick the site showed counts, at the price it showed — not only the ones "
               "anyone bet. Hit rate alone isn't profit: compare it with Needed, and read Return per $1. Picks are "
               "graded under the rule they were shown with (💰's rule and 🔒's price check changed on Nov 20).")
else:
    st.info("No graded 💰 or 🔒 picks in the last 30 days yet.")

# Nov 21 (owner: build and proven edge to A+): every rule has a version; each version keeps its own record from the day
# it started (rules.py), graded on the picks as shown (pick_ledger.py)
import rules as _RU
import pick_ledger as _PLr


@st.cache_data(ttl=900, show_spinner=False)
def _rule_recs(end):
    return _PLr.rule_records(end)


with st.expander("📐 The rules in force, and each one's record since it began", expanded=False):
    st.dataframe(pd.DataFrame(_RU.table()), hide_index=True, width="stretch",
                 column_config={"What it is": st.column_config.TextColumn(width="large")})
    from datetime import date as _date, timedelta as _td
    _yest = (_date.fromisoformat(PE._et_today()) - _td(days=1)).isoformat()
    _rr = _rule_recs(_yest)
    if _rr:
        _names = {"strong": "⭐ Strongest picks", "money": "💰 props", "games": "💰 game lines"}
        st.dataframe(pd.DataFrame([{
            "Picks": _names[r["kind"]] + ("" if r["sport"] == "ALL" else f" · {r['sport']}"),
            "Rule": f"v{r['v']} since {r['since']}", "Record": f"{r['hits']}–{r['misses']}",
            "Hit rate": f"{r['hit_rate']:.0%}", "Needed": f"{r['needed']:.0%}" if r.get("needed") else "—",
            "Return per $1": f"{r['roi']:+.1%}" if r.get("roi") is not None else "—",
            "Beat the close": (f"{r['beat_rate']:.0%} of {r['clv_moved']}" if r.get("beat_rate") is not None else "—"),
            "Avg CLV": f"{r['clv_avg']:+.1f}%" if r.get("clv_avg") is not None else "—", "Slates": r["slates"]}
            for r in _rr]), hide_index=True, width="stretch")
    else:
        st.caption("The first slate graded under the current rules is Nov 21 — its record appears the morning after.")
    st.caption("A rule's parameters are locked to its version: changing one starts a new version and a fresh record, "
               "so no record is ever tuned after the fact.")
    try:                                                        # Nov 21: markets switched off by their record
        import shutoff as _SO
        _so = _SO.table()
    except Exception:                                           # noqa: BLE001
        _so = []
    st.markdown("**Automatic shut-off** — re-scored every morning over the last 60 days")
    if _so:
        st.dataframe(pd.DataFrame(_so), hide_index=True, width="stretch")
    else:
        st.caption("No market is switched off or on watch.")
    st.caption(f"⛔ Off: {150}+ graded picks losing even at the top of their 90% range, or the market moving against "
               "them 55%+ of the time — the market keeps its picks on its pages but loses its 💰 / 🔒 flag and its "
               "place on the strongest list until its record recovers. 👀 Watch: 75+ picks losing more than 5% per $1.")
try:                                                            # the 💰 live test, while it runs
    import money_scoreboard as MSB
    if PE.MONEY_TEST["from"] <= PE._et_today():
        _mb = MSB.scoreboard()
        if _mb["total"]["n"]:
            t = _mb["total"]
            st.markdown(f"**💰 Live test since {PE.MONEY_TEST['from']}**: {t['hits']}–{t['misses']} "
                        f"({t['hit_rate']:.0%}, needed {t['needed']:.0%}), {t['units']:+.2f} units at 1 unit a pick.")
except Exception:                                               # noqa: BLE001
    pass

props = MR.props_table([k for k in live if sports.get(k).has_projections])
lines = MR.lines_table([k for k in live if k in MR.LINE_LEAGUES])

COLS = {"Hit rate": st.column_config.NumberColumn(format="percent"),
        "90% range (±)": st.column_config.NumberColumn(format="percent")}

C.section_header("🎯", "Player props")
if props:
    st.dataframe(pd.DataFrame(props), hide_index=True, width="stretch", column_config=COLS)
else:
    st.info("No graded prop picks in the last 30 days yet.")

C.section_header("🏟️", "Game lines")
if lines:
    st.dataframe(pd.DataFrame(lines), hide_index=True, width="stretch", column_config=COLS)
else:
    st.info("No graded game-line leans in the last 30 days yet.")

st.caption("How to read this: a hit rate is before the price. Above 50% is not by itself a profit; a standard −110 "
           f"line needs {MR.BREAK_EVEN_110:.1%}. \"Small sample\" means fewer than 20 graded picks, too few to judge. "
           "Soccer, International Hoops and Tennis are tracking only and are not counted here.")
