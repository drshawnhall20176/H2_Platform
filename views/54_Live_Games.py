"""
Live Games (Nov 12) — in-game projections for games in progress: win chance, projected final score, the fair live
spread and total, and (on request) the books' live lines checked against them. Owner + public (no bet log here).
Feeds and reads: live_games.py; math: live_model.py; checked on past games: research/live_backtest.py.
"""
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

import components as C
import live_games as LG
import live_model as LM
import sports

C.base_css()
C.page_header("🔴", "Live Games",
              "Games in progress: who's likely to win from here, the projected final score, and the fair live spread "
              "and total — built from the pre-game projection and how the game is actually going.")

_SPORT_LEAGUES = {"NBA": ["NBA"], "NCAAMB": ["NCAAMB"], "NHL": ["NHL"], "WNBA": ["WNBA"], "NFL": ["NFL"],
                  "NCAAF": ["NCAAF"],
                  "INTL": list(LG.INTL), "TENNIS": ["TENNIS"], "SOCCER": ["SOCCER"]}
if True:                                                         # Nov 13: international -- only leagues playing
    import intl_picks as _IP                                     # today or tomorrow (like soccer)
    _on = _IP.slate_leagues()
    if _on:
        _SPORT_LEAGUES["INTL"] = [k for k in LG.INTL if k in _on]
_key = sports.active_key()
_choices = _SPORT_LEAGUES.get(_key)
if not _choices:
    st.info("Live Games covers basketball (NBA, WNBA, college, EuroLeague, EuroCup, NBL), football (NFL, college), "
            "the NHL, tennis and soccer — pick one of those sports at the top.")
    st.stop()
league = _choices[0] if len(_choices) == 1 else st.radio(
    "League", _choices, horizontal=True, format_func=lambda k: LG.TITLE.get(k, k), key="live_league")

_ET = pytz.timezone("US/Eastern")
_today = datetime.now(_ET).date()


@st.cache_data(ttl=25, show_spinner=False)
def _games(lg, day):
    return LG.games(lg, day)


@st.cache_data(ttl=600, show_spinner=False)
def _picks(lg):
    try:
        import model_store as MS
        return MS.load_game_picks(lg)
    except Exception:                                           # noqa: BLE001
        return []


@st.cache_data(ttl=30, show_spinner=False)
def _odds(lg, api_key):
    return LG.live_odds(lg, api_key)


def _api_key():
    try:
        import best_bets_data as BBD
        return BBD.get_odds_api_key()
    except Exception:                                           # noqa: BLE001
        return None


c1, c2 = st.columns([1, 1])
# Nov 12: updates on its own by default (scores, live reads, box scores and live props all refresh together)
_EVERY = {"Every 30 seconds": 30, "Every minute": 60, "Every 2 minutes": 120, "Off (manual)": None}
_pick_every = c1.selectbox("Update", list(_EVERY), index=0, key="live_every")
auto = _EVERY[_pick_every]
# Nov 27 (owner: catch live bets): the books' live lines are on by default -- game lines and player props, checked
# against the live read on every update. The fetch is cached and shared by everyone viewing, so it costs the same for
# one viewer as for fifty.
with_lines = c2.toggle("Check the books' live lines (game lines and player props, every update)",
                       value=True, key="live_lines",
                       disabled=league not in ("NBA", "NCAAMB", "NHL", "WNBA", "EUROLEAGUE", "NBL", "TENNIS", "NFL",
                                               "NCAAF"))


@st.cache_data(ttl=25, show_spinner=False)
def _tennis(day):
    return LG.tennis_matches(day)


@st.cache_data(ttl=60, show_spinner=False)
def _tennis_odds(api_key):
    return LG.tennis_live_odds(api_key)


def _bets_table(bets):
    df = pd.DataFrame([{"Signal": b["signal"], "Bet": b["bet"], "Price": b["price"], "Model chance": b["chance"],
                        "Edge per $1": b["edge"]} for b in bets])
    st.dataframe(df, hide_index=True, width="stretch", column_config={
        "Price": st.column_config.NumberColumn(format="%+d"),
        "Model chance": st.column_config.NumberColumn(format="percent"),
        "Edge per $1": st.column_config.NumberColumn(format="%+.2f")})


@st.cache_data(ttl=25, show_spinner=False)
def _summary(lg, event_id):
    if lg not in LG.ESPN_PATH or not event_id:
        return {}
    import intl_hoops as _I
    return _I._http(f"https://site.api.espn.com/apis/site/v2/sports/{LG.ESPN_PATH[lg]}/summary",
                    {"event": event_id}) or {}


