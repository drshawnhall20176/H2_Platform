"""
Today — the customer's front page (Nov 16): the day's picks across every in-season sport, each with its pick type's
own 30-day record. Commercial layout only (the owner's front page is Home).

Reads only what the platform already saved (customer_today.py): no Odds API credits, nothing written, nothing from
anyone's Bet Log.
"""
from datetime import datetime, timedelta

import pandas as pd
import pytz
import streamlit as st

import components as C
import customer_today as CT
import sports
import todays_best as TB

C.base_css()
_now = datetime.now(pytz.timezone("US/Eastern"))
_today = _now.date()
# Nov 25 (owner): a date selector -- back to see how a day's picks did, forward to what's posted early
PAST_DAYS, AHEAD_DAYS = 30, 7
_lo, _hi = _today - timedelta(days=PAST_DAYS), _today + timedelta(days=AHEAD_DAYS)
st.session_state.setdefault("today_day", _today)
if not (_lo <= st.session_state["today_day"] <= _hi):
    st.session_state["today_day"] = _today


def _shift(n):
    d = st.session_state.get("today_day", _today) + timedelta(days=n)
    st.session_state["today_day"] = min(max(d, _lo), _hi)


def _to_today():
    st.session_state["today_day"] = _today


_sel = st.session_state["today_day"]
_day = _sel.strftime("%Y-%m-%d")
_past = _sel < _today
_when = "Today" if _sel == _today else ("Yesterday" if (_today - _sel).days == 1 else
                                        "Tomorrow" if (_sel - _today).days == 1 else "")
C.hero_banner("🏠", f"{_when + ' · ' if _when else ''}{_sel:%A, %B %-d}",
              "The model's picks for the day across every sport. Each pick shows how that kind of pick has actually "
              "done over the last 30 days." + (" Past days show the picks as they were posted." if _past else ""))
with st.container(horizontal=True, vertical_alignment="center"):     # Nov 25: one row, even on a narrow screen
    st.button("◀", key="today_prev", on_click=_shift, args=(-1,), disabled=_sel <= _lo, help="Previous day")
    st.date_input("Date", key="today_day", min_value=_lo, max_value=_hi, format="MM/DD/YYYY",
                  label_visibility="collapsed", width=150)
    st.button("▶", key="today_next", on_click=_shift, args=(1,), disabled=_sel >= _hi, help="Next day")
    st.button("Today", key="today_back", on_click=_to_today, disabled=_sel == _today)

live = [s for s in sports.enabled_sports() if sports.in_season(s.key)]
props_sports = [s.key for s in live if s.key in CT.PROPS_SPORTS]


@st.cache_data(ttl=600, show_spinner=False, max_entries=8)
def _load(day, keys, past=False):
    best = TB.collect(day, list(keys), past=past)
    try:
        winners = TB.winner_rows(day, past=past)
    except Exception:                                           # noqa: BLE001
        winners = []
    return best.get("rows") or [], winners


@st.cache_data(ttl=3600, show_spinner=False, max_entries=128)
def _has_games(key, day):
    return CT.has_games(key, day)


@st.cache_data(ttl=600, show_spinner=False, max_entries=4)
def _search_rows(day, keys):
    """Nov 25: every playable pick saved for the day (the player search), not just the top picks."""
    out = []
    for k in keys:
        out += TB.load_all_props(k, day)
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def _tag_recs(sp):
    import pick_records as PR
    return PR.tag_records(sp)


@st.cache_data(ttl=1800, show_spinner=False)
def _lean_recs(lg):
    import pick_records as PR
    return PR.lean_records(lg)


rows, winners = _load(_day, tuple(props_sports), _past)

# Nov 25 (owner): one sport bar at the top -- "All sports" by default, one sport at a time (it also sets the sidebar's
# sport, so the old "Explore a sport" buttons at the bottom are gone), and several at once only when switched on.
ALL = "ALL"
_bar = [sp.key for sp in sports.selectable_sports(False)]
for _sp in live:                                                # anything in season the selector doesn't list
    if _sp.key not in _bar:
        _bar.append(_sp.key)
# Nov 25 (owner): only sports with games scheduled on the chosen day -- a pick or game on the boards counts, else the
# sport's own schedule is asked (cached an hour)
_with = {r.get("sport") for r in list(rows) + list(winners) if r.get("sport")}
_bar = [k for k in _bar if k in _with or _has_games(k, _day) is not False]
if st.session_state.get("today_one") not in (None, ALL) and st.session_state.get("today_one") not in _bar:
    st.session_state["today_one"] = ALL                         # the sport has no games that day
