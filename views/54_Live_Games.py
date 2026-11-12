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
import sports

C.base_css()
C.page_header("🔴", "Live Games",
              "Games in progress: who's likely to win from here, the projected final score, and the fair live spread "
              "and total — built from the pre-game projection and how the game is actually going.")

_SPORT_LEAGUES = {"NBA": ["NBA"], "NCAAMB": ["NCAAMB"], "NHL": ["NHL"], "WNBA": ["WNBA"], "NFL": ["NFL"],
                  "NCAAF": ["NCAAF"],
                  "INTL": ["EUROLEAGUE", "EUROCUP", "NBL"], "TENNIS": ["TENNIS"]}
_key = sports.active_key()
_choices = _SPORT_LEAGUES.get(_key)
if not _choices:
    st.info("Live Games covers basketball (NBA, WNBA, college, EuroLeague, EuroCup, NBL), football (NFL, college), "
            "the NHL and tennis — pick one of those sports at the top.")
    st.stop()
league = _choices[0] if len(_choices) == 1 else st.radio(
    "League", _choices, horizontal=True, format_func=lambda k: LG.TITLE.get(k, k), key="live_league")

_ET = pytz.timezone("US/Eastern")
_today = datetime.now(_ET).date()


@st.cache_data(ttl=45, show_spinner=False)
def _games(lg, day):
    return LG.games(lg, day)


@st.cache_data(ttl=600, show_spinner=False)
def _picks(lg):
    try:
        import model_store as MS
        return MS.load_game_picks(lg)
    except Exception:                                           # noqa: BLE001
        return []


@st.cache_data(ttl=60, show_spinner=False)
def _odds(lg, api_key):
    return LG.live_odds(lg, api_key)


def _api_key():
    try:
        import best_bets_data as BBD
        return BBD.get_odds_api_key()
    except Exception:                                           # noqa: BLE001
        return None


c1, c2 = st.columns([1, 1])
auto = c1.toggle("Auto-refresh every minute", value=False, key="live_auto")
with_lines = c2.toggle("Show the books' live lines (3 Odds API credits a refresh; tennis 2 per tournament)",
                       value=False, key="live_lines",
                       disabled=league not in ("NBA", "NCAAMB", "NHL", "WNBA", "EUROLEAGUE", "NBL", "TENNIS", "NFL",
                                               "NCAAF"))


@st.cache_data(ttl=45, show_spinner=False)
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


@st.cache_data(ttl=45, show_spinner=False)
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


def _props_panel(g, rd, evs):
    """Live player props for one game: stat so far, projected final, chance over the pre-game line; the books' live
    prop lines on request."""
    import live_props as LP
    snaps = _prop_snaps(g["league"], _today.isoformat())
    if not snaps:
        st.caption("No pre-game prop reads saved for tonight — open a props page (Best Bets, Position Matchups) "
                   "before tip-off and they're kept.")
        return
    summ = _summary(g["league"], g.get("event_id"))
    rows = LP.read_props(g, rd, snaps, summ)
    if not rows:
        st.caption("No props to read for this game yet (the box score is empty or no saved reads match its players).")
        return
    rows.sort(key=lambda r: (-(r["p_over_pre"] or 0) if (r["p_over_pre"] or 0) >= 0.5 else -(1 - (r["p_over_pre"] or 0))))
    st.dataframe(pd.DataFrame([{
        "Player": r["player"], "Market": r["market"], "Now": r["now"], "Projected final": round(r["projected"], 1),
        "Pre-game line": r["pre_line"],
        "Over chance": r["p_over_pre"], "Lean": "—" if r["p_over_pre"] is None else
        ("Over" if r["p_over_pre"] >= 0.5 else "Under"),
        "Playing": "normal" if abs(r["factor"] - 1) < 0.1 else ("less" if r["factor"] < 1 else "more")}
        for r in rows]), hide_index=True, width="stretch", column_config={
        "Over chance": st.column_config.NumberColumn(format="percent"),
        "Projected final": st.column_config.NumberColumn(format="%.1f")})
    key = f"lp_{g['league']}_{g['id']}"
    mkts = sorted({r["market"] for r in rows})
    if st.button(f"📈 Check the books' live prop lines for this game (~{len(mkts)} credits)", key=key):
        import intl_hoops as _I
        import odds_api as O
        import sports as _S
        api = _api_key()
        ev_list = evs or (O.fetch_events_all(api, sport=_S.get(g["league"]).odds_sport_key) if api else [])
        ev = _I.match_event(ev_list or [], g["home"], g["away"])
        lines = LP.live_prop_lines(g["league"], (ev or {}).get("id"), mkts, api) if ev else []
        checked = LP.check_lines(rows, lines, g["league"], rd["share_left"])
        st.session_state[key + "_res"] = checked if checked else "none"
    res = st.session_state.get(key + "_res")
    if res == "none":
        st.caption("The books aren't showing live prop lines for this game right now.")
    elif res:
        st.dataframe(pd.DataFrame([{"Signal": b["signal"], "Bet": b["bet"], "Now": b["now"],
                                    "Projected final": round(b["projected"], 1), "Price": b["price"],
                                    "Model chance": b["chance"], "Edge per $1": b["edge"]} for b in res]),
                     hide_index=True, width="stretch", column_config={
                         "Price": st.column_config.NumberColumn(format="%+d"),
                         "Model chance": st.column_config.NumberColumn(format="percent"),
                         "Edge per $1": st.column_config.NumberColumn(format="%+.2f")})