@st.cache_data(ttl=3600, show_spinner=False)
def _books_pregame(lg, event_id):
    return LG.espn_pregame(lg, event_id)


@st.cache_data(ttl=600, show_spinner=False)
def _prop_snaps(lg, day_s):
    """Tonight's pre-game prop reads (latest save per player and market)."""
    try:
        import model_store as MS
        best = {}
        for s_ in MS.load_snapshots(lg, [day_s]):
            k = (s_.get("player"), s_.get("market"))
            if k not in best or str(s_.get("ts") or "") > str(best[k].get("ts") or ""):
                best[k] = s_
        return list(best.values())
    except Exception:                                           # noqa: BLE001
        return []


def _box_panel(g):
    import live_props as LP
    tables = LP.box_tables(_summary(g["league"], g.get("event_id")), g["league"])
    if not tables:
        st.caption("No box score yet.")
        return
    for t in tables:
        st.markdown(f"**{t['team']}**" + (f" · {t['group']}" if t["group"] else ""))
        st.dataframe(pd.DataFrame(t["rows"]), hide_index=True, width="stretch")


@st.cache_data(ttl=45, show_spinner=False)
def _live_prop_lines(lg, event_id, mkts):
    import live_props as LP
    return LP.live_prop_lines(lg, event_id, list(mkts), _api_key())


def _prop_read(g, rd, evs):
    """(rows, checked, note): the live props read for one game, and -- lines on -- the books' live prop lines priced
    with it (Nov 27: automatic, it was a button)."""
    import live_props as LP
    snaps = _prop_snaps(g["league"], _today.isoformat())
    if not snaps:
        return [], [], ("No pre-game prop reads saved for tonight — open a props page (Best Bets, Position Matchups) "
                        "before tip-off and they're kept.")
    rows = LP.read_props(g, rd, snaps, _summary(g["league"], g.get("event_id")))
    if not rows:
        return [], [], "No props to read for this game yet (the box score is empty or no saved reads match its players)."
    checked = []
    if with_lines and evs and g["state"] == "in":
        import intl_hoops as _I
        ev = _I.match_event(evs or [], g["home"], g["away"])
        if ev and ev.get("id"):
            try:
                lines = _live_prop_lines(g["league"], ev["id"], tuple(sorted({r["market"] for r in rows})))
                checked = LP.check_lines(rows, lines or [], g["league"], rd["share_left"])
            except Exception:                                   # noqa: BLE001 -- the props read still shows
                checked = []
    return rows, checked, None


def _props_panel(rows, checked, note):
    """Live player props for one game: stat so far, projected final, chance over the pre-game line; then the books'
    live prop lines checked against the read."""
    if note:
        st.caption(note)
        return
    rows = sorted(rows, key=lambda r: (-(r["p_over_pre"] or 0) if (r["p_over_pre"] or 0) >= 0.5
                                       else -(1 - (r["p_over_pre"] or 0))))
    st.dataframe(pd.DataFrame([{
        "Player": r["player"], "Market": r["market"], "Now": r["now"], "Projected final": round(r["projected"], 1),
        "Pre-game line": r["pre_line"],
        "Over chance": r["p_over_pre"], "Lean": "—" if r["p_over_pre"] is None else
        ("Over" if r["p_over_pre"] >= 0.5 else "Under"),
        "Playing": "normal" if abs(r["factor"] - 1) < 0.1 else ("less" if r["factor"] < 1 else "more")}
        for r in rows]), hide_index=True, width="stretch", column_config={
        "Over chance": st.column_config.NumberColumn(format="percent"),
        "Projected final": st.column_config.NumberColumn(format="%.1f")})
    if not with_lines:
        st.caption("Turn on “Check the books' live lines” above to price these at the books.")
        return
    if not checked:
        st.caption("The books aren't showing live prop lines for this game's players right now.")
        return
    st.markdown("**The books' live prop lines, checked against the read**")
    st.dataframe(pd.DataFrame([{"Signal": b["signal"], "Bet": b["bet"], "Now": b["now"],
                                "Projected final": round(b["projected"], 1), "Price": b["price"],
                                "Model chance": b["chance"], "Edge per $1": b["edge"]} for b in checked]),
                 hide_index=True, width="stretch", column_config={
                     "Price": st.column_config.NumberColumn(format="%+d"),
                     "Model chance": st.column_config.NumberColumn(format="percent"),
                     "Edge per $1": st.column_config.NumberColumn(format="%+.2f")})


