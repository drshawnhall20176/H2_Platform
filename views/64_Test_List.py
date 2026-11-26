"""
64_Test_List.py -- the owner's test list (focus_list.py), in the Owner Office (Nov 26).

Every 🃏 Bet, 💰 Money pick and 🧪 close-gap pick of the day across every sport, one filterable table, earliest start
first. Owner only (an Office page). Tap a row for the player or game card.
"""
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

import components as C
import focus_list as FL
import todays_best as TB

ET = pytz.timezone("US/Eastern")
C.base_css()
C.page_header("🎯", "Test list",
              "Every 🃏 Bet, 💰 Money pick and 🧪 close-gap pick on today's boards, every sport, in one list — the "
              "picks you're testing, and nothing else. Follows the boards as the lines move.")

_now = datetime.now(ET)
c1, c2, c3 = st.columns([1, 2, 1])
day = c1.date_input("Date", _now.date(), key="tl_day", format="MM/DD/YYYY").strftime("%Y-%m-%d")
kinds = c2.pills("Show", list(FL.KINDS), selection_mode="multi", default=list(FL.DEFAULT_KINDS), key="tl_kinds",
                 help="🃏 Bet: a tested tag whose earned chance clears its price's break-even · 💰 Money pick: the live "
                      "money test · 🧪 Close gap: college basketball games where the model and the market are within "
                      "2 points — paper-track only until the rule earns a tag · 🧪 Other tracking: the prop rules being "
                      "tested forward (off by default).")
if c3.button("🔄 Refresh now", help="Re-read the boards (they also refresh on their own every 5 minutes)."):
    st.cache_data.clear()


@st.cache_data(ttl=300, show_spinner="Reading today's boards…", max_entries=8)
def _boards(d):
    import customer_today as CT
    past = d < datetime.now(ET).strftime("%Y-%m-%d")
    props = (TB.collect(d, list(CT.PROPS_SPORTS), past=past).get("rows") or [])
    try:
        winners = TB.winner_rows(d, past=past)
    except Exception:                                           # noqa: BLE001
        winners = []
    return props, winners, datetime.now(ET).strftime("%-I:%M %p")


try:
    props, winners, read_at = _boards(day)
except Exception as exc:                                        # noqa: BLE001
    st.warning(f"The boards couldn't be read just now ({type(exc).__name__}). Try Refresh in a minute.")
    st.stop()

every = FL.build(props, winners, kinds=FL.KINDS, parse_time=C._kick_dt)
sports_here = sorted({r["sport"] for r in every})
d1, d2 = st.columns([3, 1])
pick_sports = d1.multiselect("Sports", sports_here, placeholder="All sports", key="tl_sports")
hide_started = d2.toggle("Hide games that have started", value=day == _now.strftime("%Y-%m-%d"), key="tl_hide")
rows = FL.build(props, winners, kinds=kinds or FL.DEFAULT_KINDS, sports=pick_sports or None, parse_time=C._kick_dt)
if hide_started:
    def _gone(r):
        k = C._kick_dt(r.get("time"))
        try:
            return k is not None and k <= _now
        except TypeError:
            return False
    rows = [r for r in rows if not _gone(r)]

n = FL.counts(rows)
m1, m2, m3, m4 = st.columns(4)
m1.metric("💰 Money picks", n[FL.MONEY])
m2.metric("🃏 Bets", n[FL.BET])
m3.metric("🧪 Close gap (paper)", n[FL.GAP])
m4.metric("Boards read at", read_at)

try:                                                            # the close-gap rule's forward record, right here
    import candidate_rules as CR
    cg = CR.status_line("NCAAMB", day)
    if cg:
        st.caption(cg)
except Exception:                                               # noqa: BLE001
    pass

if not rows:
    st.info("Nothing on the list for these filters. That's an answer too: no tested pick qualifies right now. Boards "
            "rebuild every hour as the books post and move lines.")
    st.stop()

import card_links as CL                                         # a row opens its player or game card


def _open(r):
    if r["open_as"] == "game":
        CL.open_game(lambda x: r["sport"])(r["src"])
    else:
        CL.open_player(r["sport"])(r["src"])


CL.table(pd.DataFrame(FL.table(rows)), key=f"tl_table_{day}", items=rows, open_fn=_open, hide_index=True,
         width="stretch", caption="Tap a row for its card — the read, the recent games and the line history.",
         column_config={"Chance": st.column_config.NumberColumn(format="percent"),
                        "Needs": st.column_config.NumberColumn(format="percent", help="Break-even for the price"),
                        "Edge": st.column_config.NumberColumn(format="percent", help="Chance minus break-even")})
st.caption("**Chance** is the earned chance (how picks like it have actually done). **Needs** is what the price needs "
           "to break even. Close-gap picks have no chance of their own yet: they're a rule being tested forward, so "
           "track them on paper. Prices are the best the boards saw at their last read; check your book before you "
           "bet. Started games drop off the list.")