@st.fragment(run_every=60 if auto else None)
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
            top[0].markdown(f"**{m['p1']} vs {m['p2']}** · {LG.set_text(m)}")
            top[0].caption(f"{m['tournament']} · {m.get('round') or ''} · best of {m['best_of']}")
            if not r:
                top[1].caption("No pre-match chance saved for this match (the Tennis Lab only reads matches the books "
                               "price), so no live read.")
                continue
            rd = r["read"]
            fav, p = (m["p1"], rd["win_a"]) if rd["win_a"] >= 0.5 else (m["p2"], 1 - rd["win_a"])
            top[1].markdown(f"**{fav}** wins **{p:.0%}**")
            st.caption(f"Pre-match: {m['p1']} {p1:.0%} · projected total {rd['total_games']:.1f} games "
                       f"({rd['games_played']} played) · fair live price {m['p1']} "
                       f"{_fair(rd['win_a'])} / {m['p2']} {_fair(1 - rd['win_a'])}")
            if r["bets"]:
                _bets_table(r["bets"])
            elif with_lines:
                st.caption("No live line from the books for this match right now.")
    if later:
        with st.expander(f"Later today ({len(later)})"):
            st.dataframe(pd.DataFrame([{"Start": m["detail"] or m["kickoff"], "Match": f"{m['p1']} vs {m['p2']}",
                                        "Event": m["tournament"]} for m in C.by_kickoff(later)]),
                         hide_index=True, width="stretch")
    if done:
        with st.expander(f"Final ({len(done)})"):
            st.dataframe(pd.DataFrame([{"Match": f"{m['p1']} vs {m['p2']}", "Score": LG.set_text(m),
                                        "Winner": m["p1"] if m.get("winner") == 1 else m["p2"]} for m in done]),
                         hide_index=True, width="stretch")


def _fair(p):
    if p <= 0.0001 or p >= 0.9999:
        return "—"
    return f"{-round(100 * p / (1 - p)):+d}" if p >= 0.5 else f"{round(100 * (1 - p) / p):+d}"


@st.fragment(run_every=60 if auto else None)
def board():
    gs = _games(league, _today)
    picks = _picks(league)
    evs = _odds(league, _api_key()) if with_lines else []
    live = [g for g in gs if g["state"] == "in"]
    later = [g for g in gs if g["state"] == "pre"]
    done = [g for g in gs if g["state"] == "post"]
    st.caption(f"Updated {datetime.now(_ET):%-I:%M:%S %p} ET · {len(live)} live · {len(later)} later · {len(done)} final")
    if not live:
        st.info("No games in progress right now." + (f" Next: {C.by_kickoff(later)[0]['away']} @ "
                                                     f"{C.by_kickoff(later)[0]['home']}." if later else ""))
    import intl_picks as IP
    import intl_hoops as I
    football = league in ("NFL", "NCAAF")
    for g in C.by_kickoff(live):
        # Nov 12: football uses the books' pre-game line (it beat our football models on past games); everything else
        # uses the Game Lab's projection, or the books' line when the Game Lab has none
        pre = None if football else LG.pregame_for(g, picks)
        if pre is None:
            pre = _books_pregame(league, g.get("event_id"))
        mk = None
        if evs:
            ev = I.match_event(evs, g["home"], g["away"])
            if ev:
                mk = IP.market(ev, ev.get("home_team"), ev.get("away_team"))
                if not I.same_team(ev.get("home_team"), g["home"]):  # the feed lists the teams the other way round
                    mk = None
        r = LG.read_game(g, pre, mk)
        with st.container(border=True):
            top = st.columns([3, 2])
            poss = ""
            if g.get("possession"):
                poss = f" · 🏈 {g['home'] if g['possession'] == 'home' else g['away']} ball" + \
                    (f", {g['down_text']}" if g.get("down_text") else "")
            top[0].markdown(f"**{g['away']} {g['away_score']:.0f} @ {g['home']} {g['home_score']:.0f}** · "
                            f"{LG.clock_text(g)}{poss}")
            if not r:
                top[1].caption("No pre-game projection or line for this game, so no live read.")
                continue
            rd = r["read"]
            fav, p = (g["home"], rd["win_home"]) if rd["win_home"] >= 0.5 else (g["away"], 1 - rd["win_home"])
            top[1].markdown(f"**{fav}** wins **{p:.0%}**")
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
            if league in ("NBA", "NCAAMB", "WNBA", "NHL", "NFL", "NCAAF"):
                with st.expander("🧍 Live player props"):
                    _props_panel(g, rd, evs)
    if later:
        with st.expander(f"Later today ({len(later)})"):
            st.dataframe(pd.DataFrame([{"Start": g["detail"] or g["kickoff"], "Game": f"{g['away']} @ {g['home']}"}
                                       for g in C.by_kickoff(later)]), hide_index=True, width="stretch")
    if done:
        with st.expander(f"Final ({len(done)})"):
            st.dataframe(pd.DataFrame([{"Game": f"{g['away']} @ {g['home']}",
                                        "Final": f"{g['away_score']:.0f}–{g['home_score']:.0f}"} for g in done]),
                         hide_index=True, width="stretch")


if league == "TENNIS":
    tennis_board()
else:
    board()
st.caption(
    "**Tennis** works from the games in each set (the live feed has no point score or server): each player's chance "
    "of winning a point on serve is backed out of the pre-match chance, then the point → game → set → match odds run "
    "from the current score. **Football** starts from the books' pre-game line and counts the drive in progress "
    "(field position). **Player props:** stat so far + his pre-game projection for the rest of the game, adjusted "
    "for how much he's actually playing. **Basketball / hockey:** the projected final is the score now plus the rest of the game at the pre-game projection's "
    "scoring rate and edge (on past games, tonight's pace added nothing beyond that); the leader's cushion is only as "
    "safe as the time left allows. **Tracking only** while it's being proven — a live line marked 🟢 is one the model prices better than the "
    "book, not a sure thing. Live lines move fast; check the price in your app before you bet.")