def _edges_panel(items):
    """Nov 27 (owner: catch live bets): every live line across tonight's games where the model's chance beats the price
    by 5%+, biggest first, at the top of the page -- no opening game after game to find them."""
    import live_signals as LS
    found = []
    for it in items:
        g, r = it["g"], it["r"]
        if not r:
            continue
        for b in list(r["bets"]) + list(it.get("checked") or []):
            if LS.worth(b):
                found.append((g, b))
    found.sort(key=lambda x: -x[1]["edge"])
    with st.container(border=True):
        if not found:
            st.markdown("**🔥 Live edges right now:** none — the books' live lines match the model's read on every "
                        "game in progress (an edge needs the model's chance to beat the price by 5%+).")
            return
        st.markdown(f"**🔥 Live edges right now — {len(found)}**")
        _more = len(found) - 30
        found = found[:30]                                      # Nov 27: the 30 biggest; the rest are in each game
        if _more > 0:
            st.caption(f"The 30 biggest shown — {_more} more inside the games below.")
        st.dataframe(pd.DataFrame([{
            "Game": f"{g['away']} {g['away_score']:.0f} @ {g['home']} {g['home_score']:.0f}", "Clock": LG.clock_text(g),
            "Bet": b["bet"], "Type": b.get("market") or "", "Price": b["price"], "Model chance": b["chance"],
            "Edge per $1": b["edge"], "Check": "⚠ Price may be stale — check it" if b["edge"] >= LS.STALE_EDGE else ""}
            for g, b in found]), hide_index=True, width="stretch", column_config={
            "Price": st.column_config.NumberColumn(format="%+d"),
            "Model chance": st.column_config.NumberColumn(format="percent"),
            "Edge per $1": st.column_config.NumberColumn(format="%+.2f")})
        st.caption("Edge per $1 = the model's chance × the payout − 1, at the best live price we found. Live lines move "
                   "in seconds: check the price at your book before you bet. A very big edge usually means a book "
                   "hasn't moved its line yet after a run of scoring, so it may be gone by the time you look. Every "
                   "edge shown here is kept and graded — the record is at the bottom of the page.")


@st.cache_data(ttl=60, show_spinner=False)
def _signals(since_day):
    import live_signals as LS
    return LS.load(since_day)


def _keep_signals(items, done):
    """Save tonight's new 🟢 live edges (first sighting), and grade the saved ones whose game just ended."""
    import live_signals as LS
    seen = st.session_state.setdefault("_live_sig_seen", set())
    now_iso = datetime.now(pytz.utc).isoformat()
    for it in items:
        if it["r"] and it["g"]["state"] == "in":
            try:
                LS.record_new(_today.isoformat(), it["g"], list(it["r"]["bets"]) + list(it.get("checked") or []),
                              LG.clock_text(it["g"]), now_iso, seen=seen)
            except Exception:                                   # noqa: BLE001 -- never costs the page
                pass
    if not done:
        return
    try:
        ids = {str(g.get("id")) for g in done}
        rows = [r for r in _signals(_today.isoformat()) if not r.get("result") and r.get("league") == league
                and str(r.get("game_id")) in ids]
        if rows:
            by = {str(g.get("id")): g for g in done}
            if LS.grade_pending([_today.isoformat()], lambda lg, d: list(by.values()), _summary, rows=rows):
                _signals.clear()
    except Exception:                                           # noqa: BLE001
        pass


def _record_panel():
    import live_signals as LS
    rows = _signals(LS.since(_today, 30))
    rec = LS.record(rows)
    with st.expander(f"📒 How live edges have done — last 30 days: {LS.record_text(rec)}", expanded=False):
        if not rows:
            st.caption("Nothing yet: live edges are kept from Nov 27 on, the first time each one shows on this page.")
            return
        by = rec["by"]
        if by:
            st.dataframe(pd.DataFrame([{"Type": k, "Graded": d["n"], "Won": d["w"], "Lost": d["l"], "Push": d["p"],
                                        "Units": round(d["units"], 2), "Per bet": d["roi"]}
                                       for k, d in sorted(by.items())]), hide_index=True, width="stretch",
                         column_config={"Per bet": st.column_config.NumberColumn(format="percent")})
        recent = list(reversed(rows))[:40]
        st.dataframe(pd.DataFrame([{"Day": r.get("day"), "League": r.get("league"), "Game": r.get("game"),
                                    "Seen at": f"{r.get('clock')} ({r.get('score')})", "Bet": r.get("bet"),
                                    "Price": r.get("price"), "Edge per $1": r.get("edge"),
                                    "Result": {"win": "✅ Won", "loss": "❌ Lost", "push": "➖ Push",
                                               "void": "Void"}.get(r.get("result"), "⏳ Open")}
                                   for r in recent]), hide_index=True, width="stretch", column_config={
            "Price": st.column_config.NumberColumn(format="%+d"),
            "Edge per $1": st.column_config.NumberColumn(format="%+.2f")})
        st.caption(f"{rec['open']} still open. Paper record: one unit on each live edge at the price and the moment it "
                   "FIRST showed here (later, better prices don't count), graded from the final score or box score. "
                   "Every league together. Model signals only — nobody's bets.")


