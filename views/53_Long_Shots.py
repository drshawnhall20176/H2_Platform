"""
Long Shots (Nov 10) — alternate-line value: the books' price on "8+ assists", "30+ points"... vs the model's HONEST
chance of it. Owner request after Jeremiah Fears' 8+ assists hit at +1500 (the model had projected 6.0 vs a 4.5 line).
Logic and the tail-honesty table: long_shots.py. NBA for now (the market the tail test covers).
"""
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

import best_bets_data as BBD
import components as C
import log_ui as LU
import long_shots as LS
import odds_api as O
import props_engine as PE
import sports

_active = sports.active()
C.base_css()
C.page_header("💎", "Long Shots", "Alternate lines (8+ assists, 30+ points…) where the book's price is longer than the "
                                 "model's honest chance — the Fears-at-+1500 kind of bet, found before tip-off.")
if not sports.require_sport(["NBA"], "Long Shots"):
    st.stop()

eastern = pytz.timezone("US/Eastern")
date_str = datetime.now(eastern).strftime("%Y-%m-%d")
api_key = BBD.get_odds_api_key()
if not api_key:
    st.info("Needs the Odds API key (ODDS_API_KEY) — alternate lines come from the books.")
    st.stop()
book = BBD.render_book_selector(key_prefix="longshots", date_str=date_str)


@st.cache_data(ttl=900, show_spinner=False)
def _slate(sport_key, day, bk):
    rows, meta = sports.get(sport_key).engine.build_slate(day)
    offers = BBD.fetch_generic_offers(sport_key, day, api_key)
    reads = BBD.slate_reads_for(sport_key, day, meta, offers, bk) or {}
    return meta, reads


with st.spinner("Loading tonight's model reads…"):
    meta, reads = _slate(_active.key, date_str, book)
if not meta or not reads:
    st.info("No NBA games with posted player lines yet today.")
    st.stop()

games = {m["label"]: m for m in meta}
pick = st.selectbox("Game", list(games.keys()), key="longshots_game")
g = games.get(pick) or next(iter(games.values()))
store = st.session_state.setdefault("longshots_quotes", {})
if st.button(f"📈 Load alternate lines for {g['label']}  (~{len(LS.ALT_TO_MAIN)} Odds API credits)", key="ls_load"):
    try:
        import book_menu as BM
        import position_lines as PL
        ev = PL.match_event(O.fetch_events_all(api_key, sport=_active.odds_sport_key), g["home_name"], g["away_name"])
        if not ev:
            store[g["label"]] = {"error": "The books haven't posted this game yet."}
        else:
            res = BM.fetch_menu(api_key, _active.odds_sport_key, [ev["id"]], list(LS.ALT_TO_MAIN), book or O.DEFAULT_BOOK,
                                feed_by_event={ev["id"]: ev.get("_feed") or _active.odds_sport_key})
            store[g["label"]] = {"quotes": res.get("quotes") or [], "remaining": res.get("remaining"),
                                 "unavailable": res.get("unavailable") or []}
    except Exception as exc:                                    # noqa: BLE001
        store[g["label"]] = {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}

got = store.get(g["label"])
if not got:
    st.caption("Press the button to load this game's alternate lines at your selected book.")
    st.stop()
if got.get("error"):
    st.warning(got["error"])
    st.stop()

rows = LS.finder({k: v for k, v in reads.items() if v.get("game") == g["label"]}, got["quotes"], PE.norm_name,
                 PE.prob_over)
if got.get("remaining"):
    st.caption(f"Odds API credits left: {got['remaining']}")
value = [r for r in rows if r["EV per $1"] > 0]
st.markdown(f"**{len(value)} rung(s) priced longer than the honest chance** · {len(rows)} checked")
if not rows:
    st.info("No alternate rungs to compare for this game at this book (or the model has no read on these players).")
    st.stop()
show = value or rows[:15]
df = pd.DataFrame([{k: r[k] for k in ("Player", "Bet", "Price", "Book says", "Honest chance", "Model raw", "Edge",
                                       "EV per $1", "Projection", "Main line", "Flags")} for r in show])
sel = LU.selectable(df, "ls_sel", hide_index=True, width="stretch", column_config={
    "Price": st.column_config.NumberColumn(format="%+d"),
    "Book says": st.column_config.NumberColumn(format="percent"),
    "Honest chance": st.column_config.NumberColumn(format="percent"),
    "Model raw": st.column_config.NumberColumn(format="percent"),
    "Edge": st.column_config.NumberColumn(format="percent"),
    "EV per $1": st.column_config.NumberColumn(format="%+.2f"),
    "Projection": st.column_config.NumberColumn(format="%.1f")})
LU.panel(LU.picked(show, sel), "ls_log", date_str, tag="long-shot")
st.caption(
    "**Honest chance** = the model's chance of the rung, corrected by how its long-shot chances have actually landed "
    "(walk-forward test on ~2,750 games per market: it overstates 15–55% rungs and understates under-5% ones). "
    "**Book says** = the chance the price implies (vig included, so it's a bit high). **EV per $1** = what $1 returns "
    "on average at the honest chance — +1.00 means it should double over many bets. These hit rarely: most nights "
    "a long shot loses, so keep stakes small and flat (a few dollars), never chase. Rows marked *check news* have a "
    "projection far from the book's main line — the book may know about a role or minutes change.")
