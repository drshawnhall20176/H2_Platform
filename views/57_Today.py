"""
Today — the customer's front page (Nov 16): the day's picks across every in-season sport, each with its pick type's
own 30-day record. Commercial layout only (the owner's front page is Home).

Reads only what the platform already saved (customer_today.py): no Odds API credits, nothing written, nothing from
anyone's Bet Log.
"""
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

import components as C
import customer_today as CT
import sports
import todays_best as TB

C.base_css()
_now = datetime.now(pytz.timezone("US/Eastern"))
_day = _now.strftime("%Y-%m-%d")
C.hero_banner("🏠", f"Today · {_now:%A, %B %-d}",
              "The model's picks for today across every sport in season. Each pick shows how that kind of pick has "
              "actually done over the last 30 days.")

live = [s for s in sports.enabled_sports() if sports.in_season(s.key)]
props_sports = [s.key for s in live if s.key in CT.PROPS_SPORTS]


@st.cache_data(ttl=600, show_spinner=False)
def _load(day, keys):
    best = TB.collect(day, list(keys))
    try:
        winners = TB.winner_rows(day)
    except Exception:                                           # noqa: BLE001
        winners = []
    return best.get("rows") or [], winners


@st.cache_data(ttl=1800, show_spinner=False)
def _tag_recs(sp):
    import pick_records as PR
    return PR.tag_records(sp)


@st.cache_data(ttl=1800, show_spinner=False)
def _lean_recs(lg):
    import pick_records as PR
    return PR.lean_records(lg)


rows, winners = _load(_day, tuple(props_sports))
f1, f2 = st.columns([3, 2])
picked = f1.pills("Sports", [s.key for s in live], selection_mode="multi", key="today_sports",
                  format_func=lambda k: f"{sports.get(k).icon} {k}", label_visibility="collapsed")
include_new = f2.toggle("Include pick types too new to judge", value=False, key="today_new",
                        help="Pick types with fewer than 20 graded picks in the last 30 days. Losing pick types are "
                             "never shown.")
props = CT.prop_picks(rows, include_new=include_new, sports=picked or None, records_for=_tag_recs, parse_time=C._kick_dt)
lines = CT.line_picks(winners, sports=picked or None, records_for=_lean_recs, parse_time=C._kick_dt)
s = CT.summary(props, lines)
C.kpi_row([{"icon": "🎯", "value": str(s["picks"]), "label": "Player picks today"},
           {"icon": "✅", "value": str(s["winning"]), "label": "From pick types with a winning record"},
           {"icon": "🏟️", "value": str(s["lines"]), "label": "Playable game lines"},
           {"icon": "📅", "value": str(len(s["sports"])), "label": "Sports with a pick"}])

PCT = {"Chance": st.column_config.NumberColumn(format="percent")}
C.section_header("🎯", "Player picks")
if props:
    st.dataframe(pd.DataFrame(props), hide_index=True, width="stretch", column_config=PCT)
else:
    st.info("No player picks yet today. Boards are built through the day as the books post their lines."
            + ("" if include_new else " Switch on the toggle above to include pick types that are too new to judge."))

C.section_header("🏟️", "Game lines")
if lines:
    st.dataframe(pd.DataFrame(lines), hide_index=True, width="stretch", column_config=PCT)
else:
    st.info("No playable game lines today. A game line is listed only when a tested rule supports it or leans of "
            "its kind have won 55% or more.")

st.caption("Every game, every lean and the full board are under Games and All picks in the sidebar. "
           "How these pick types have graded is under Track record.")

st.divider()
C.section_header("🧭", "Explore a sport", "Pick a sport to load its games, players and live pages in the sidebar.")
current = st.session_state.get("sport", sports.DEFAULT_SPORT)
with st.container(horizontal=True, horizontal_alignment="left"):
    for sp in sports.selectable_sports(False):
        beta = sp.key in sports.LAB_SPORTS
        if st.button(f"{sp.icon} {sp.label}" + (" · beta" if beta else ""), key=f"today_sport_{sp.key}",
                     type="primary" if current == sp.key else "secondary", width="content"):
            st.session_state["sport"] = sp.key
            st.rerun()
st.caption("Beta sports are tracking only: their record is not proven yet, and they are not counted in the picks above.")
st.caption(CT.DISCLAIMER)