@st.fragment(run_every=auto)
def tennis_board():
    ms = _tennis(_today)
    picks = _picks("TENNIS")
    evs = _tennis_odds(_api_key()) if with_lines else []
    live = [m for m in ms if m["state"] == "in"]
    later = [m for m in ms if m["state"] == "pre"]
    done = [m for m in ms if m["state"] == "post"]
    st.caption(f"Updated {datetime.now(_ET):%-I:%M:%S %p} ET · {len(live)} live · {len(later)} later · {len(done)} final")
    if not live:
        st.info("No singles matches in progress on the ATP or WTA right now.")
    for m in live:
        p1 = LG.tennis_pregame(m, picks)
        r = LG.read_tennis(m, p1, LG.tennis_market(m, evs) if evs else None)
        with st.container(border=True):
            top = st.columns([3, 2])
            top[0].markdown(_tennis_card(m, r["read"] if r else None, p1), unsafe_allow_html=True)
            top[0].caption(f"{m['tournament']} · {m.get('round') or ''} · best of {m['best_of']}")
            if not r:
                top[1].caption("No pre-match chance saved for this match (the Tennis Lab only reads matches the books "
                               "price), so no live read.")
                continue
            rd = r["read"]
            fav, p = (m["p1"], rd["win_a"]) if rd["win_a"] >= 0.5 else (m["p2"], 1 - rd["win_a"])
            start = p1 if fav == m["p1"] else 1 - p1
            top[1].markdown(f"**{fav}** wins **{p:.0%}** " + _arrow_md(p, start, "the start of the match"),
                            unsafe_allow_html=True)
            st.caption(f"Pre-match: {m['p1']} {p1:.0%} · projected total {rd['total_games']:.1f} games "
                       f"({rd['games_played']} played) · fair live price {m['p1']} "
                       f"{_fair(rd['win_a'])} / {m['p2']} {_fair(1 - rd['win_a'])}")
            if r["bets"]:
                _bets_table(r["bets"])
            elif with_lines:
                st.caption("No live line from the books for this match right now.")
    if later:
        with st.expander(f"Later today ({len(later)})", expanded=not live):
            st.dataframe(pd.DataFrame([{"Start": m["detail"] or m["kickoff"], "Match": f"{m['p1']} vs {m['p2']}",
                                        "Event": m["tournament"]} for m in C.by_kickoff(later)]),
                         hide_index=True, width="stretch")
    if done:
        done = _latest_first(done)                              # Nov 12: most recent first
        res = [LG.tennis_result(m, LG.tennis_pregame(m, picks)) for m in done]
        rec = LG.record(res)
        with st.expander(f"Final ({len(done)})" + (f" · model {rec}" if rec else ""), expanded=bool(rec) and not live):
            C.hit_miss_breakdown(res, "result", "chance", key="lg_tennis_hm", title="Pre-match picks that hit and missed")
            res, done = C.show_filter(res, "result", key="lg_tennis_show", apply_to=done)
            st.dataframe(pd.DataFrame([{"Started": _when(m), "Match": f"{m['p1']} vs {m['p2']}",
                                        "Score": LG.set_text(m),
                                        "Winner": f"— ({m['void']})" if m.get("void") else
                                        (m["p1"] if m.get("winner") == 1 else m["p2"]) + (" (opp. retired)" if m.get("retired") else ""),
                                        "Model's pick": r["pick"], "Chance": r["chance"], "Result": r["result"]}
                                       for m, r in zip(done, res)]),
                         hide_index=True, width="stretch",
                         column_config={"Chance": st.column_config.NumberColumn(format="percent")})
            st.caption("Model's pick = the player the Tennis Lab favoured before the match. — = no pre-match read "
                       "(matches the books don't price).")


