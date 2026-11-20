"""
Today.py -- the entry page (Nov 17, owner's design): the day across every sport before any one sport is chosen.

Owner: "one sport per row with each sport showing the top 4 picks today from each if applicable ... NHL shows 10
games today so it would be a row by itself with the top 4 picks, then the next row would be the next active sport."
The day in four numbers, then one bordered row per sport playing today (sports with picks first, then by games):
its game and pick counts, an "Open desk" button (Home on that sport) and up to four cards -- prop picks from pick
types with a winning 30-day record (one per player), playable game lines, and college basketball spreads moving our
way (tested, todays_best.spread_move). The owner's brief sits at the top, under the date (Nov 19). No Odds API credits: everything is already saved.
"""
import streamlit as st
from datetime import datetime as _dt
from datetime import timedelta as _td

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


@st.cache_data(ttl=600, show_spinner="Loading today's boards…")
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


@st.cache_data(ttl=900, show_spinner=False)
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

# ---------- one row per sport (Nov 17, owner: "one sport per row with each sport showing the top 4 picks") ----------
import re as _re


def _lean_pct(rec: str) -> float:
    m = _re.search(r"\((\d+)%", rec or "")
    return int(m.group(1)) / 100 if m else 0.5


_games, _cards = {}, {}
for r in _g_win:
    _games[r.get("sport")] = _games.get(r.get("sport"), 0) + 1
_g_rowsorted = sorted([r for r in _g_rows if r.get("kind") == "Prop"],
                      key=lambda r: (0 if r.get("lock") else 1, -(r.get("chance") or 0)))
for r in _g_rowsorted:                                      # prop picks from winning pick types (top_cards' rule)
    _games.setdefault(r.get("sport"), 0)
for sp_key in {r.get("sport") for r in _g_rowsorted}:
    for c in _CT.top_cards([r for r in _g_rowsorted if r.get("sport") == sp_key], records_for=_glance_tags, n=4):
        _cards.setdefault(sp_key, []).append({**c, "score": (2 if c["lock"] else 1, c["chance"] or 0), "kind": "Prop"})
for r in _g_lines:                                          # playable game lines
    _cards.setdefault(r["Sport"], []).append({
        "sport": r["Sport"], "pick": r["Pick"], "chance": r.get("Chance"), "lock": False, "move": "",
        "price": r.get("Best price") or "—", "game": r.get("Game") or "", "time": r.get("Time") or "",
        "record": r.get("Record (30 days)") if r.get("Record (30 days)") not in (None, "—") else "",
        "basis": r.get("Basis"), "score": (1, r.get("Chance") or _lean_pct(r.get("Record (30 days)"))), "kind": "Line"})
_npicks = {}
for r in _g_props:
    _npicks[r["Sport"]] = _npicks.get(r["Sport"], 0) + 1
for r in _g_lines:
    _npicks[r["Sport"]] = _npicks.get(r["Sport"], 0) + 1
for r in _g_win:                                            # college basketball spreads moving our way (tested)
    if r.get("spread_move") == "📈 our way" and r.get("spread_move_why") and \
            not any(c.get("game") == r.get("game") for c in _cards.get(r.get("sport"), [])):
        _npicks[r["sport"]] = _npicks.get(r["sport"], 0) + 1
        _from, _to = r["spread_move_why"].split(" → ")
        _cards.setdefault(r["sport"], []).append({
            "sport": r["sport"], "pick": f"{_from.rsplit(' ', 1)[0]} {_to}", "chance": None, "lock": False,
            "move": "📈 spread moving our way", "price": "", "game": r.get("game") or "", "time": r.get("time") or "",
            "record": "tested: 55% covered at the moved number", "basis": f"opened {_from.rsplit(' ', 1)[1]}",
            "score": (1, 0.55), "kind": "Line"})
for k in _cards:
    _cards[k].sort(key=lambda c: c["score"], reverse=True)