if st.session_state.get("today_sports"):
    st.session_state["today_sports"] = [k for k in st.session_state["today_sports"] if k in _bar]


def _label(k):
    if k == ALL:
        return "🌐 All sports"
    sp = sports.get(k)
    return f"{sp.icon} {k}" + (" · beta" if k in sports.LAB_SPORTS else "")


def _one_changed():
    k = st.session_state.get("today_one")
    if k and k != ALL:
        st.session_state["sport"] = k                           # the sidebar follows the sport picked here


def _multi_changed():
    now = list(st.session_state.get("today_sports") or [])
    new = [k for k in now if k not in st.session_state.get("_today_prev", [])]
    if new:
        st.session_state["sport"] = new[-1]
    st.session_state["_today_prev"] = now


def _mode_changed():
    if st.session_state.get("today_multi"):                     # carry the one sport into the multi bar
        one = st.session_state.get("today_one")
        st.session_state["today_sports"] = [one] if one and one != ALL else []
        st.session_state["_today_prev"] = list(st.session_state["today_sports"])
    else:
        sel = list(st.session_state.get("today_sports") or [])
        st.session_state["today_one"] = sel[-1] if len(sel) == 1 else ALL


multi = st.session_state.get("today_multi", False)
if multi:
    picked = st.pills("Sports", _bar, selection_mode="multi", key="today_sports", format_func=_label,
                      on_change=_multi_changed, label_visibility="collapsed") or None
else:
    st.session_state.setdefault("today_one", ALL)
    _one = st.pills("Sports", [ALL] + _bar, selection_mode="single", key="today_one",
                    format_func=_label, on_change=_one_changed, label_visibility="collapsed")
    picked = None if (not _one or _one == ALL) else [_one]
f1, f2 = st.columns(2)
f1.toggle("Show several sports at once", key="today_multi", on_change=_mode_changed,
          help="Off: one sport at a time (or All sports), and the sidebar follows it. On: pick any mix of sports.")
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

# Nov 25 (owner: "the ability to click a card and have it jump to a game or prop"): a Cards view -- every pick and game
# opens its player card or game card (today_visual.py). Commercial layout only (this page already is); the tables are
# one click away, and if the cards ever fail the page falls back to the tables.
try:
    import nav_layout as _NL
    _commercial = _NL.is_commercial(st.secrets.get("AUDIENCE", "owner"), st.session_state.get(_NL.PREVIEW_KEY))
except Exception:                                               # noqa: BLE001
    _commercial = False
_view = "Table"
if _commercial:
    _view = st.segmented_control("View", ["Cards", "Table"], default="Cards", key="today_view",
                                 help="Cards: tap Open on any pick or game for its player card or game card. "
                                      "Table: every pick in one list.") or "Cards"
_cards_ok = False
if _view == "Cards":
    try:
        import today_visual as _TV
        try:
            _all = _search_rows(_day, tuple(props_sports))
        except Exception:                                       # noqa: BLE001
            _all = []
        _TV.render([sports.get(k) for k in _bar if (not picked or k in picked)], rows, winners, _day,
                   records_for=_tag_recs,
                   search_rows=_all)
        _cards_ok = True
    except Exception:                                           # noqa: BLE001 -- the tables below are the fallback
        st.caption("The card view couldn't load just now, so here are the tables.")

PCT = {"Chance": st.column_config.NumberColumn(format="percent")}
if not _cards_ok:
    C.section_header("🎯", "Player picks")
    if props:
        st.dataframe(pd.DataFrame(props), hide_index=True, width="stretch", column_config=PCT)
    else:
        st.info("No player picks yet today. Boards are built through the day as the books post their lines."
                + ("" if include_new else " Switch on the toggle above to include pick types that are too new to "
                   "judge."))

    C.section_header("🏟️", "Game lines")
    if lines:
        st.dataframe(pd.DataFrame(lines), hide_index=True, width="stretch", column_config=PCT)
    else:
        st.info("No playable game lines today. A game line is listed only when a tested rule supports it or leans of "
                "its kind have won 55% or more.")

st.caption("Every game, every lean and the full board are under Games and All picks in the sidebar. "
           "How these pick types have graded is under Track record.")

st.caption("Beta sports are tracking only: their record is not proven yet, and they are not counted in the picks above.")
st.caption(CT.DISCLAIMER)