def _tennis_card(m, rd=None, p_start=None):
    """Nov 12: a scorecard like the books' -- flag, name, 🎾 on the server, games per set (the set in progress
    highlighted), tiebreak points as a small superscript, and each player's live win chance."""
    import html as _h
    n = max(len(m["sets1"]), 1)
    cur = len(m["sets1"]) - 1 if m["state"] == "in" else -1
    tbs = m.get("tiebreaks") or [[], []]

    def cell(v, i, tb):
        hi = "color:#f5a623;font-weight:800;" if i == cur else "opacity:.85;"
        sup = f"<sup style='font-size:10px;opacity:.7'>{int(tb)}</sup>" if tb not in (None, "") else ""
        return f"<td style='text-align:center;width:30px;{hi}'>{v}{sup}</td>"

    rows = []
    for k, (name, sets) in enumerate(((m["p1"], m["sets1"]), (m["p2"], m["sets2"]))):
        flag = (m.get("flags") or [None, None])[k]
        img = f"<img src='{_h.escape(flag)}' style='width:20px;height:14px;object-fit:cover;border-radius:2px;" \
              f"margin-right:8px;vertical-align:-2px'>" if flag else ""
        serve = " <span title='serving'>🎾</span>" if m.get("server") == k + 1 and m["state"] == "in" else ""
        won = " ✔" if m.get("winner") == k + 1 and not m.get("void") else ""
        chance = ""
        if rd is not None and m["state"] == "in":
            pk = rd["win_a"] if k == 0 else 1 - rd["win_a"]
            t = LG.trend(pk, None if p_start is None else (p_start if k == 0 else 1 - p_start))
            arrow = f" <span style='color:{t['color']};font-weight:800' title='since the start of the match: " \
                    f"{t['delta'] * 100:+.0f} pts'>{t['arrow']}</span>" if t["arrow"] else ""
            chance = f"<td style='text-align:right;padding-left:12px;font-size:12px;white-space:nowrap'>" \
                     f"<span style='opacity:.8'>{pk:.0%}</span>{arrow}</td>"
        tb = (tbs[k] if k < len(tbs) else []) + [None] * n
        cells = "".join(cell(v, i, tb[i]) for i, v in enumerate(sets)) or "<td></td>"
        rows.append(f"<tr><td style='padding:3px 10px 3px 0;font-weight:700;white-space:nowrap'>{img}"
                    f"{_h.escape(name)}{serve}{won}</td>{cells}{chance}</tr>")
    status = ("<span style='border:1px solid currentColor;border-radius:4px;padding:0 5px;font-size:11px;"
              "font-weight:700'>Live</span> " if m["state"] == "in" else "") + _h.escape(m.get("detail") or "")
    head = "<tr><td></td>" + "".join(f"<td style='text-align:center;font-size:10px;opacity:.6'>{i + 1}</td>"
                                     for i in range(n)) + ("<td style='text-align:right;font-size:10px;opacity:.6;"
                                                          "padding-left:12px'>wins</td>" if rd is not None and
                                                          m["state"] == "in" else "") + "</tr>"
    return (f"<table style='border-collapse:collapse;font-size:15px;margin-bottom:4px'>{head}{''.join(rows)}</table>"
            f"<div style='font-size:12px;opacity:.75'>{status}</div>")


def _arrow_md(now, start, since):
    """Nov 12: a green up / red down arrow for how the win chance has moved since the start."""
    t = LG.trend(now, start)
    if not t["arrow"]:
        return ""
    return (f"<span style='color:{t['color']};font-weight:800'>{t['arrow']} {t['delta'] * 100:+.0f}</span>"
            f"<span style='opacity:.6;font-size:12px'> pts since {since}</span>")


def _when(x):
    """The start time in New York (the feeds don't say when a match ended)."""
    d = C._kick_dt(x.get("kickoff"))
    return d.strftime("%a %b %-d, %-I:%M %p") if d else "—"


def _latest_first(items):
    return list(reversed(C.by_kickoff(items)))


def _fair(p):
    if p <= 0.0001 or p >= 0.9999:
        return "—"
    return f"{-round(100 * p / (1 - p)):+d}" if p >= 0.5 else f"{round(100 * (1 - p) / p):+d}"


_PROP_LEAGUES = ("NBA", "NCAAMB", "WNBA", "NHL", "NFL", "NCAAF")


