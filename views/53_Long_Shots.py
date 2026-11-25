"""
Long Shots (Nov 10) — alternate-line value: the books' price on "8+ assists", "30+ points"... vs the model's HONEST
chance of it. Owner request after Jeremiah Fears' 8+ assists hit at +1500 (the model had projected 6.0 vs a 4.5 line).
Logic and the tail-honesty table: long_shots.py. NBA, (Nov 12) NFL and (Nov 14) NHL and college football -- the sports the tail and price tests cover.
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
C.page_header("💎", "Long Shots", "Alternate lines (8+ assists, 100+ rush yards…) where the book's price is longer than the "
                                 "model's honest chance — the Fears-at-+1500 kind of bet, found before the game starts.")
if not sports.require_sport(["NBA", "NFL", "NHL", "NCAAF"], "Long Shots"):
    st.stop()
SPORT = _active.key if _active.key in LS.SPORTS else "NBA"
ALTS = LS.SPORTS[SPORT]["alt"]                                  # this sport's alternate markets -> main markets
START = {"NFL": "kickoff", "NCAAF": "kickoff", "NHL": "puck drop"}.get(SPORT, "tip-off")
# The one market whose value lines have made money in testing (research/longshot_backtest.py)
BEST = {"NBA": ("Assists",), "NFL": ("Rush Yards",), "NHL": ("Goals",),
        "NCAAF": ("Rush Yards", "Receiving Yards")}[SPORT]
WARN = {
    "NBA": "**Watch list, not a bet list.** Tested on 10 NBA nights (Oct 30 – Nov 9, ~10,000 DraftKings alternate "
           "lines): the lines this page calls value returned **−22%** bet at 11am prices and **−32%** at tip-off. The "
           "model's long-shot chances are fair on average, but where it disagrees with the book the book is usually "
           "right. **One exception so far: Assists** (+27% at 11am, +8% at tip-off over 549 bets) — promising, not "
           "proven. Bet early, keep stakes to a few dollars.",
    "NFL": "**Watch list, not a bet list.** Tested on 5 NFL game days (Nov 1 – Nov 9, ~3,000 DraftKings alternate "
           "lines): the lines this page calls value returned **−19%** at 11am prices and **−21%** at kickoff, and "
           "prices of +1200 or longer lost over 40%. **One exception so far: Rush Yards** (+32% at 11am, +36% at kickoff "
           "over ~160 bets) — promising, not proven: mostly two Sundays. Keep stakes to a few dollars.",
    "NHL": "**Watch list, not a bet list.** Tested on 11 NHL nights (Nov 3 – Nov 13, ~7,000 DraftKings alternate "
           "lines): the lines this page calls value returned **−11%** at 11am prices and **−25%** at puck drop, and "
           "prices of +1200 or longer lost over 40%. Shots on Goal and Points lost 24–38%. **Closest to an exception: "
           "Goals** (+28% at 11am over 341 bets, but only 13 hits, and break-even at puck drop) — a lead, not an edge. "
           "Bet early if at all, and keep stakes to a dollar or two.",
    "NCAAF": "**Watch list, not a bet list — but the best test result on this page.** Tested on 9 college football "
             "days (Oct 30 – Nov 13, ~2,400 DraftKings alternate lines): the lines this page calls value returned "
             "**+27%** at 11am prices and **+14%** at kickoff, and the book moved its price toward the model on 62% of "
             "them. **Rush Yards** (+37% at 11am, +26% at kickoff) and **Receiving Yards** (+31% / +24%) carried it; "
             "**Pass Yards lost 27–33%** and Receptions went from +69% to −15% by kickoff. Most of the bets came from "
             "two Saturdays, so this is promising, not proven. Bet early, keep stakes to a few dollars.",
}[SPORT]



@st.cache_data(ttl=1800, show_spinner=False)
def _lead(r):
    """Nov 24 (owner: every table like NCAAMB's): League and Bet? lead every long-shot table. 🃏 Bet = a market whose
    long-shot value lines have made money in testing (BEST); everything else is Info only."""
    mk = r.get("Market") or ""
    if not mk and r.get("Bet"):
        mk = next((m for m in BEST if m in str(r.get("Bet"))), "")
    return {"League": SPORT, "Bet?": "🃏 Bet" if mk in BEST else "Info only"}


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
    for mk in ALTS:
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
                "Position Matchups, Long Shots…) is opened before the game starts.")
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
            st.caption("Alternate prices: saved from when they were loaded before the game starts.")
        elif api_key and g and st.button(f"📈 Load that night's alternate prices (~{10 * len(ALTS)} credits, "
                                         "paid Odds API plan only)", key="ls_hist"):
            with st.spinner("Asking the Odds API history…"):
                got = _historical_alts(g, book)
            if got.get("error"):
                st.warning(got["error"])
            else:
                quotes = got["quotes"]
                if got.get("remaining"):
                    st.caption(f"Odds API credits left: {got['remaining']}")
    rows = LS.lookback(rows_in, quotes, PE.norm_name, sport=SPORT)
    if not rows:
        st.info("No rungs to show for this pick.")
        return
    summ = LS.night_summary(rows)
    if summ["rungs"]:
        st.markdown(f"**{summ['hits']} of {summ['rungs']} rungs hit** — the honest chances expected about "
                    f"**{summ['expected']:.0f}**. Close means the chances were fair that night; one night is noisy.")
    else:
        st.caption("Box scores aren't final yet for this pick.")
    C.hit_miss_breakdown(rows, "Hit", "Honest chance", key="ls_past_hm", title="Rungs that hit and missed")
    show = C.show_filter(rows, "Hit", key="ls_past_show")      # Nov 19: all / only the hits / only the misses
    cols = ["Player", "Bet", "Hit", "Actual", "Honest chance", "Fair price", "Price", "EV per $1", "Projection",
            "Main line", "Game"]
    if not any(r["Price"] for r in show):
        cols = [c for c in cols if c not in ("Price", "EV per $1")]
    st.dataframe(pd.DataFrame([{**_lead(r), **{c: r[c] for c in cols}} for r in show]), hide_index=True, width="stretch",
                 column_config={"Honest chance": st.column_config.NumberColumn(format="percent"),
                                "Fair price": st.column_config.NumberColumn(format="%+d", help=(
                                    "The price that would be a fair bet at the honest chance — a book paying more "
                                    "than this was a value bet")),
                                "Price": st.column_config.NumberColumn(format="%+d"),
                                "EV per $1": st.column_config.NumberColumn(format="%+.2f"),
                                "Projection": st.column_config.NumberColumn(format="%.1f")})
    st.caption("Each rung above the book's main line, priced from what the model said before the game starts (its saved "
               "projection and main-line chance; the spread is re-fitted, so it's close to the live page, not "
               "identical). **Fair price**: if the book paid more than this, it was a value bet. Hits at long fair "
               "prices are the outliers — a good long shot still misses most nights, so judge it over many.")

st.warning(WARN)
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

# Nov 16: lead with the day's scan (long_shots_scan.py runs a few times a day and saves it: no credits to show it),
# so the page opens on tonight's long shots instead of a game picker and a load button.
import long_shots_scan as _LSS


@st.cache_data(ttl=600, show_spinner=False)
def _scan(sport_key, d):
    return _LSS.load(sport_key, d)


_saved = _scan(SPORT, date_str)
_cards = _LSS.lead_cards(_saved)
C.section_header("💎", f"Tonight's top {SPORT} long shots",
                 "From today's scan of every game: the most likely long shots still worth their price.")
if _cards:
    for _col, _c in zip(st.columns(len(_cards)), _cards):
        with _col.container(border=True):
            st.markdown(f"**{_c['pick']}**")
            st.metric("Price", "—" if _c["price"] is None else f"{float(_c['price']):+.0f}", label_visibility="collapsed")
            st.caption(("—" if _c["chance"] is None else f"Honest chance {_c['chance']:.0%}")
                       + ("" if _c["book"] is None else f" · book says {_c['book']:.0%}")
                       + f"  \n{_c['game']}" + (f" · {_c['time']}" if _c["time"] else ""))
            st.caption(_c["note"])
    try:
        _asof = datetime.fromisoformat(_saved["at"]).astimezone(eastern).strftime("%-I:%M %p")
    except (KeyError, TypeError, ValueError):
        _asof = ""
    _all = _LSS.all_rows(_saved)
    with st.expander(f"All {len(_all)} value long shots from today's scan"
                     + (f" ({_saved.get('games', 0)} games)" if _saved.get("games") else "")):
        import card_links as _CL                                # Nov 25: a row opens the player card
        _CL.table(pd.DataFrame([{**_lead(r), **r} for r in _all]), key=f"ls_all_{SPORT}",
                  items=_LSS.sorted_rows(_saved),
                  open_fn=_CL.open_player_named(SPORT), hide_index=True, width="stretch",
                  caption="Tap a row to open the player's card — his alt lines are on it too.", column_config={
            "Price": st.column_config.NumberColumn(format="%+d"),
            "Honest chance": st.column_config.NumberColumn(format="percent"),
            "Book says": st.column_config.NumberColumn(format="percent"),
            "EV per $1": st.column_config.NumberColumn(format="%+.2f")})
    st.caption((f"Prices as of {_asof} ET. " if _asof else "")
               + "Most long shots lose: these are tail outcomes on a normal night, priced a little longer than the "
                 "honest chance. Flat stakes of a few dollars, never two of the same player in one parlay.")
else:
    st.info("No long-shot scan for today yet. It runs a few times a day once the books post alternate lines; "
            "until then, pick a game below.")
st.divider()
C.section_header("🔎", "Dig into one game", "Every rung for one game at your book.")

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
    st.info(f"No {SPORT} games with posted player lines yet today.")
    st.stop()

games = {m["label"]: m for m in meta}
pick = st.selectbox("Game", list(games.keys()), key="longshots_game")
g = games.get(pick) or next(iter(games.values()))
store = st.session_state.setdefault("longshots_quotes", {})
if not C.is_owner() and g["label"] not in store:
    # Nov 14: the public build never spends Odds API credits here -- it reads the alternate prices the scheduled
    # long-shot scan (long_shots_scan.py) archived for this game today
    try:
        import model_store as MS
        _sv = MS.load_odds(_active.key, date_str, g.get("home_name") or "", g.get("away_name") or "", ALT_ARCHIVE)
    except Exception:                                           # noqa: BLE001
        _sv = None
    if _sv and _sv.get("offers"):
        store[g["label"]] = {"quotes": _sv["offers"], "remaining": None, "unavailable": []}
    else:
        st.info("Today's alternate lines for this game haven't been scanned yet — the scan runs a few times a day.")
        st.stop()
if C.is_owner() and st.button(f"📈 Load alternate lines for {g['label']}  (~{len(ALTS)} Odds API credits)", key="ls_load"):
    try:
        import book_menu as BM
        import position_lines as PL
        ev = PL.match_event(O.fetch_events_all(api_key, sport=_active.odds_sport_key), g["home_name"], g["away_name"])
        if not ev:
            store[g["label"]] = {"error": "The books haven't posted this game yet."}
        else:
            res = BM.fetch_menu(api_key, _active.odds_sport_key, [ev["id"]], list(ALTS), book or O.DEFAULT_BOOK,
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
                 PE.prob_over, sport=SPORT)
if got.get("remaining"):
    st.caption(f"Odds API credits left: {got['remaining']}")
value = [r for r in rows if r["EV per $1"] > 0]
st.markdown(f"**{len(value)} rung(s) priced longer than the honest chance** · {len(rows)} checked")
if not rows:
    st.info("No alternate rungs to compare for this game at this book (or the model has no read on these players).")
    st.stop()
mkts = sorted({r["Market"] for r in rows})
only = st.multiselect("Markets", mkts, default=[m for m in mkts if m in BEST] or mkts, key=f"ls_markets_{SPORT}",
                      help=f"{' and '.join(BEST)} {'is the only' if len(BEST) == 1 else 'are the'} {SPORT} "
                           f"market{'s' if len(BEST) > 1 else ''} whose value lines have made money in testing so far.")
rows = [r for r in rows if r["Market"] in only] if only else rows
value = [r for r in rows if r["EV per $1"] > 0]
show = value or rows[:15]
df = pd.DataFrame([{**_lead(r), **{k: r[k] for k in ("Player", "Bet", "Price", "Book says", "Honest chance", "Model raw", "Edge",
                                       "EV per $1", "Projection", "Main line", "Flags")}} for r in show])
sel = LU.selectable(df, "ls_sel", hide_index=True, width="stretch", column_config={
    "Price": st.column_config.NumberColumn(format="%+d"),
    "Book says": st.column_config.NumberColumn(format="percent"),
    "Honest chance": st.column_config.NumberColumn(format="percent"),
    "Model raw": st.column_config.NumberColumn(format="percent"),
    "Edge": st.column_config.NumberColumn(format="percent"),
    "EV per $1": st.column_config.NumberColumn(format="%+.2f"),
    "Projection": st.column_config.NumberColumn(format="%.1f")})
LU.panel(LU.picked(show, sel), "ls_log", date_str, tag="long-shot")
st.caption(C.money_md(
    "**Honest chance** = the model's chance of the rung, corrected by how its long-shot chances have actually landed "
    "(walk-forward test per market: it overstates the middle rungs and understates the longest ones). "
    "**Book says** = the chance the price implies (vig included, so it's a bit high). **EV per $1** = what $1 returns "
    "on average at the honest chance — +1.00 means it should double over many bets. These hit rarely: most nights "
    "a long shot loses, so keep stakes small and flat (a few dollars), never chase. Rows marked *check news* have a "
    "projection far from the book's main line — the book may know about a role or minutes change."))