# Nov 19 (owner, the middle ground): each sport's row always carries its strongest 💰 Money pick (biggest edge, game not
# started) as one of its four cards -- added in the 4th spot when the usual top four don't already include one
try:
    _now_et = _dt.now(_ET)
    for sp_key in {r.get("sport") for r in _g_rows if r.get("money")}:
        _have = _cards.get(sp_key, [])
        if any(c.get("money") for c in _have[:4]):
            continue
        _m = _CT.money_picks([r for r in _g_rows if r.get("sport") == sp_key], parse_time=C._kick_dt, now=_now_et, n=1)
        if _m:
            m = _m[0]
            _card = {**m, "money": True, "move": "", "basis": f"{m['edge']:+.0%} edge" if m.get("edge") is not None else "",
                     "record": "", "score": (1, m.get("chance") or 0), "kind": "Prop"}
            _cards[sp_key] = [c for c in _have if c.get("pick") != m["pick"]][:3] + [_card] + \
                [c for c in _have if c.get("pick") != m["pick"]][3:]
            _npicks[sp_key] = _npicks.get(sp_key, 0) + 1
except Exception:                                               # noqa: BLE001 -- the page always renders
    pass

_order = sorted([s for s in live if _games.get(s.key) or _cards.get(s.key)],
                key=lambda s: (-_npicks.get(s.key, 0), -_games.get(s.key, 0)))
_quiet = [s for s in live if s not in _order]

C.section_header("🏟", f"Today · {_dt.now(_ET):%A, %B %-d}")
# Nov 17: the books' promotions running today pop up here (promos.py; schedule-based, owner-added ones too)
try:
    import promos as _PROMO
    for _p in _PROMO.on_today(_dt.now(_ET).date(), [s.key for s in _order], banners_only=True):
        _b1, _b2 = st.columns([5, 1])
        _b1.info(f"**{_p['name']}** is on today at {_p['book']} ({', '.join(_p.get('sports') or [])}).", icon="🎁")
        _b2.page_link("views/59_Promotions.py", label="See it →")
except Exception:                                               # noqa: BLE001 -- a banner never breaks the page
    pass
# ---------- the owner's brief (Nov 19: moved to the top -- owner: "so it does not get overlooked") ----------
if _owner:
    try:
        import model_store as _MS
        import pandas as _pd
        _bday = _dt.now(_ET).strftime("%Y-%m-%d")
        _briefs = [(k, t, _MS.get_setting(f"brief:{_bday}:{k}")) for k, t in
                   (("picks", "🎯 This afternoon's picks"), ("morning", "☀️ Morning brief"))]
        _briefs = [(k, t, b) for k, t, b in _briefs if isinstance(b, dict) and b.get("text")]
        for _i, (_kind, _title, _b) in enumerate(_briefs):
            with st.expander(_title, expanded=_i == 0):         # the newest note open, the other one folded
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

# ---------- 💰 live test scoreboard (Nov 20, owner: "run that concept live this weekend to see how it does") ----------
@st.cache_data(ttl=600, show_spinner=False)
def _money_board(day):
    import money_scoreboard as _MSB
    return _MSB.scoreboard(today=day)