@st.fragment(run_every=auto)
def board():
    gs = _games(league, _today)
    picks = _picks(league)
    evs = _odds(league, _api_key()) if with_lines else []
    live = [g for g in gs if g["state"] == "in"]
    later = [g for g in gs if g["state"] == "pre"]
    done = [g for g in gs if g["state"] == "post"]
    import intl_picks as IP
    import intl_hoops as I
    import live_lead as LL
    football = league in ("NFL", "NCAAF")

    def _pre(g):
        # Nov 12: football uses the books' pre-game line (it beat our football models on past games); everything else
        # uses the Game Lab's projection, or the books' line when the Game Lab has none
        pre = None if football else LG.pregame_for(g, picks)
        return pre if pre is not None else _books_pregame(league, g.get("event_id"))

    def _start_home(g, pre):
        try:
            return LM.project(g["league"], float(pre["model_margin"]), float(pre["model_total"]), 0, 0, 1,
                              LM.cfg(g["league"])["minutes"])["win_home"]
        except Exception:                                       # noqa: BLE001
            return None

    # Nov 16: read every live game first, then lead with a summary and the closest game (it was start order)
    reads = []
    for g in C.by_kickoff(live):
        pre = _pre(g)
        mk = None
        if evs:
            ev = I.match_event(evs, g["home"], g["away"])
            if ev:
                mk = IP.market(ev, ev.get("home_team"), ev.get("away_team"))
                if not I.same_team(ev.get("home_team"), g["home"]):  # the feed lists the teams the other way round
                    mk = None
        r = LG.read_game(g, pre, mk)
        wh = r["read"]["win_home"] if r else None
        props = ([], [], None)
        if r and league in _PROP_LEAGUES:
            try:
                props = _prop_read(g, r["read"], evs)
            except Exception:                                   # noqa: BLE001
                props = ([], [], "The live props read couldn't load just now.")
        reads.append({"g": g, "pre": pre, "r": r, "win_home": wh, "start_home": _start_home(g, pre) if r else None,
                      "label": f"{g['away']} @ {g['home']}", "home": g["home"], "away": g["away"],
                      "leader": None if wh is None else (g["home"] if wh >= 0.5 else g["away"]),
                      "props": props, "checked": props[1]})
    st.caption(f"Updated {datetime.now(_ET):%-I:%M:%S %p} ET")
    C.kpi_row(LL.summary(reads, len(later), len(done)))
    if not live:
        st.info("No games in progress right now." + (" What's next is below." if later else ""))
    elif with_lines:
        _edges_panel(reads)
    _keep_signals(reads, done)
    ordered = LL.order_live(reads)
    for n_card, it in enumerate(ordered):
        g, pre, r = it["g"], it["pre"], it["r"]
        with st.container(border=True):
            top = st.columns([3, 2])
            poss = ""
            if g.get("possession"):
                poss = f" · 🏈 {g['home'] if g['possession'] == 'home' else g['away']} ball" + \
                    (f", {g['down_text']}" if g.get("down_text") else "")
            _tag = ("⚖️ Closest game · " if n_card == 0 and len(ordered) > 1 and it["win_home"] is not None
                    and LL.lead_chance(it["win_home"]) < LL.CLOSE else "")
            top[0].markdown(f"{_tag}**{g['away']} {g['away_score']:.0f} @ {g['home']} {g['home_score']:.0f}** · "
                            f"{LG.clock_text(g)}{poss}")
            if not r:
                top[1].caption("No pre-game projection or line for this game, so no live read.")
                continue
            rd = r["read"]
            fav, p = (g["home"], rd["win_home"]) if rd["win_home"] >= 0.5 else (g["away"], 1 - rd["win_home"])
            start_home = it["start_home"]
            top[1].markdown(f"**{fav}** wins **{p:.0%}** " + ("" if start_home is None else _arrow_md(
                p, start_home if fav == g["home"] else 1 - start_home, "tip-off / kickoff")), unsafe_allow_html=True)
            fh = (rd["total"] + rd["margin"]) / 2
            fa = (rd["total"] - rd["margin"]) / 2
            st.caption(f"Projected final: {g['away']} {fa:.0f} – {g['home']} {fh:.0f} · fair live spread "
                       f"{g['home']} {r['fair_spread']:+g} · fair live total {r['fair_total']:g} · "
                       f"pre-game ({'books' if pre.get('source') == 'books' else 'Game Lab'}): {g['home']} "
                       f"{-float(pre['model_margin']):+.1f}, total {float(pre['model_total']):.1f} · "
                       f"{rd['minutes_left']:.1f} min left")
            if r["bets"]:
                _bets_table(r["bets"])
            elif with_lines:
                st.caption("No live line from the books for this game right now.")
            if league in _PROP_LEAGUES:
                _pr = it.get("props") or ([], [], None)
                _n = sum(1 for b in _pr[1] if b.get("edge") is not None and b["edge"] >= LG.MIN_EDGE)
                with st.expander("🧍 Live player props" + (f" · 🟢 {_n} worth a look" if _n else "")):
                    _props_panel(*_pr)
                with st.expander("📋 Live box score"):
                    _box_panel(g)
    if later:
        with st.expander(f"Next up ({len(later)} still to start)", expanded=not live):
            st.dataframe(pd.DataFrame(LL.next_up(
                C.by_kickoff(later), _pre, _start_home, lambda g: C._kick_dt(g.get("kickoff")), datetime.now(_ET))),
                hide_index=True, width="stretch")
            st.caption("Pre-game favourite and projected score (away–home) come from "
                       + ("the books' line" if football else "the Game Lab's projection")
                       + f", for the next {LL.NEXT_N} games. — = no pre-game read yet.")
    if done:
        def _pre_done(g):
            p = None if football else LG.pregame_for(g, picks)
            return p if p is not None or not football else _books_pregame(league, g.get("event_id"))
        done = _latest_first(done)                              # Nov 12: most recent first
        res = [LG.game_result(g, _pre_done(g)) for g in done]
        rec = LG.record(res)
        with st.expander(f"Final ({len(done)})" + (f" · model {rec}" if rec else ""), expanded=bool(rec) and not live):
            C.hit_miss_breakdown(res, "result", "chance", key=f"lg_{league}_hm", title="Pre-game picks that hit and missed")
            res, done = C.show_filter(res, "result", key=f"lg_{league}_show", apply_to=done)
            st.dataframe(pd.DataFrame([{"Started": _when(g), "Game": f"{g['away']} @ {g['home']}",
                                        "Final": f"{g['away_score']:.0f}–{g['home_score']:.0f}",
                                        "Pre-game pick": r["pick"], "Chance": r["chance"], "Result": r["result"]}
                                       for g, r in zip(done, res)]),
                         hide_index=True, width="stretch",
                         column_config={"Chance": st.column_config.NumberColumn(format="percent")})
            st.caption("Pre-game pick = the team the " + ("books favoured (football starts from the books' line)"
                                                           if football else "Game Lab favoured before tip-off")
                       + " to win. — = no pre-game read saved for that game.")


