import streamlit as st
import sports
import components as C
import schedule_board as SB
from datetime import datetime as _dt
import pytz as _pytz

_ET = _pytz.timezone("US/Eastern")

C.base_css()
C.hero_banner("📈", "H2 Sports — The Sports Trading Desk",
             "Trade sports, don't bet sports. Every prop priced, every position sized with "
             "discipline, every result graded against the closing line. This is a day-trading "
             "tool for real analysts — not a picks service, not a betting platform.")

# Sport selector -- primary location is here in the main content area, not the sidebar.
# Streamlit's st.navigation always injects page links at the top of the sidebar regardless
# of call order, pushing any sidebar widget below the full page list. Rendering it here
# ensures it's always visible and unobstructed, at the top of the main content on the
# landing page every user sees first.
st.divider()
try:
    _owner = st.secrets.get("AUDIENCE", "owner") == "owner"
except Exception:                                               # noqa: BLE001
    _owner = True
live = sports.selectable_sports(_owner)          # Nov 5: only sports in season, plus Tennis and Intl Hoops
keys = [s.key for s in live]
current = st.session_state.get("sport", sports.DEFAULT_SPORT)
if current not in keys:
    current = sports.default_selectable(_owner)

C.section_header("🏟", "Select Sport")
with st.container(horizontal=True, horizontal_alignment="left"):
    for s in live:
        if st.button(f"{s.icon} {s.label}", key=f"sport_btn_{s.key}",
                     type="primary" if current == s.key else "secondary", width="content"):
            st.session_state["sport"] = s.key
            st.rerun()

active = sports.get(current)
if active:
    st.caption(f"Currently viewing: **{active.icon} {active.label}** — select a page from the sidebar to begin.")
    if current == "UFC":
        st.info("🥊 UFC Fight Card is live — tonight's bouts with moneyline odds, "
               "method of victory lines, and fight duration props. "
               "Phase 2 will add finishing rate history and conviction scoring.")

st.divider()