try:
    import money_scoreboard as _MSB
    import props_engine as _PEM
    _mday = _dt.now(_ET).strftime("%Y-%m-%d")
    if _PEM.MONEY_TEST["from"] <= _mday <= (_dt.fromisoformat(_PEM.MONEY_TEST["to"]) + _td(days=2)).strftime("%Y-%m-%d"):
        _mb = _money_board(_mday)
        _live = {}
        for _r in _g_rows:
            if _r.get("money") and _r.get("kind") == "Prop":
                _live[_r.get("sport")] = _live.get(_r.get("sport"), 0) + 1
        _t = _mb["total"]
        _f, _to = _dt.fromisoformat(_mb["from"]), _dt.fromisoformat(_mb["to"])
        with st.container(border=True):
            C.section_header("💰", f"Money picks · live test, {_f:%a %b %-d} – {_to:%a %b %-d}")
            if _t["n"]:
                C.kpi_row([
                    {"icon": "🧾", "value": f"{_t['hits']}–{_t['misses']}", "label": "💰 record so far"},
                    {"icon": "🎯", "value": f"{_t['hit_rate']:.0%}", "label": f"hit rate (needed {_t['needed']:.0%})",
                     "trend": "good" if _t["hit_rate"] >= _t["needed"] else "bad"},
                    {"icon": "💵", "value": f"{_t['units']:+.2f}u", "label": "units, $1 a pick",
                     "trend": "good" if _t["units"] >= 0 else "bad"},
                    {"icon": "📈", "value": f"{_t['roi']:+.1%}", "label": "return per $1"},
                ])
            else:
                st.caption("No 💰 picks graded yet — the first night's results land with tomorrow's morning review.")
            import pandas as _pdm
            _mdf = _pdm.DataFrame(_MSB.table(_mb, _live))
            _fmt = {"Hit rate": "{:.0%}", "Needed": "{:.0%}", "Units ($1 a pick)": "{:+.2f}", "Per $1": "{:+.1%}"}
            for _c, _f in _fmt.items():
                _mdf[_c] = [_f.format(v) if v is not None and v == v else "—" for v in _mdf[_c]]
            st.dataframe(_mdf, hide_index=True, width="stretch",
                         column_config={"Needed": st.column_config.TextColumn(help="The hit rate the prices needed "
                                                                                   "to break even"),
                                        "Today": st.column_config.NumberColumn(help="💰 picks on today's boards")})
            st.caption(_PEM.MONEY_HELP + " Every 💰 pick counts, at the price it showed — not only the ones bet.")
except Exception:                                               # noqa: BLE001 -- the scoreboard never breaks the page
    pass

C.kpi_row([{"icon": "🎯", "value": str(_g_sum["picks"]), "label": "Player picks from winning pick types"},
           {"icon": "🏟️", "value": str(_g_sum["lines"]), "label": "Playable game lines"},
           {"icon": "📅", "value": str(sum(1 for s in _order if _cards.get(s.key))), "label": "Sports with a pick"},
           {"icon": "🗓️", "value": str(len(_order)), "label": "Sports playing today"}])
st.caption("One row per sport playing today, busiest first: its strongest picks (pick types with a winning 30-day "
           "record, playable game lines, and college basketball spreads moving our way), and its best 💰 Money pick "
           "where the sport has them (live test this weekend: the model 3–20% better than the sportsbook price, a 40%+ "
           "chance, and a fair price — see the 💰 scoreboard above). Open a sport for its full desk: every table, filter "
           "and logging.")

for s in _order:
    cards = _cards.get(s.key, [])[:4]
    g, n = _games.get(s.key, 0), _npicks.get(s.key, 0)
    with st.container(border=True):
        h1, h2 = st.columns([4, 1])
        h1.markdown(f"#### {s.icon} {s.label.split(' — ')[0]}  \n<span style='opacity:.7'>"
                    + (f"{g} game{'s' if g != 1 else ''} today · " if g else "")
                    + f"{n} playable pick{'s' if n != 1 else ''}</span>", unsafe_allow_html=True)
        if h2.button("Open desk →", key=f"today_sport_{s.key}", type="primary" if cards else "secondary",
                     width="stretch"):
            st.session_state["sport"] = s.key
            st.switch_page("Home.py")
        if not cards:
            st.caption("Nothing playable yet: no pick type here has a winning record today, and no game line clears "
                       "the bar. Boards fill in as the books post lines; the desk has every lean.")
            continue
        for col, c in zip(st.columns(4), cards):
            with col.container(border=True):
                st.markdown(f"**{'💰 ' if c.get('money') else ''}{'🔒 ' if c['lock'] else ''}{c['pick']}**")
                st.metric("Chance", "—" if c["chance"] is None else f"{c['chance']:.0%}", label_visibility="collapsed")
                st.caption(" · ".join(x for x in (c.get("price") if c.get("price") not in ("—", "") else "",
                                                   c.get("basis") or "") if x)
                           + f"  \n{c['game']}" + (f" · {c['time']}" if c["time"] else ""))
                st.caption(" · ".join(x for x in (("✅ " + c["record"]) if c.get("record") else "",
                                                   c.get("move") or "") if x))

if _quiet:
    st.caption("Not playing today: " + ", ".join(f"{s.icon} {s.label.split(' — ')[0]}" for s in _quiet))