@st.cache_data(ttl=25, show_spinner=False)
def _soccer_day(day):
    """Every Soccer Lab league's matches today (one ESPN request each, in parallel)."""
    from concurrent.futures import ThreadPoolExecutor
    import soccer_data as SD
    import soccer_live as SL
    with ThreadPoolExecutor(12) as ex:
        import soccer_picks as SPK
        keys = SPK.slate_leagues() or list(SD.LEAGUES)              # Nov 13: only leagues playing today/tomorrow
        chunks = list(ex.map(lambda k: SL.games(k, day), keys))
    return [g for c in chunks for g in c]


@st.cache_data(ttl=600, show_spinner=False)
def _soccer_rec(lg, home, away, kickoff):
    """The Soccer Lab's saved record for a match (None when it wasn't captured)."""
    import soccer_live as SL
    return SL.pregame_for({"home": home, "away": away, "kickoff": kickoff}, _picks(lg))


@st.cache_data(ttl=600, show_spinner=False)
def _soccer_pre(lg, home, away, kickoff):
    """The match's pre-game goal rates (from the sharp line when the Soccer Lab saved one)."""
    import soccer_live as SL
    p = SL.pregame_for({"home": home, "away": away, "kickoff": kickoff}, _picks(lg))
    if not p:
        return None, None, None
    r = SL.pregame_rates(p)
    return r, p.get("line_total"), ("sharp line" if p.get("mkt_home") is not None else "goals model")


