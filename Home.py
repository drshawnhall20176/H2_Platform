import streamlit as st
import sports
import components as C
import schedule_board as SB
from datetime import datetime as _dt
import pytz as _pytz
import props_engine as _PE_H
import money_score as _MSC

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

# Nov 17: the day across every sport (the glance, the four strongest picks, the brief) moved to the entry page,
# Today.py; this page is one sport's desk.
try:
    st.page_link("Today.py", label="← Today: every sport at a glance", icon="📅")
except Exception:                                               # noqa: BLE001 -- builds without the Today page
    pass
# Nov 17: today's promotion for this sport, if any (promos.py)
try:
    import promos as _PROMO
    for _p in _PROMO.on_today(_dt.now(_pytz.timezone("US/Eastern")).date(),
                              [st.session_state.get("sport") or ""], banners_only=True):
        st.info(f"🎁 **{_p['name']}** is on today at {_p['book']} — see Promotions in the sidebar.")
except Exception:                                               # noqa: BLE001
    pass
C.section_header("🏟", "Select Sport")
# Nov 24 (owner: "Select Sport and Sports shown are redundant ... couldn't the multi select be done at the select sport
# level?"): one picker. Pick one sport or several; every table on this desk follows the set. The sidebar's pages are
# one sport's tools, so they open to the sport picked most recently (named under the picker).
if current not in (st.session_state.get("desk_sports") or []):  # arrived from Today / another page: that sport alone
    st.session_state["desk_sports"] = [current]
    st.session_state["_desk_prev"] = [current]


def _desk_changed():
    new = list(st.session_state.get("desk_sports") or [])
    old = list(st.session_state.get("_desk_prev") or [])
    if not new:                                                 # never empty: keep the sidebar's sport
        new = [st.session_state.get("sport", current)]
        st.session_state["desk_sports"] = new
    added = [k for k in new if k not in old]
    if added:
        st.session_state["sport"] = added[-1]
    elif st.session_state.get("sport") not in new:
        st.session_state["sport"] = new[0]
    st.session_state["_desk_prev"] = new


st.pills("Select Sport", [s.key for s in live], selection_mode="multi", key="desk_sports", on_change=_desk_changed,
         format_func=lambda k: f"{sports.get(k).icon} {sports.get(k).label}", label_visibility="collapsed")
current = st.session_state.get("sport", current)

active = sports.get(current)
if active:
    _others = [k for k in (st.session_state.get("desk_sports") or []) if k != current]
    st.caption(f"Sidebar pages open to: **{active.icon} {active.label}**"
               + (f" · this desk also shows {', '.join(_others)}" if _others else "")
               + " — click more sports to add them to the tables below; the last one you click runs the sidebar.")
    if current == "UFC":
        st.info("🥊 UFC Fight Card: tonight's bouts with moneyline odds, the market's no-vig chances, and total-rounds "
               "(fight duration) lines. There's no UFC model — every chance comes from the odds — and method-of-victory "
               "lines aren't shown because the odds feed doesn't carry them.")

st.divider()