# ---------- Today's best (Nov 6) ----------
# The day's top-tagged picks across every in-season sport and the labs, in one list. Props come from the last Best
# Bets board built for each sport today (no extra Odds API spend); game lines, international hoops and tennis from
# their capture jobs. Tags are the same ones each sport's own page shows. Owner build only.
if _owner:
    import pandas as _pd
    import props_engine as _PE
    import todays_best as _TB
    _today = _dt.now(_ET).strftime("%Y-%m-%d")
    _props_sports = [s.key for s in live if s.key in ("NBA", "NFL", "NHL", "NCAAF")]
    C.section_header("⭐", "Today's best")
    _best = _TB.collect(_today, _props_sports)
    _missing = [k for k, at in _best["props"].items() if not at]
    _c1, _c2, _c3 = st.columns([2, 2, 1])
    _here = active.label if active else "This sport"
    _scope = _c1.radio("Sports", [f"{_here} only", "All sports"], horizontal=True, key="home_best_scope",
                       label_visibility="collapsed")
    _show = _c2.radio("Show", ["🔒 Locks only", "All playable"], horizontal=True, key="home_best_show",
                      label_visibility="collapsed")
    if _c3.button("🔄 Refresh props", width="stretch",
                  help="Builds today's Best Bets board for each props sport (the same Odds API use as opening it)."):
        import best_bets_data as _BBD
        with st.spinner("Building today's boards…"):
            for _k in _props_sports:
                try:
                    _BBD.load_generic_best_bets_board(_k, _today, _BBD.O.DEFAULT_BOOK)
                except Exception:                               # noqa: BLE001
                    pass
        st.rerun()
    # Nov 6: follow the sport picked above (the panel showed every sport, so NBA showed tennis); "All sports" for the lot
    _rows = _best["rows"] if _scope == "All sports" else [r for r in _best["rows"] if r.get("sport") == current]
    _rows = [r for r in _rows if r.get("lock")] if _show.startswith("🔒") else _rows
    if _rows:
        _df = _pd.DataFrame([{"Sport": r["sport"], "Time": r.get("time") or "", "Pick": r["pick"],
                              "Use": ("🔒 " if r.get("lock") else "") + (r.get("use") or ""),
                              "Chance": r.get("chance"),
                              "Price": ("—" if r.get("price") is None else f"{float(r['price']):+.0f}"),
                              "Needs": ("" if r.get("need") is None else f"{float(r['need']):+.0f} or better"),
                              "Game": r.get("game"), "Where": r.get("page"),
                              "Tested": "no backtest" if r.get("untested") else ""} for r in _rows[:60]])
        if not _df["Needs"].any():
            _df = _df.drop(columns=["Needs"])
        if not _df["Tested"].any():
            _df = _df.drop(columns=["Tested"])
        if _scope != "All sports":
            _df = _df.drop(columns=["Sport"])
        st.dataframe(_df, hide_index=True, width="stretch",
                     column_config={"Chance": st.column_config.NumberColumn(format="percent")})
        if any(r.get("untested") for r in _rows):
            st.caption("**No backtest:** these tennis matches (events only ESPN lists, with no posted prices) are tagged "
                       "from the model's chance alone — nothing has tested that chance yet. On main-tour matches the "
                       "books beat this model, so those are always ⛔ Pass. Treat these as reads, and only at the "
                       "price shown under Needs or better.")
    else:
        _none = "locks" if _show.startswith("🔒") else "playable picks"
        st.caption(f"No {_none} for {_here} yet today." if _scope != "All sports" else f"No {_none} yet today.")
    _notes = []
    if _missing:
        _notes.append(f"Props not built yet today: {', '.join(_missing)} — open their Best Bets or press Refresh.")
    def _stamp(k, at):
        try:
            return f"{k} {_dt.fromisoformat(at).astimezone(_ET):%I:%M %p}".replace(" 0", " ")
        except (TypeError, ValueError):
            return None
    _stamps = [x for x in (_stamp(k, at) for k, at in _best["props"].items() if at) if x]
    if _stamps:
        _notes.append("Props as of " + ", ".join(_stamps) + ".")
    _notes.append("Prices move — confirm on the sport's own page before placing. Tennis and most international "
                  "leagues rarely show picks: their backtests haven't earned them yet.")
    st.caption(" ".join(_notes))

    # ---- Most likely winners (Nov 6): every game today, the side the model thinks wins, for every sport covered
    @st.cache_data(ttl=21600, show_spinner=False)
    def _winner_record():
        return _TB.winner_record()

    @st.cache_data(ttl=900, show_spinner=False)
    def _winners(day):
        return _TB.winner_rows(day)

    st.markdown("##### 🏆 Most likely winners")
    _wall = _winners(_today)
    _w = _wall if _scope == "All sports" else [r for r in _wall if r["sport"] == current]
    if current in ("NFL", "UFC") and _scope != "All sports":
        st.caption("Not covered yet for this sport: there's no stored game model for NFL (the college spread model "
                   "showed no NFL edge), and UFC's chances come from the odds themselves. Choose All sports to see "
                   "the rest.")
    elif _w:
        _wdf = _pd.DataFrame([{"Sport": r["sport"], "Time": r["time"], "Game": r["game"], "Model's winner": r["winner"],
                               "Model": r["chance"], "Books": r["book"],
                               "Best price": ("—" if r.get("price") is None else f"{float(r['price']):+.0f}"
                                              + (f" {r['price_book']}" if r.get("price_book") else "")),
                               "Value at price": r["value"], "Use": r.get("use") or "",
                               "League": r["league"]} for r in _w[:60]])
        if _scope != "All sports":
            _wdf = _wdf.drop(columns=["Sport"])
        if not _wdf["Use"].any():
            _wdf = _wdf.drop(columns=["Use"])
        st.dataframe(_wdf, hide_index=True, width="stretch",
                     column_config={"Model": st.column_config.NumberColumn("Model's chance", format="percent"),
                                    "Books": st.column_config.NumberColumn("Books' chance", format="percent"),
                                    "Value at price": st.column_config.NumberColumn(format="percent")})
        _rec = _winner_record()
        _sports_here = sorted({r["sport"] for r in _w})
        _bits = []
        for _sp in _sports_here:
            _a = _rec.get(_sp)
            if _a and _a["n"] >= 20:
                _hi = [(n, w) for (lo, hi), (n, w) in _a["bands"].items() if lo >= 0.7 and n]
                _hn, _hw = sum(n for n, _ in _hi), sum(w for _, w in _hi)
                _bits.append(f"{_sp}: favorite won {_a['won'] / _a['n']:.0%} of {_a['n']:,}"
                             + (f" ({_hw / _hn:.0%} when it said 70%+, {_hn:,} games)" if _hn >= 10 else ""))
        st.caption(("**Track record** — " + "; ".join(_bits) + ". " if _bits else "")
                   + "**Most likely isn't the same as a good bet:** a heavy favorite usually wins but often costs more "
                     "than it's worth. *Value at price* is the model's chance against the best price (above 0 = the "
                     "price pays more than the model thinks it should); a Use tag appears only where a tested rule "
                     "backs the bet. NFL and UFC aren't covered yet.")
    else:
        st.caption("No games with a model chance today" + ("" if _scope == "All sports" else " for this sport") + ".")
    st.divider()

