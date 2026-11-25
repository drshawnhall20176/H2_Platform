"""
Alt Lines — every alternate rung's last-10 hit rate next to its price's break-even (Nov 25, PropSeason scrub item 5).

alt_hits.py does the work: the alternate prices the long-shot scan archived before tip-off, against tonight's board
rows (each player's last 10 games). History, not a pick.
"""
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

import alt_hits as AH
import components as C
import sports
import todays_best as TB

_active = sports.active()
C.base_css()
C.page_header("📐", f"Alt-line hit rates · {_active.key}",
              "Each alternate rung's last-10 hit rate beside the break-even of its real price. A hit rate means "
              "nothing without the price: a rung at -900 needs 90% just to break even.")
if not sports.require_sport(["NBA", "NFL", "NHL", "NCAAF"], "Alt-line hit rates"):
    st.stop()
SPORT = _active.key
eastern = pytz.timezone("US/Eastern")
day = st.date_input("Date", datetime.now(eastern).date(), key="ah_day", format="MM/DD/YYYY").strftime("%Y-%m-%d")


@st.cache_data(ttl=900, show_spinner="Reading tonight's alternate prices…", max_entries=8)
def _load(sport, d):
    rows = TB.load_all_props(sport, d)
    return AH.for_day(sport, d, rows)


try:
    rs = _load(SPORT, day)
except Exception as exc:                                        # noqa: BLE001
    st.warning(f"The alternate prices couldn't be read just now ({type(exc).__name__}). Try again shortly.")
    st.stop()
if not rs:
    st.info("No alternate prices saved for this date yet. The long-shot scan saves them a few times a day once the "
            "books post alternate lines.")
    st.stop()

c1, c2, c3 = st.columns(3)
games = sorted({r["game"] for r in rs if r["game"]})
g = c1.selectbox("Game", ["All games"] + games, key="ah_game")
min_rate = c2.slider("Last-10 hit rate ≥", 0, 100, 70, 10, key="ah_rate", format="%d%%")
only = c3.toggle("Only history above break-even", value=False, key="ah_above")
show = [r for r in rs if (g == "All games" or r["game"] == g) and r["rate"] >= min_rate / 100
        and (not only or r["margin"] >= AH.EDGE)]
st.caption(f"{len(show)} of {len(rs)} rungs.")
if show:
    import card_links as CL                                     # Nov 25: a row opens the player card
    CL.table(pd.DataFrame(AH.table(show, parse_time=C._kick_dt)), key=f"ah_table_{SPORT}",
             items=AH.ordered(show, parse_time=C._kick_dt), open_fn=CL.open_player_named(SPORT),
             hide_index=True, width="stretch", caption="Tap a row to open the player's card — every rung is on it.",
             column_config={"Hit rate": st.column_config.NumberColumn(format="percent"),
                            "Break-even": st.column_config.NumberColumn(format="percent")})
st.caption(AH.CAPTION)
