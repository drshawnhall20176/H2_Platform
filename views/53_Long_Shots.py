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



@st.cache_data(ttl=1800, show_spinner=False)
def _past_night(sport_key, day_s):
    import model_store as MS
    import postgame as PG
    snaps = MS.load_snapshots(sport_key, [day_s])
    if not snaps:
        return [], {}
    res = PG.fetch_results(sport_key, day_s, sorted({(s["team"], s["opp"]) for s in snaps}))
    try:
        _rows, meta = sports.get(sport_key).engine.build_slate(day_s)
    except Exception:                                           # noqa: BLE001
        meta = []
    return PG.grade(snaps, res), {m["label"]: m for m in meta or []}


def _historical_alts(g, bk):
    """That night's alternate prices from the Odds API history (paid plans only; 10 credits per market)."""
    import book_menu as BM
    import position_lines as PL
    noon = eastern.localize(datetime.combine(day, datetime.min.time()).replace(hour=12))
    evs, _h = O.fetch_historical_events(api_key, noon.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                        sport=_active.odds_sport_key)
    evs = evs.get("data") if isinstance(evs, dict) else evs
    ev = PL.match_event(evs or [], g.get("home_name"), g.get("away_name"))
    if not ev:
        return {"error": "The Odds API history has no event for this game."}
    quotes, left = [], None
    for mk in LS.ALT_TO_MAIN:
        try:
            js, hdr = O.fetch_historical_event_props(ev["id"], api_key, [mk], ev.get("commence_time"),
                                                     sport=_active.odds_sport_key)
        except O.OddsAPIError as exc:
            if "401" in str(exc) or "403" in str(exc):
                return {"error": "Past prices need a paid Odds API plan (the history endpoint refused this key)."}
            continue
        left = hdr.get("remaining") or left
        quotes += BM.parse_menu_event((js or {}).get("data") or {}, bk or O.DEFAULT_BOOK)
    try:
        import model_store as MS
        MS.save_odds(_active.key, date_str, g.get("home_name") or "", g.get("away_name") or "", ALT_ARCHIVE,
                     {"offers": quotes}, None)
    except Exception:                                           # noqa: BLE001
        pass
    return {"quotes": quotes, "remaining": left}


def _look_back():
    with st.spinner("Loading that night's model reads and box scores…"):
        graded, meta = _past_night(_active.key, date_str)
    if not graded:
        st.info("No saved model reads for this date. They're kept whenever a props page (Best Bets, Edge Board, "
                "Position Matchups, Long Shots…) is opened before tip-off.")
        return
    labels = sorted({s.get("game") for s in graded if s.get("game")})
    pick = st.selectbox("Game", ["All games"] + labels, key="longshots_past_game")
    rows_in = graded if pick == "All games" else [s for s in graded if s.get("game") == pick]
    quotes = []
    if pick != "All games":
        import model_store as MS
        g = meta.get(pick) or {}
        saved = MS.load_odds(_active.key, date_str, g.get("home_name") or "", g.get("away_name") or "", ALT_ARCHIVE)
        if saved and saved.get("offers"):
            quotes = saved["offers"]
            st.caption("Alternate prices: saved from when they were loaded before tip-off.")
        elif api_key and g and st.button(f"📈 Load that night's alternate prices (~{10 * len(LS.ALT_TO_MAIN)} credits, "
                                         "paid Odds API plan only)", key="ls_hist"):
            with st.spinner("Asking the Odds API history…"):
                got = _historical_alts(g, book)
            if got.get("error"):
                st.warning(got["error"])
            else:
                quotes = got["quotes"]
                if got.get("remaining"):
                    st.caption(f"Odds API credits left: {got['remaining']}")
    rows = LS.lookback(rows_in, quotes, PE.norm_name)
    if not rows:
        st.info("No rungs to show for this pick.")
        return
    summ = LS.night_summary(rows)
    if summ["rungs"]:
        st.markdown(f"**{summ['hits']} of {summ['rungs']} rungs hit** — the honest chances expected about "
                    f"**{summ['expected']:.0f}**. Close means the chances were fair that night; one night is noisy.")
    else:
        st.caption("Box scores aren't final yet for this pick.")
    only = st.checkbox("Only the ones that hit", value=False, key="ls_past_hits")
    show = [r for r in rows if r["Hit"] == "✅"] if only else rows
    cols = ["Player", "Bet", "Hit", "Actual", "Honest chance", "Fair price", "Price", "EV per $1", "Projection",
            "Main line", "Game"]
    if not any(r["Price"] for r in show):
        cols = [c for c in cols if c not in ("Price", "EV per $1")]
    st.dataframe(pd.DataFrame([{c: r[c] for c in cols} for r in show]), hide_index=True, width="stretch",
                 column_config={"Honest chance": st.column_config.NumberColumn(format="percent"),
                                "Fair price": st.column_config.NumberColumn(format="%+d", help=(
                                    "The price that would be a fair bet at the honest chance — a book paying more "
                                    "than this was a value bet")),
                                "Price": st.column_config.NumberColumn(format="%+d"),
                                "EV per $1": st.column_config.NumberColumn(format="%+.2f"),
                                "Projection": st.column_config.NumberColumn(format="%.1f")})
    st.caption("Each rung above the book's main line, priced from what the model said before tip-off (its saved "
               "projection and main-line chance; the spread is re-fitted, so it's close to the live page, not "
               "identical). **Fair price**: if the book paid more than this, it was a value bet. Hits at long fair "
               "prices are the outliers — a good long shot still misses most nights, so judge it over many.")

st.warning("**Watch list, not a bet list (yet).** First real test, Nov 9 (all 8 NBA games, 1,705 DraftKings alternate "
           "rungs at tip-off prices): the rungs this page would have called value hit **48** times, where the model "
           "expected 111 and the book's prices implied 80. When the model and the book disagree on an alternate line, "
           "the book has been right more often. More nights are being tested; until then, small stakes only.")
eastern = pytz.timezone("US/Eastern")
today = datetime.now(eastern).date()
day = st.date_input("Date", value=today, max_value=today, key="longshots_date",
                    help="Today: tonight's alternate lines and their value. A past date: what the model's honest "
                         "chances were for each rung above the main line, and what actually happened.")
date_str = day.strftime("%Y-%m-%d")
api_key = BBD.get_odds_api_key()
book = BBD.render_book_selector(key_prefix="longshots", date_str=date_str)
ALT_ARCHIVE = ["long_shots_alt"]


def _archive(g, quotes, kickoff):
    """Keep tonight's alternate prices so a look back at this date shows them for free."""
    try:
        import model_store as MS
        MS.save_odds(_active.key, date_str, g.get("home_name") or "", g.get("away_name") or "", ALT_ARCHIVE,
                     {"offers": quotes}, kickoff)
    except Exception:                                           # noqa: BLE001
        pass


if day < today:
    _look_back()
    st.stop()

if not api_key:
    st.info("Needs the Odds API key (ODDS_API_KEY) — alternate lines come from the books.")
    st.stop()


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
            _archive(g, res.get("quotes") or [], ev.get("commence_time"))
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
