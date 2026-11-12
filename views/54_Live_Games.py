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

_SPORT_LEAGUES = {"NBA": ["NBA"], "NCAAMB": ["NCAAMB"], "NHL": ["NHL"], "WNBA": ["WNBA"],
                  "INTL": ["EUROLEAGUE", "EUROCUP", "NBL"]}
_key = sports.active_key()
_choices = _SPORT_LEAGUES.get(_key)
if not _choices:
    st.info("Live Games covers basketball (NBA, WNBA, college, EuroLeague, EuroCup, NBL) and the NHL — pick one of "
            "those sports at the top.")
    st.stop()
league = _choices[0] if len(_choices) == 1 else st.radio(
    "League", _choices, horizontal=True, format_func=lambda k: LG.TITLE[k], key="live_league")

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
with_lines = c2.toggle("Show the books' live lines (3 Odds API credits a refresh)", value=False, key="live_lines",
                       disabled=league not in ("NBA", "NCAAMB", "NHL", "WNBA", "EUROLEAGUE", "NBL"))


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
    for g in C.by_kickoff(live):
        pre = LG.pregame_for(g, picks)
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
            top[0].markdown(f"**{g['away']} {g['away_score']:.0f} @ {g['home']} {g['home_score']:.0f}** · "
                            f"{LG.clock_text(g)}")
            if not r:
                top[1].caption("No pre-game projection saved for this game, so no live read.")
                continue
            rd = r["read"]
            fav, p = (g["home"], rd["win_home"]) if rd["win_home"] >= 0.5 else (g["away"], 1 - rd["win_home"])
            top[1].markdown(f"**{fav}** wins **{p:.0%}**")
            fh = (rd["total"] + rd["margin"]) / 2
            fa = (rd["total"] - rd["margin"]) / 2
            st.caption(f"Projected final: {g['away']} {fa:.0f} – {g['home']} {fh:.0f} · fair live spread "
                       f"{g['home']} {r['fair_spread']:+g} · fair live total {r['fair_total']:g} · "
                       f"pre-game: {g['home']} {-float(pre['model_margin']):+.1f}, total {float(pre['model_total']):.1f} · "
                       f"{rd['minutes_left']:.1f} min left")
            if r["bets"]:
                df = pd.DataFrame([{"Signal": b["signal"], "Bet": b["bet"], "Price": b["price"],
                                    "Model chance": b["chance"], "Edge per $1": b["edge"]} for b in r["bets"]])
                st.dataframe(df, hide_index=True, width="stretch", column_config={
                    "Price": st.column_config.NumberColumn(format="%+d"),
                    "Model chance": st.column_config.NumberColumn(format="percent"),
                    "Edge per $1": st.column_config.NumberColumn(format="%+.2f")})
            elif with_lines:
                st.caption("No live line from the books for this game right now.")
    if later:
        with st.expander(f"Later today ({len(later)})"):
            st.dataframe(pd.DataFrame([{"Start": g["detail"] or g["kickoff"], "Game": f"{g['away']} @ {g['home']}"}
                                       for g in C.by_kickoff(later)]), hide_index=True, width="stretch")
    if done:
        with st.expander(f"Final ({len(done)})"):
            st.dataframe(pd.DataFrame([{"Game": f"{g['away']} @ {g['home']}",
                                        "Final": f"{g['away_score']:.0f}–{g['home_score']:.0f}"} for g in done]),
                         hide_index=True, width="stretch")


board()
st.caption(
    "**How it works:** the projected final is the score now plus the rest of the game at the pre-game projection's "
    "scoring rate and edge (on past games, tonight's pace added nothing beyond that); the leader's cushion is only as "
    "safe as the time left allows. **Tracking only** while it's being proven — a live line marked 🟢 is one the model prices better than the "
    "book, not a sure thing. Live lines move fast; check the price in your app before you bet.")