# ---------- Today's Schedule ----------
# Sport-aware, and only rendered for the sports schedule_board.py actually covers (MLB, NBA,
# WNBA, NFL, NCAAF, NCAAMB) -- UFC (individual bouts, not team matchups -- UFC Fight Card already
# IS its own schedule) is deliberately hidden here rather than shown broken/empty, same "hidden,
# not shown broken" posture the sidebar itself already uses for sport-gated pages. NCAAMB renders
# through the SAME rich board as every other sport here now (added directly on request to League
# Schedules, and this page gets it for free too, same shared schedule_board.py) -- honestly
# grouped into an "Other" section rather than real conferences, since no verified 350+-team
# conference table exists yet, see schedule_board.py's own module docstring for the full reasoning.
if active and current in SB.SUPPORTED_SPORTS:
    today_str = _dt.now(_ET).strftime("%Y-%m-%d")
    with st.spinner("Loading today's schedule..."):
        schedule_result = SB.todays_schedule(current, today_str)

    # ADDED DIRECTLY ON REQUEST: a real, genuinely empty result for TODAY (confirmed by
    # todays_schedule_board's own docstring: this is "a real empty schedule -- a legitimate
    # off-day," not a fetch failure) used to just show a bare "No games scheduled today" and
    # stop there -- for a sport whose season hasn't started yet (NFL/NCAAF preseason, an
    # off-season gap), that's honest but not very useful on its own. Falls forward to the next
    # REAL scheduled date instead, using the same real schedule data, clearly labeled as NOT
    # today so it's never mistaken for it.
    _today_empty = bool(schedule_result) and not schedule_result["grouped"] and not schedule_result["other"]
    if _today_empty:
        with st.spinner("Checking for upcoming games..."):
            _next_date = SB.next_scheduled_date(current, today_str)
        if _next_date:
            with st.spinner("Loading the next scheduled slate..."):
                schedule_result = SB.todays_schedule(current, _next_date)
            st.caption(f"No {active.label} games scheduled today — showing the next real "
                      f"scheduled date instead.")
            C.todays_schedule_board(schedule_result, active.icon, active.label,
                                    heading=f"Next {active.label} games — {_next_date}")
        else:
            C.todays_schedule_board(schedule_result, active.icon, active.label)
    else:
        C.todays_schedule_board(schedule_result, active.icon, active.label)
    st.divider()

if active:
    with st.container(border=True):
        st.markdown(
            f"""
This dashboard is built on a single shared backend (`{active.engine_module}.py`) so every page
pulls the same live data and stays consistent.

Pick a date on any page, and the engine fetches the slate concurrently — a full day
usually loads in a few seconds. See the sidebar for every page available for
**{active.icon} {active.label}**.
"""
        )

st.info(
    "Analytics here describe likelihoods and trends, not certainties. If you publish picks "
    "to an audience, note that gambling-content promotion is regulated in many regions "
    "(affiliate/advertising rules vary by jurisdiction)."
)