@st.fragment(run_every=auto)
def soccer_board():
    """Nov 13: live soccer across every Soccer Lab league."""
    import soccer_data as SD
    import soccer_live as SL
    gs = _soccer_day(_today)
    live = [g for g in gs if g["state"] == "in"]
    later = [g for g in gs if g["state"] == "pre"]
    done = [g for g in gs if g["state"] == "post"]
    st.caption(f"Updated {datetime.now(_ET):%-I:%M:%S %p} ET · {len(live)} live · {len(later)} later today · "
               f"{len(done)} final — leagues with a match today or tomorrow")
    if not live:
        st.info("No matches in progress in the Soccer Lab's leagues right now.")
    for g in sorted(live, key=lambda x: (SD.LEAGUES[x["league"]]["group"], SD.LEAGUES[x["league"]]["title"])):
        pre, line, src = _soccer_pre(g["league"], g["home"], g["away"], g["kickoff"])
        with st.container(border=True):
            top = st.columns([3, 2])
            reds = (" 🟥" * g["red_home"]) + " vs" + (" 🟥" * g["red_away"]) if g["red_home"] or g["red_away"] else " vs"
            top[0].markdown(f"**{g['home']} {g['home_score']} – {g['away_score']} {g['away']}**  ·  "
                            f"{g['detail'] or str(int(g['minute'])) + chr(39)}")
            top[0].caption(SD.LEAGUES[g["league"]]["title"] + ("" if reds == " vs" else f" · red cards: home{reds} away"))
            if not pre:
                top[1].caption("No pre-match read saved for this match (the Soccer Lab hadn't priced it), so no live "
                               "read.")
                continue
            rd = SL.read(g, pre, line)
            top[1].markdown(f"**{g['home']}** {rd['p_home']:.0%} · **Draw** {rd['p_draw']:.0%} · "
                            f"**{g['away']}** {rd['p_away']:.0%}")
            bits = [f"Projected final {rd['proj_home']:.1f} – {rd['proj_away']:.1f}",
                    f"fair live price {g['home']} {SL.fair(rd['p_home'])} / Draw {SL.fair(rd['p_draw'])} / "
                    f"{g['away']} {SL.fair(rd['p_away'])}"]
            if rd.get("line") is not None:
                bits.append(f"over {rd['line']:g}: {rd['p_over']:.0%}")
            bits.append(f"next goal {g['home']} {rd['next_home']:.0%} · {g['away']} {rd['next_away']:.0%} · "
                        f"none {rd['no_more']:.0%}")
            st.caption(" · ".join(bits) + f"  (pre-match from the {src})")
    if later:
        with st.expander(f"Later today ({len(later)})", expanded=not live):
            import soccer_picks as SPK
            rows = []
            for x in sorted(later, key=lambda x: str(x.get("kickoff"))):
                rec = _soccer_rec(x["league"], x["home"], x["away"], x["kickoff"])
                rows.append({"Kickoff (ET)": _when(x), "Match": f"{x['home']} vs {x['away']}",
                             "League": SD.LEAGUES[x["league"]]["title"],
                             "Projected winner": SPK.projected(rec) if rec else "not in the Soccer Lab",
                             "Market favorite": SPK.market(rec) if rec else "—",
                             "Best US H / D / A": "—" if not rec or rec.get("best_home") is None else
                             f"{rec['best_home']:+d} / {rec['best_draw']:+d} / {rec['best_away']:+d}"})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.caption("Projected winner = the goals model's most likely result (and rounded score); Market favorite = "
                       "Pinnacle's no-vig chance. The model lost to the market in testing — tracking only.")
    if done:
        with st.expander(f"Final ({len(done)})"):
            import soccer_picks as SPK
            rows = []
            for x in _latest_first(done):
                rec = _soccer_rec(x["league"], x["home"], x["away"], x["kickoff"])
                res = "home" if x["home_score"] > x["away_score"] else ("away" if x["away_score"] > x["home_score"] else "draw")
                pick = None
                if rec and rec.get("p_home") is not None:
                    pr = {"home": rec["p_home"], "draw": rec["p_draw"], "away": rec["p_away"]}
                    pick = max(pr, key=pr.get)
                rows.append({"Kickoff (ET)": _when(x), "Match": f"{x['home']} vs {x['away']}",
                             "Score": f"{x['home_score']}–{x['away_score']}",
                             "League": SD.LEAGUES[x["league"]]["title"],
                             "Projected winner": SPK.projected(rec) if rec else "—",
                             "Model": "—" if pick is None else ("✅ right" if pick == res else "❌ wrong")})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


if league == "TENNIS":
    tennis_board()
elif league == "SOCCER":
    soccer_board()
else:
    board()
    _record_panel()
st.caption(
    "**Soccer** starts from each side's expected goals backed out of the sharp pre-match line (the goals model's own "
    "when there's none), scales them to the time left, adjusts for red cards, and adds the score so far. "
    "**Tennis** works from the games in each set and who's serving (ESPN's live feed doesn't carry the point score, "
    "so 15/30/40 isn't shown): each player's chance "
    "of winning a point on serve is backed out of the pre-match chance, then the point → game → set → match odds run "
    "from the current score. **Football** starts from the books' pre-game line and counts the drive in progress "
    "(field position). **Player props:** stat so far + his pre-game projection for the rest of the game, adjusted "
    "for how much he's actually playing. **Basketball / hockey:** the projected final is the score now plus the rest of the game at the pre-game projection's "
    "scoring rate and edge (on past games, tonight's pace added nothing beyond that); the leader's cushion is only as "
    "safe as the time left allows. **Tracking only** while it's being proven — a live line marked 🟢 is one the model prices better than the "
    "book, not a sure thing. Live lines move fast; check the price in your app before you bet.")
