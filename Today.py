"""
Today.py -- the entry page (Nov 17, owner's design): the day across every sport before any one sport is chosen.

Owner: "have the entry page to the portfolio be the 'Today at a glance' with the top four items for sports that are
active that day. Above the four boxes would be a link that would then take the user to a specific sport where they
would see today's best etc." Order: one button per in-season sport (with today's count of playable picks) -> the day
in four numbers -> the four strongest picks across every sport (strength alone, one per player; 📈 when the market is
moving our way) -> the owner's morning brief and afternoon picks. A sport button opens Home on that sport. Everything
here is read from boards and records already saved: no Odds API credits.
"""
import streamlit as st
from datetime import datetime as _dt

import pytz as _pytz

import components as C
import sports

_ET = _pytz.timezone("US/Eastern")
C.base_css()
C.hero_banner("📈", "H2 Sports — The Sports Trading Desk",
              "Trade sports, don't bet sports. Every prop priced, every position sized with discipline, every result "
              "graded against the closing line.")
try:
    _owner = st.secrets.get("AUDIENCE", "owner") == "owner"
except Exception:                                               # noqa: BLE001
    _owner = True

import customer_today as _CT
import todays_best as _TB0


@st.cache_data(ttl=300, show_spinner=False)
def _glance_data(day, keys):
    best = _TB0.collect(day, list(keys))
    try:
        winners = _TB0.winner_rows(day)
    except Exception:                                           # noqa: BLE001
        winners = []
    return best.get("rows") or [], winners


@st.cache_data(ttl=1800, show_spinner=False)
def _glance_tags(sp):
    import pick_records as _PR0
    return _PR0.tag_records(sp)


@st.cache_data(ttl=1800, show_spinner=False)
def _glance_leans(lg):
    import pick_records as _PR0
    return _PR0.lean_records(lg)


@st.cache_data(ttl=600, show_spinner=False)
def _line_index(sp, day):
    import line_history as _LH
    return _LH.sport_index(sp, since=day)


_g_day = _dt.now(_ET).strftime("%Y-%m-%d")
live = sports.selectable_sports(_owner)
_g_live = [s.key for s in sports.enabled_sports() if sports.in_season(s.key)]
try:
    _g_rows, _g_win = _glance_data(_g_day, tuple(k for k in _g_live if k in _CT.PROPS_SPORTS))
    _g_rows = [dict(r) for r in _g_rows]
    for _sp in _TB0.MOVE_SPORTS:
        try:
            _TB0.market_moves(_sp, _g_day, _g_rows, index=_line_index(_sp, _g_day))
        except Exception:                                       # noqa: BLE001
            pass
    _g_props = _CT.prop_picks(_g_rows, records_for=_glance_tags, parse_time=C._kick_dt)
    _g_lines = _CT.line_picks(_g_win, records_for=_glance_leans, parse_time=C._kick_dt)
except Exception:                                               # noqa: BLE001 -- the page always renders
    _g_rows, _g_props, _g_lines = [], [], []
_g_sum = _CT.summary(_g_props, _g_lines)

# ---------- pick a sport (above the boxes) ----------
_count = {}
for r in _g_props + _g_lines:
    _sp = r.get("Sport")
    if _sp:
        _count[_sp] = _count.get(_sp, 0) + 1
C.section_header("🏟", f"Today · {_dt.now(_ET):%A, %B %-d}")
st.caption("Choose a sport for its full desk: Today's best, game lines, long shots and logging.")
with st.container(horizontal=True, horizontal_alignment="left"):
    for s in sorted(live, key=lambda s: -_count.get(s.key, 0)):
        n = _count.get(s.key, 0)
        if st.button(f"{s.icon} {s.label.split(' — ')[0]} · {n}", key=f"today_sport_{s.key}", type="primary" if n else "secondary",
                     width="content", help=f"{n} playable pick{'s' if n != 1 else ''} today"):
            st.session_state["sport"] = s.key
            st.switch_page("Home.py")

# ---------- the day in four numbers ----------
C.kpi_row([{"icon": "🎯", "value": str(_g_sum["picks"]), "label": "Player picks from winning pick types"},
           {"icon": "🏟️", "value": str(_g_sum["lines"]), "label": "Playable game lines"},
           {"icon": "📅", "value": str(len(_g_sum["sports"])), "label": "Sports with a pick"},
           {"icon": "🗂️", "value": str(len(_g_live)), "label": "Sports in season"}])

# ---------- the four strongest picks ----------
_g_cards = _CT.top_cards(_g_rows, records_for=_glance_tags)
if _g_cards:
    for _col, _c in zip(st.columns(len(_g_cards)), _g_cards):
        with _col.container(border=True):
            st.markdown(f"**{'🔒 ' if _c['lock'] else ''}{_c['pick']}**")
            st.metric("Chance", "—" if _c["chance"] is None else f"{_c['chance']:.0%}", label_visibility="collapsed")
            st.caption(f"{_c['sport']} · {_c['price']}  \n{_c['game']}" + (f" · {_c['time']}" if _c["time"] else ""))
            st.caption(" · ".join(x for x in (("✅ " + _c["record"]) if _c["record"] else "",
                                               _c.get("move") or "") if x))
    st.caption("The strongest player picks across every sport: pick types with a winning 30-day record only, one per "
               "player. 📈 = the market has moved toward this side since the first price today. Pick a sport above "
               "for the full tables and logging.")
else:
    st.caption("No player picks from winning pick types yet today. Boards are built through the day as the books post "
               "their lines.")

# ---------- the owner's brief ----------
if _owner:
    st.divider()
    try:
        import model_store as _MS
        import pandas as _pd
        _bday = _dt.now(_ET).strftime("%Y-%m-%d")
        for _kind, _title in (("picks", "🎯 This afternoon's picks"), ("morning", "☀️ Morning brief")):
            _b = _MS.get_setting(f"brief:{_bday}:{_kind}")
            if isinstance(_b, dict) and _b.get("text"):
                with st.expander(_title, expanded=_kind == "picks"):
                    _lines = _b["text"].split("\n")[1:]          # the first line is the note's own title
                    if _b.get("table"):
                        _head = [l for l in _lines if l.strip() and not l.startswith("•")]
                        st.markdown(C.money_md(_head[0]))
                        st.dataframe(_pd.DataFrame(_b["table"]), hide_index=True, width="stretch")
                        for _l in _head[1:]:
                            st.caption(C.money_md(_l))
                    else:
                        st.markdown(C.money_md("  \n".join(_lines)))
    except Exception:                                           # noqa: BLE001 -- the brief is a bonus
        pass