# ---------- Today's best (Nov 6) ----------
# The day's top-tagged picks across every in-season sport and the labs, in one list. Props come from the last Best
# Bets board built for each sport today (no extra Odds API spend); game lines, international hoops and tennis from
# their capture jobs. Tags are the same ones each sport's own page shows. Nov 14: both builds (owner rule: public =
# owner minus the Bet Log) -- the log box and the credit-spending Refresh button stay owner-only.
if True:
    import pandas as _pd
    import props_engine as _PE
    import todays_best as _TB
    import pick_records as _PR
    import log_ui as _LU
    _now_day = _dt.now(_ET).date()
    # Nov 14: college basketball props too (they're saved by warm-slates like the rest)
    _props_sports = [s.key for s in live if s.key in ("NBA", "NFL", "NHL", "NCAAF", "NCAAMB", "WNBA", "MLB")]
    C.section_header("⭐", "Today's best")
    # Nov 7: look back -- any earlier date shows that day's picks as they were saved, with how each one went
    _day = st.date_input("Date", _now_day, max_value=_now_day, key="home_best_date", format="MM/DD/YYYY")
    _past = _day < _now_day
    _today = _day.strftime("%Y-%m-%d")
    _best = _TB.collect(_today, _props_sports, past=_past)
    _missing = [k for k, at in _best["props"].items() if not at]
    _c1, _c3 = st.columns([4, 1])
    _here = active.label if active else "This sport"
    # Nov 24 (owner): "select sport enabled to allow for multiple sport filtering ... the tables should update
    # accordingly" -- pick any set of sports; every table below follows it
    _sport_opts = [s.key for s in live]
    _sel = set(st.session_state.get("desk_sports") or [current])     # Nov 24: the one Select Sport picker above
    _multi = len(_sel) > 1
    _scope = "All sports" if set(_sport_opts) <= _sel else "picked"
    # Nov 24 (owner): Tracking and Info only as choices beside Only Locks / Only Money picks / All playable
    _show = _c1.radio("Show", ["🔒 Locks only", "💰 Money picks", "🧪 Tracking", "Info only", "All playable"],
                      horizontal=True, key="home_best_show", label_visibility="collapsed",
                      # Nov 23 (owner): say what each choice shows
                      format_func={"🔒 Locks only": "🔒 Only Locks", "💰 Money picks": "💰 Only Money picks",
                                   "🧪 Tracking": "🧪 Only Tracking", "Info only": "Only Info only",
                                   "All playable": "All picks"}.get,
                      help=_PE_H.MONEY_HELP + " 🧪 Only Tracking = picks from a rule being tested forward (college "
                           "basketball's close-gap games, the football prop Unders). Only Info only = the model's leans "
                           "with no tested edge.")
    if _owner and _c3.button("🔄 Refresh props", width="stretch", disabled=_past,
                  help="Reloads each props sport's board. Boards are rebuilt every hour on the server (Nov 20: "
                       "building them here ran the app out of memory); this picks up the newest one."):
        _BBD_r = __import__("best_bets_data"); _BBD_r.load_generic_best_bets_board.clear()
        import best_bets_data as _BBD
        with st.spinner("Building today's boards…"):
            for _k in _props_sports:
                try:
                    _BBD.load_generic_best_bets_board(_k, _today, _BBD.O.DEFAULT_BOOK)
                except Exception:                               # noqa: BLE001
                    pass
        st.rerun()
    # Nov 6: follow the sport picked above (the panel showed every sport, so NBA showed tennis); "All sports" for the lot
    _rows = [r for r in _best["rows"] if r.get("sport") in _sel]

    # Nov 6: start-time and game filters, shared by the picks and the game lines below
    @st.cache_data(ttl=900, show_spinner=False)
    def _winners(day, past):
        rows = _TB.winner_rows(day, past=past)
        try:                                                    # Nov 14: soccer's goals model, tracking only
            rows += _TB.soccer_rows(day, past=past)
        except Exception:                                       # noqa: BLE001
            pass
        return rows

    _wall = _winners(_today, _past)
    _wscope = [r for r in _wall if r["sport"] in _sel]

    def _tkey(t):
        # Nov 11: the shared parser (clock times, "Sat 7:00 PM", ISO kickoffs); unknown times last
        d = C._kick_dt(t)
        return (0, d.hour * 60 + d.minute) if d else (1, 0)

    @st.cache_data(ttl=900, show_spinner=False)
    def _blowouts(day):
        return _TB.blowout_rows(day)

    try:
        _ball = _blowouts(_today)
    except Exception:                                           # noqa: BLE001
        _ball = []
    _bscope = [r for r in _ball if r["sport"] in _sel]

    # Nov 7: the MMA card (one odds request for the whole card), when UFC is picked or All sports
    @st.cache_data(ttl=900, show_spinner=False)
    def _ufc(day):
        import best_bets_data as _BBD2
        return _TB.ufc_rows(day, _BBD2.get_odds_api_key())

    _uscope = []
    if "UFC" in _sel:
        try:
            _uscope = _ufc(_today)
        except Exception:                                       # noqa: BLE001
            _uscope = []
    _every = _rows + _wscope + _bscope + _uscope
    _times = sorted({r.get("time") for r in _every if r.get("time")}, key=_tkey)
    _gtime = {}
    for r in _every:                                            # Nov 7: games listed by start time, not A-Z
        if r.get("game"):
            _gtime[r["game"]] = min(_gtime.get(r["game"], _tkey(r.get("time"))), _tkey(r.get("time")))
    _games = sorted(_gtime, key=lambda g: (_gtime[g], g))
    _f1, _f2 = st.columns([1, 2])
    _pick_times = _f1.multiselect("Start time", _times, key="home_best_times", placeholder="All times")
    _pick_games = _f2.multiselect("Game", _games, key="home_best_games", placeholder="All games")

    def _keep(r):
        return ((not _pick_times or r.get("time") in _pick_times)
                and (not _pick_games or r.get("game") in _pick_games))

    # Nov 8: kickoff weather for football games (football_weather.py): sky, temperature, wind; ⚠️ = the model adjusts
    @st.cache_data(ttl=1800, show_spinner=False)
    def _wx_label(sport, day, game):
        import football_weather as _FW
        return _FW.label_for(sport, day, game)

    def _wx(sport, game):
        return _wx_label(sport, _today, game) if sport in ("NFL", "NCAAF") else ""

    _rows = [r for r in _rows if _keep(r)]
    _rows = ([r for r in _rows if r.get("lock")] if _show.startswith("🔒") else
             [r for r in _rows if r.get("money")] if _show.startswith("💰") else _rows)
    # Nov 8: every pick type carries its own live record (last 30 days, refreshed by the morning review); a type
    # that's been losing is hidden until it earns its way back -- the visible half of the daily feedback loop
    @st.cache_data(ttl=1800, show_spinner=False)
    def _tag_recs(sp):
        return _PR.tag_records(sp)

    _PR.annotate_props(_rows, _tag_recs)

    @st.cache_data(ttl=1800, show_spinner=False)
    def _money_rec(sp):
        import money_scoreboard as _MSB                         # Nov 20: the new 💰 rule's record, not the old one's
        return _MSB.record_text(sp)
    for _r in _rows:                                            # Nov 19: a 💰 pick shows the 💰 record, not its tag's
        if _r.get("money"):
            _r["record"] = _money_rec(_r.get("sport"))
    _hidden = [r for r in _rows if r.get("verdict") in _PR.HIDE]
    _show_losing = st.toggle(f"Show losing pick types ({len(_hidden)} hidden)", value=False, key="home_best_losing",
                             disabled=not _hidden,
                             help="Pick types whose last-30-day record is under 50% (or 40% and under: the other "
                                  "side has been winning). They come back on their own when the record recovers.")
    if not _show_losing:                                        # a 💰 pick is judged by its own record, not its tag's
        _rows = [r for r in _rows if r.get("verdict") not in _PR.HIDE or r.get("money")]
    # Nov 17: is the market moving toward the model's side since the first price today? (NBA, NFL; tracking signal)
    if not _past:
        @st.cache_data(ttl=600, show_spinner=False)
        def _line_index(sp, day):
            import line_history as _LHx
            return _LHx.sport_index(sp, since=day)
        for _sp in _TB.MOVE_SPORTS:
            try:
                _TB.market_moves(_sp, _today, _rows, index=_line_index(_sp, _today))
            except Exception:                                   # noqa: BLE001
                pass
    _ours = [r for r in _rows if r.get("move") == "📈 our way"]
    if _ours and st.toggle(f"📈 Market moving our way only ({len(_ours)})", value=False, key="home_best_moves",
                           help="Picks whose market has moved toward the model's side since the first price today "
                                "(the line moved our way, or our side got more expensive) -- the earliest sign the "
                                "model is beating the book. Tested on graded picks: NBA 57% when the market moved our "
                                "way vs 53% against; NFL 62% vs 53%. Small samples, so treat it as a tiebreaker."):
        _rows = _ours
    _rows = sorted(_rows, key=lambda r: _tkey(r.get("time")))   # Nov 6: earliest games first (stable: rank kept within a time)
    # Nov 14: every lock is listed (the old 60-row cap, applied after the time sort, cut the late games' locks)
    _cap = len(_rows) if _show.startswith("🔒") else 250
    _sel_props, _sel_lines = [], []                             # Nov 8: ticked rows, logged by the box below the lists

    import game_lines_table as _GLT                             # Nov 20: the shared game-lines board's log items
    _line_items = _GLT.line_items                              # (GLT.line_items)
    if _past and _rows:                                         # Nov 19: looking back -- the split, by chance range
        C.hit_miss_breakdown(_rows, "result", "chance", key="home_best_hm", title="Picks that hit and missed")
        _rows = C.show_filter(_rows, "result", key="home_best_hm_show")
    import game_previews as _GPp
    _SHOWBET = {"🧪 Tracking": _GPp.BET_TRACK, "Info only": _GPp.BET_INFO}
    if _rows and _show in _SHOWBET:                             # Nov 24: the Show choice picks the Bet? kind
        _rows = [r for r in _rows if _GPp.prop_bet(r.get("sport"), ("💰 " if r.get("money") else "")
                                                   + ("🔒 " if r.get("lock") else "") + (r.get("use") or ""),
                                                   r) == _SHOWBET[_show]]
    if _rows:
        _df = _pd.DataFrame([{"Sport": r["sport"], "Time": r.get("time") or "", "Game": r.get("game"),
                              "Bet?": _GPp.prop_bet(r.get("sport"), ("💰 " if r.get("money") else "")
                                                    + ("🔒 " if r.get("lock") else "") + (r.get("use") or ""), r),
                              "Pick": r["pick"],
                              "Use": ("💰 " if r.get("money") else "") + ("🔒 " if r.get("lock") else "")
                                     + (r.get("use") or ""),
                              "Record (30d)": r.get("record") or "—",
                              "Chance": r.get("chance"),
                              "Price": ("—" if r.get("price") is None else f"{float(r['price']):+.0f}"),
                              "Needs": ("" if r.get("need") is None else f"{float(r['need']):+.0f} or better"),
                              "Market": " ".join(x for x in (r.get("move") or "", f"({r['move_why']})" if r.get("move_why") else "") if x),
                              "Weather": _wx(r.get("sport"), r.get("game")),
                              "Where": r.get("page"),
                              "Tested": "no backtest" if r.get("untested") else "",
                              "Result": _TB.RESULT_ICON.get(r.get("result"), "—")} for r in _rows[:_cap]])
        if not _past:
            _df = _df.drop(columns=["Result"])
        if not _df["Weather"].replace("", None).notna().any():
            _df = _df.drop(columns=["Weather"])
        if not _df["Needs"].any():
            _df = _df.drop(columns=["Needs"])
        if not _df["Market"].any():
            _df = _df.drop(columns=["Market"])
        if not _df["Tested"].any():
            _df = _df.drop(columns=["Tested"])
        # Nov 24: the Sport column stays -- the tables show it as League, first
        _sel_props = _LU.picked(_rows[:_cap], _LU.selectable(_df, "home_best_sel", hide_index=True, width="stretch",
                     column_config={"Chance": st.column_config.NumberColumn(format="percent"),
                                    "Record (30d)": st.column_config.TextColumn(help=(
                                        "How this KIND of pick has done in this sport over the last 30 days — every "
                                        "pick with the same Use tag (e.g. all NBA 'No edge' reads), not this player. "
                                        "The ± is the likely range. 💰 rows show the 💰 Money picks' own record "
                                        "(from the weekly money review) instead."))}))
        _fades = sorted({f"{r['sport']} {_PR._strip(r.get('use'))}" for r in _rows if r.get("verdict") == "fade"})
        if _fades:
            st.warning("**Consider the fade:** " + ", ".join(_fades) + " — the other side of these has been winning "
                       "60%+. Check the opposite side's price before betting either way.")
        if any(r.get("untested") for r in _rows):
            st.caption("**No backtest:** these tennis matches (events only ESPN lists, with no posted prices) are tagged "
                       "from the model's chance alone — nothing has tested that chance yet. On main-tour matches the "
                       "books beat this model, so those are always ⚪ No edge. Treat these as reads, and only at the "
                       "price shown under Needs or better.")
    else:
        _none = {"🔒 Locks only": "locks", "💰 Money picks": "💰 Money picks", "🧪 Tracking": "🧪 Tracking picks",
                 "Info only": "Info-only picks"}.get(_show, "picks")
        _when = f"on {_day:%a %b %-d}" if _past else "yet today"
        st.caption(f"No {_none} for {', '.join(sorted(_sel))} {_when}"
                   + (" among the player props — the game lines are further down." if not _past else "."))
    _notes = []
    if _past and _rows:
        _gr = [r for r in _rows if r.get("result") in ("win", "loss")]
        if _gr:
            _wn = sum(r["result"] == "win" for r in _gr)
            _notes.append(f"**{_day:%a %b %-d}: {_wn}–{len(_gr) - _wn}** on the picks listed (graded ones).")
    if _missing and not _past:
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

    # ---- Most probable long shots (Nov 14): for each sport with a Long Shots tab, the top few from the day's scan
    import long_shots_scan as _LSS
    _ls_sports = [k for k in _LSS.SPORTS if k in _sel and k in [s.key for s in live]]
    _ls_sets = [(k, _LSS.load(k, _today)) for k in _ls_sports]

    @st.cache_data(ttl=3600, show_spinner="Rebuilding that day's long shots…")
    def _ls_rebuilt(k, day):
        return _LSS.rebuild_past(k, day)
    if _past:                                                   # Nov 19: a past day whose saved scan is gone
        _ls_sets = [(k, v if v and v.get("top") else _ls_rebuilt(k, _today)) for k, v in _ls_sets]
    _ls_sets = [(k, v) for k, v in _ls_sets if v and v.get("top")]
    if _ls_sports:
        st.markdown("##### 💎 Most probable long shots")
        if not _ls_sets:
            st.caption("No long shots saved for this day (the scan's alternate prices weren't kept)." if _past else
                       "No long-shot scan yet for today — it runs a few times a day once the books post alternate "
                       "lines (and on the Long Shots page).")
        _ls_items = []
        @st.cache_data(ttl=1800, show_spinner=False)
        def _ls_graded(k, day, rows):
            return _LSS.grade_saved(list(rows), k, day)

        for _k, _v in _ls_sets:
            _top = [r for r in _v["top"] if _keep(r)]
            if _show == "🧪 Tracking":
                _top = []
            elif _show == "Info only":
                _top = [r for r in _top if not r.get("tested")]
            if not _top:
                continue
            if _past:                                           # Nov 19: how each went, from that night's box scores
                try:
                    _top = _ls_graded(_k, _today, tuple(_top))
                except Exception:                               # noqa: BLE001
                    pass
                C.hit_miss_breakdown(_top, "Hit", "Honest chance", key=f"home_ls_hm_{_k}",
                                     title=f"{_k} long shots that hit and missed")
                _top = C.show_filter(_top, "Hit", key=f"home_ls_show_{_k}")
            try:
                _at = _dt.fromisoformat(_v["at"]).astimezone(_ET).strftime("%-I:%M %p")
            except (TypeError, ValueError):
                _at = ""
            st.markdown(f"**{_k}** · {len(_v.get('rows') or [])} value long shots across {_v.get('games', 0)} games"
                        + (f" · prices as of {_at}" if _at else "")
                        + (" · rebuilt from that night's saved reads and alternate prices" if _v.get("rebuilt") else ""))
            # Nov 24 (owner: "most-probable longshots look different"): the same layout as every table -- League,
            # Time, Game, Bet? first; the tested market is 🃏 Bet (it was a ✅, which now means model & market agree)
            _ldf = _pd.DataFrame([{"League": _k, "Time": r.get("time") or "", "Game": r.get("game") or "",
                                   "Bet?": "🃏 Bet" if r.get("tested") else "Info only", "Pick": r.get("pick"),
                                   "Price": r.get("Price"), "Honest chance": r.get("Honest chance"),
                                   "Book says": r.get("Book says"), "EV per $1": r.get("EV per $1"),
                                   "Market": str(r.get("Market") or ""),
                                   **({"Actual": r.get("Actual"), "Result": r.get("Hit") or "—"} if _past else {})}
                                  for r in _top])
            _ls_items += _LU.picked(_top, _LU.selectable(_ldf, f"home_ls_{_k}", hide_index=True, width="stretch",
                                    column_config={"Price": st.column_config.NumberColumn(format="%+d"),
                                                   "Honest chance": st.column_config.NumberColumn(format="percent"),
                                                   "Book says": st.column_config.NumberColumn(format="percent"),
                                                   "EV per $1": st.column_config.NumberColumn(format="%+.2f")}))
        if _ls_sets:
            _LU.panel(_ls_items, "home_ls_log", _today, tag="long-shot", past=_past)
            st.caption(C.money_md(
                "The most likely long shots (priced +400 or longer) that are still worth their price at the honest "
                "chance, one per player, from the Long Shots finder — only where the model and the book roughly agree "
                "on the player's normal night (projection within 25% of the book's main line), so these are tail "
                "outcomes, not bets that the book has the player wrong. 🃏 Bet = the one market whose long-shot value lines have "
                "made money in testing (NBA Assists, NFL Rush Yards, college football Rush and Receiving Yards); the rest "
                "lost 19–32% overall (NHL: 11–25%). Most of these lose "
                "— keep stakes flat at a few dollars and never put two of the same player in one parlay."))

    # ---- Lab long shots (Nov 14): tennis, international hoops and soccer, read from their labs -- tracking only
    @st.cache_data(ttl=900, show_spinner=False)
    def _lab_ls(day):
        import lab_long_shots as _LLS
        return _LLS.collect(day)

    _lab_names = {"TENNIS": "Tennis", "INTL": "International hoops", "SOCCER": "Soccer",
                  "SOCCER_SCORERS": "Soccer goalscorers"}
    _lab_sets = []
    if not _past and (_sel & {"TENNIS", "INTL", "SOCCER"}):
        try:
            _lab_sets = [(k, v) for k, v in _lab_ls(_today).items()
                         if k.split("_")[0] in _sel]
        except Exception:                                       # noqa: BLE001
            _lab_sets = []
    if _lab_sets:
        if not _ls_sports:
            st.markdown("##### 💎 Most probable long shots")
        _lab_items = []
        for _k, _v in _lab_sets:
            _top = [r for r in _v["top"] if _keep(r)]
            if not _top:
                continue
            try:
                _at = _dt.fromisoformat(_v["at"]).astimezone(_ET).strftime("%-I:%M %p") if _v.get("at") else ""
            except (TypeError, ValueError):
                _at = ""
            st.markdown(f"**{_lab_names.get(_k, _k)}** · {_v['n']} value {_v['kind']} · untested, tracking"
                        + (f" · prices as of {_at}" if _at else ""))
            _labdf = _pd.DataFrame([{"League": r.get("league") or _lab_names.get(_k, _k), "Time": r.get("time") or "",
                                     "Game": r.get("game") or "", "Bet?": "Info only", "Pick": r.get("pick"),
                                     "Price": r.get("Price"),
                                     "Model chance": r.get("chance"), "EV per $1": r.get("EV per $1"),
                                     "Book": r.get("book") or ""} for r in _top])
            _lab_items += _LU.picked(_top, _LU.selectable(_labdf, f"home_labls_{_k}", hide_index=True, width="stretch",
                                     column_config={"Price": st.column_config.NumberColumn(format="%+d"),
                                                    "Model chance": st.column_config.NumberColumn(format="percent"),
                                                    "EV per $1": st.column_config.NumberColumn(format="%+.2f")}))
        _LU.panel([dict(r, best=r.get("pick"), bet_price=r.get("price")) for r in _lab_items], "home_labls_log",
                  _today, tag="long-shot,lab", past=_past)
        st.caption(C.money_md(
            "From the labs, no extra credits: the model's **underdogs** priced +300 or longer whose model chance still "
            "beats the price (tennis uses the calibrated chance; soccer counts a draw or either side), and **soccer "
            "anytime goalscorers** at +400 or longer for regular starters (5+ starts in the last 10), scanned a few "
            "times a day. Only where the model and the book roughly agree (the model's chance at most 1.5× what the price "
            "implies) — a bigger disagreement is usually the book knowing something the model doesn't. None of this is tested — the soccer goals model lost to the closing line, and hoops and "
            "tennis underdogs have no backtest — so it's a tracking list. Most of these lose; flat stakes of a few "
            "dollars, if any."))

    # ---- Most likely winners (Nov 6): every game today, the side the model thinks wins, for every sport covered
    @st.cache_data(ttl=21600, show_spinner=False)
    def _winner_record():
        return _TB.winner_record()

    LEANS_CAP = 250                                             # Nov 14: soccer and every hoops league are in here
    st.markdown("##### 🏆 Game lines: tested picks and model leans")
    _w = [r for r in _wscope if _keep(r)]
    if _sel == {"UFC"}:
        st.caption("Not covered for this sport: UFC's chances come from the odds themselves. Choose All sports to see "
                   "the rest.")
    elif _w:
        # Nov 6 (revised): tested picks first (bet, backtested chance, price, value), then every other game's lean --
        # the spread or total the model disagrees with most, its own number beside the line, no invented value
        # Nov 6: earliest games first; within a start time, tested picks, then the strongest leans
        _w = sorted(_w, key=lambda r: (_tkey(r.get("time")), not r.get("best_tested"), r.get("backtest") is None,
                                       -(r.get("backtest") or 0), -(r.get("lean_z") or 0)))
        @st.cache_data(ttl=1800, show_spinner=False)
        def _lean_recs(lg):
            return _PR.lean_records(lg)

        _PR.annotate_leans(_w, _lean_recs)
        _t1, _t2 = st.columns(2)
        _only_tested = _t1.toggle("Tested picks only", value=False, key="home_win_tested")
        _lhid = [r for r in _w if not r.get("best_tested") and r.get("lean_verdict") in _PR.HIDE]
        _lshow = _t2.toggle(f"Show losing lean types ({len(_lhid)} hidden)", value=False, key="home_win_losing",
                            disabled=not _lhid, help="Untested leans in a market where the model's lean has lost "
                                                     "more than it won over the last 30 days.")
        _ws = [r for r in _w if r.get("best_tested")] if _only_tested else _w
        _gours = [r for r in _ws if r.get("spread_move") == "📈 our way"]
        if _gours and st.toggle(f"📈 Spread moving our way only ({len(_gours)})", value=False, key="home_win_moves",
                                help="College basketball games where the spread has moved a point or more toward the "
                                     "model's side since it opened. Tested on 519 graded games: the model's side "
                                     "covered 55% even at the moved (closing) number, vs 47% when the spread moved "
                                     "against it. Bet these early -- the opening number covered 65%."):
            _ws = _gours
        import game_lines_table as _GLTb
        import game_previews as _GPb
        if not _lshow:                                          # a 🧪 Tracking / 🃏 Bet row is never hidden as "losing"
            _ws = [r for r in _ws if r.get("best_tested") or r.get("lean_verdict") not in _PR.HIDE
                   or not _GLTb.bet(r).startswith(_GPb.BET_INFO)]
        if _show == "🧪 Tracking":                              # Nov 24 (owner): the Show choice, on the game lines too
            _ws = [r for r in _ws if _GLTb.bet(r).startswith(_GPb.BET_TRACK)]
        elif _show == "Info only":
            _ws = [r for r in _ws if _GLTb.bet(r).startswith(_GPb.BET_INFO)]
        # Nov 20 (owner): the Show choice filters the game lines too -- 🔒 rows only, 💰 rows only, or everything
        if _show == "💰 Money picks":
            _ws = [r for r in _ws if r.get("money")]
        elif _show == "🔒 Locks only":
            _ws = [r for r in _ws if r.get("lock")]
        if not _ws and _w:                                      # Nov 24 (owner): say why the board is empty
            _kind = {"🔒 Locks only": "🔒 Lock", "💰 Money picks": "💰 Money", "🧪 Tracking": "🧪 Tracking",
                     "Info only": "Info-only"}.get(_show, "matching")
            _lg = ", ".join(sorted({r["sport"] for r in _w}))
            _ntr = sum(1 for r in _w if _GLTb.bet(r).startswith(_GPb.BET_TRACK))
            st.info(f"No {_kind} game lines for {_lg} today — **{len(_w)} games** are on the board. Choose **All picks** "
                    "above to see them"
                    + (f" ({_ntr} are 🧪 Tracking — choose **🧪 Only Tracking**)" if _ntr and _show != "🧪 Tracking" else "")
                    + ". Games with no tested or tracked rule read **Info only** in the Bet? column.")
        if _past and _ws:                                       # Nov 19: the picks' split, by chance range, and a filter
            # Nov 19 (owner): two result columns, two charts -- the pick, and the model's likely winner
            _gproxy = [{"pick": r.get("best_result"),
                        "pick_chance": r.get("best_chance") if r.get("best_tested") else r.get("backtest"),
                        "winner": r.get("winner_result"), "winner_chance": r.get("chance"),
                        # Nov 20: the Money Score's side, on games scoring +4% or better (money_score.BAND)
                        "money": r.get("money_result") if (r.get("money_score") or -1) >= _MSC.BAND[0] else None,
                        "money_chance": r.get("money_chance")} for r in _ws]
            C.hit_miss_pair([("Line pick result", _gproxy, "pick", "pick_chance"),
                             ("Winner pick result", _gproxy, "winner", "winner_chance"),
                             ("Money pick result (score +4%+)", _gproxy, "money", "money_chance")],
                            key="home_win_hm", title="Game lines: how the Line picks, Winner picks and Money picks did")
            _, _ws = C.show_filter(_gproxy, "pick", key="home_win_hm_show", apply_to=_ws,
                                   by={"Line pick result": "pick", "Winner pick result": "winner",
                                       "Money pick result": "money"})
        import game_lines_table as _GLT0
        _wdf = _pd.DataFrame([{"Sport": r["sport"], "Time": r["time"], "Game": r["game"], "Bet?": _GLT0.bet(r), **_GLT0.extras(r),
                               "Weather": _wx(r["sport"], r["game"]),
                               "Spread": r.get("spread_txt") or "",
                               "Total": r.get("total_txt") or "",
                               "Model": r.get("model_txt") or r.get("lean_detail") or "",
                               "Spread move": " ".join(x for x in (r.get("spread_move") or "",
                                                                    f"({r['spread_move_why']})" if r.get("spread_move_why") else "") if x),
                               "✓ Pick": False,
                               "Pick": r.get("best") or "—",
                               "Use": _PR.lean_use(r),
                               "Record (30d)": ((("⚠️ " if r.get("lean_verdict") in _PR.HIDE else "")
                                                 + r["lean_record"]) if r.get("lean_record") else "—"),
                               "Backtest cover": r.get("backtest") if not r.get("best_tested") else None,
                               "Chance": r.get("best_chance") if r.get("best_tested") else None,
                               "Price": (f"{float(r['best_price']):+.0f}" if r.get("best_tested") and r.get("best_price")
                                         is not None else ""),
                               "Value": r.get("best_value") if r.get("best_tested") else None,
                               "✓ Winner": False,
                               "Likely winner": f"{r['winner']} ({r['chance']:.0%})",
                               # Nov 20: the third measure -- what the price pays (money_score.py)
                               "Money score": r.get("money_score"),
                               "✓ Money": False,
                               "Money pick": ((("💰 " if r.get("money") else "") + r["money_pick"]
                                               + (f" {float(r['money_price']):+.0f}" if r.get("money_price") is not None
                                                  else "")
                                               + (f" · {_PE_H.stake_units(r.get('money_chance'), r.get('money_price')):g}u"
                                                  if r.get("money") and _PE_H.stake_units(r.get("money_chance"),
                                                                                         r.get("money_price")) else ""))
                                              if r.get("money_pick") else "—"),
                               "League": _GLT0.league_of(r),
                               "Final": r.get("final") or "—",
                               "Pick result": _TB.RESULT_ICON.get(r.get("best_result"), "—"),
                               "Winner result": _TB.RESULT_ICON.get(r.get("winner_result"), "—"),
                               "Money result": _TB.RESULT_ICON.get(r.get("money_result"), "—")} for r in _ws[:LEANS_CAP]])
        if not _past and not _wdf.empty:
            _wdf = _wdf.drop(columns=["Final", "Pick result", "Winner result", "Money result"])
        if not _wdf.empty and not _wdf["Spread move"].any():
            _wdf = _wdf.drop(columns=["Spread move"])
        if not _wdf.empty and "League" in _wdf:                 # Nov 24: League (first) names the sport
            _wdf = _wdf.drop(columns=["Sport"])
        if not _wdf.empty and not _wdf["Weather"].replace("", None).notna().any():
            _wdf = _wdf.drop(columns=["Weather"])
        if not _wdf.empty:                                       # columns with nothing in them (no tested picks) go
            _wdf = _wdf.drop(columns=[c for c in ("Chance", "Price", "Value", "Backtest cover", "Spread", "Total",
                                                  "Money score")
                                      if c in _wdf and not _wdf[c].replace("", None).notna().any()])
        # Nov 20 (owner: "more investor friendly -- the more important columns to the left, informational to the
        # right"): the bet and how it did first, then the model's pick and the likely winner, then the detail
        _ORDER = ["League", "Time", "Sport", "Game", "Bet?", "Model & market agree?", "Blowout risk", "Close gap (pts)",
                  "Spread move", "Final", "Pick result", "Money result", "Winner result",
                  "✓ Pick", "Pick", "Use", "Chance", "Price", "Value",
                  "✓ Money", "Money pick", "Money score",
                  "✓ Winner", "Likely winner", "Record (30d)", "Backtest cover", "Last meetings", "Spread", "Total", "Model",
                  "Weather"]
        if not _wdf.empty:
            _wdf = _wdf[[c for c in _ORDER if c in _wdf.columns] + [c for c in _wdf.columns if c not in _ORDER]]
        if _wdf.empty:
            st.caption({"💰 Money picks": "No 💰 game lines" + (" today" if not _past else "") + " — switch to All "
                                          "playable to see every game.",
                        "🔒 Locks only": "No 🔒 game lines" + (" today" if not _past else "") + " — switch to All "
                                         "playable to see every game."}.get(_show, "No tested game-line picks today."))
        else:
            import game_lines_table as _GLT
            import game_previews as _GPV
            _wdf, _unote = _GPV.collapse_use(_wdf)               # Nov 23: a Use column that's ⚪ on every row goes
            if _unote:
                st.caption(_unote)
            with st.expander("📖 How to read the game lines — the three picks and every column", expanded=False):
                st.markdown(_GLT.LEGEND)
            st.caption("☑️ Tick **Line pick**, **Winner pick** or **Money pick** on any row to log that bet — each box "
                       "sits right before the bet it logs.")
            _ticks_l = _GLT.back(_LU.tick_grid(
                _GLT.display(_wdf), [_GLT.DISPLAY[t] for t in ("✓ Pick", "✓ Money", "✓ Winner")], "home_win_ticks",
                hide_index=True, width="stretch", tick_help=_GLT.TICK_HELP,
                         column_config=_GLT.config({"Chance": st.column_config.NumberColumn(format="percent"),
                                        "Value": st.column_config.NumberColumn(format="percent"),
                                        "Money score": st.column_config.NumberColumn(
                                            format="percent", help="What the price pays: expected return per $1 at "
                                            "the best price, from a chance that trusts the model only as far as its "
                                            "record against the books has earned. 💰 = college basketball, +4% to "
                                            "+12% with a 40%+ chance (what made money in testing)."),
                                        "Backtest cover": st.column_config.NumberColumn(format="percent")})))
            _sel_lines = _line_items(_ws[:LEANS_CAP], _ticks_l)
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
        st.caption(("**Track record** (likely winner) — " + "; ".join(_bits) + ". " if _bits else "")
                   + "**Use** — the same symbols as every page: 🎟️ Parlay + Single / 🎟️ Parlay leg / 🎯 Single only / ⚪ No edge. "
                     "A tested pick (a backtest supports the rule: NCAAMB spreads at 8+ points of disagreement, EuroLeague "
                     "spreads, NBL moneylines) carries its rule's tag, with a real chance and value. Every other game shows "
                     "the model's **lean** (the spread or total it disagrees with most): 🎯 Single only when leans of that "
                     "kind and size have won 55%+ (backtest, or 20+ games in the last 30 days), otherwise ⚪ No edge. "
                     "52.4% breaks even at −110. Tick a row and the log box shows its grade (A–F) and why. **Spread / "
                     "Total** are the books' lines; **Model** is the model's own score. College football leans are ⛔ "
                     "Pass: its spread model was retested Nov 14 and is a coin flip against the closing line. Heavy "
                     "favorites aren't listed as picks: they usually win but cost more than they're worth. **Soccer** rows "
                     "show the goals model's most likely result beside the market's favourite — tracking only, ⚪ No edge. "
                     "NFL and UFC aren't covered yet.")
    else:
        st.caption("No games with a model chance today" + ("" if _multi else " for this sport") + ".")

    # ---- Soccer price flags (Nov 14): a US price above the sharp (Pinnacle) no-vig line by 2%+ -- tracking only
    if "SOCCER" in _sel:
        @st.cache_data(ttl=900, show_spinner=False)
        def _soccer_flags(day):
            return _TB.soccer_flags(day)

        try:
            _sf = [r for r in _soccer_flags(_today) if _keep(r)] if not _past else []
        except Exception:                                       # noqa: BLE001
            _sf = []
        if _sf:
            st.markdown("##### 📈 Soccer price flags (tracking)")
            _sf = sorted(_sf, key=lambda r: (_tkey(r.get("time")), -(r.get("ev") or 0)))
            _sfdf = _pd.DataFrame([{"Time": r["time"], "League": r["league"], "Match": r["game"], "Bet": r["pick"],
                                    "Best US price": r.get("price"), "Book": r.get("book") or "",
                                    "Sharp fair chance": r.get("chance"), "Edge vs sharp": r.get("ev"),
                                    "Goals model": r.get("projected") or ""} for r in _sf])
            _sel_sf = _LU.picked(_sf, _LU.selectable(_sfdf, "home_soccer_flags", hide_index=True, width="stretch",
                                 column_config={"Best US price": st.column_config.NumberColumn(format="%+d"),
                                                "Sharp fair chance": st.column_config.NumberColumn(format="percent"),
                                                "Edge vs sharp": st.column_config.NumberColumn(format="percent")}))
            _sel_lines = list(_sel_lines) + [dict(r, best=r["pick"], bet_price=r.get("price"), price=r.get("price"),
                                                  grade=("tracking only" if r.get("status") else _PR.grade(r)))
                                             for r in _sel_sf if r.get("bet_market") and r.get("pick")]
            st.caption(C.money_md(
                "A US book's price that beats Pinnacle's no-vig line by 2% or more. Untested: these are tracked to see "
                "whether the edge holds up (the Soccer Lab keeps the record). Small flat stakes only, if any."))
    # ---- Blowout watch (Nov 7): the games most likely to be decided big, and by whom -- the Game Script loop's calls
    # ---- UFC / MMA card (Nov 7)
    if "UFC" in _sel:
        st.markdown("##### 🥊 Fight card")
        _u = sorted([r for r in _uscope if _keep(r)], key=lambda r: r.get("commence") or "")
        if _u:
            _udf = _pd.DataFrame([{"Time": r["time"], "Bout": r["game"], "Favorite": r["fav"] or "—",
                                   "Market chance": r["chance"],
                                   "Best price (fav)": "—" if r["fav_price"] is None else f"{float(r['fav_price']):+.0f}",
                                   "Best price (dog)": "—" if r["dog_price"] is None else f"{float(r['dog_price']):+.0f}",
                                   "Spread (DK)": r.get("spread") or "", "Total rounds (DK)": r.get("total") or "",
                                   "Books": r["books"]} for r in _u])
            st.dataframe(_udf, hide_index=True, width="stretch",
                         column_config={"Market chance": st.column_config.NumberColumn(
                             format="percent", help="The books' no-vig chance for the favorite.")})
            st.caption(f"{len(_u)} bouts (priced by a major US sportsbook), earliest first. **Market chance** is the books' "
                       "read with the vig removed — there's no UFC model yet, so these aren't picks. Spread and total "
                       "rounds are DraftKings' lines. Method of victory, KO-only and round props aren't in the odds feed. "
                       "Smaller promotions' bouts are on **UFC Fight Card** (switch off 'Main cards only').")
        else:
            st.caption("No MMA bouts listed for this date" + (" (completed bouts drop out of the odds feed)." if _past
                                                              else "."))
    st.markdown("##### 💥 Blowout watch")
    _bw = [r for r in _bscope if _keep(r)]
    if _bw:
        _bn = st.slider("Games shown (highest blowout chance)", 3, 25, 8, key="home_blow_n") if len(_bw) > 3 else len(_bw)
        # the N most likely blowouts, listed earliest game first (like every table here), across sports
        _btop = sorted(_bw[:_bn], key=lambda r: (_tkey(r.get("time")), -r["chance"]))
        if _past:
            # Nov 19 (owner): a 27% blowout chance isn't a blowout call. Two honest checks instead: did blowouts
            # happen about as often as the chances said, and was the model's MOST LIKELY outcome right?
            _gb = [r for r in _btop if r.get("y")]
            if _gb:
                _bh = sum(1 for r in _gb if r.get("blowout_hit"))
                _be = sum(r["chance"] for r in _gb)
                st.markdown(f"**Blowouts: {_bh} of {len(_gb)} happened — the chances said about {_be:.1f}.** "
                            + ("Right on." if abs(_bh - _be) <= max(1.0, 0.25 * _be) else
                               ("More than expected." if _bh > _be else "Fewer than expected."))
                            + f" At about {_be / len(_gb):.0%} each, most of these games were never expected to be "
                              "blowouts — judge the list by that count, not by any one game.")
            C.hit_miss_breakdown(_btop, "likely_result", "likely_chance", key="home_blow_hm",
                                 title="The model's most likely outcome — right or wrong")
            _btop = C.show_filter(_btop, "likely_result", key="home_blow_show")
        _bdf = _pd.DataFrame([{"Sport": r["sport"], "Time": r["time"], "Game": r["game"],
                               "Most likely to win big": f"{r['team']} ({r['who']})",
                               "Blowout chance": r["chance"], "Win big by": r["margin"],
                               "Close game": r["close"], "Line": r["line"],
                               "Most likely outcome": r.get("likely") or "—",
                               "What happened": r.get("happened") or "—",
                               "Called it": r.get("likely_result") or "—"} for r in _btop])
        # Nov 24: Sport stays and reads as League, first
        if not _past:
            _bdf = _bdf.drop(columns=["What happened", "Called it"])
        st.dataframe(_bdf, hide_index=True, width="stretch",
                     column_config={"Blowout chance": st.column_config.NumberColumn(format="percent",
                                        help="Chance this team wins by the blowout margin, before the game. The list "
                                             "is ranked by it -- the games most likely to get out of hand -- but even "
                                             "the top one is usually under 50%: a watch list, not a prediction."),
                                    "Most likely outcome": st.column_config.TextColumn(
                                        help="The outcome the model gave the best chance: favorite wins big, underdog "
                                             "wins big, close game, or decided but not a blowout. 'Called it' grades "
                                             "this."),
                                    "Close game": st.column_config.NumberColumn(format="percent",
                                        help="Chance the game finishes within the close margin.")})
        st.caption("From the Game Script learning job: every game's chances before it starts, from the line curve that "
                   "beat the old spread table on games it wasn't fit on (refit twice a day as games finish). "
                   "Matchup history doesn't move these numbers yet — tested, the line already prices it. Open "
                   "**Game Script** to see how each player's props read if it goes that way.")
    else:
        st.caption("No blowout calls for these games yet — the learning job logs them each morning and afternoon "
                   "(NBA, college basketball, NFL, college football, NHL).")
    # ---- Log picks to the Bet Log (Nov 8: tick rows in the tables above -- props and game lines -- singles / parlay)
    _ticked = list(_sel_props) + list(_sel_lines)
    _LU.panel(_ticked, "home_log", _today, past=_past)
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
