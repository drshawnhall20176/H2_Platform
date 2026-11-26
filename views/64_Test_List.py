"""
64_Test_List.py -- the owner's test list (focus_list.py), in the Owner Office (Nov 26).

Every 🃏 Bet, 💰 Money pick and 🧪 close-gap pick of the day across every sport, one filterable table, earliest start
first. Owner only (an Office page). Tap a row for the player or game card.
"""
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

import components as C
import focus_list as FL

if not hasattr(FL, "merge_props"):                               # Nov 26: a server still holding the old module
    import importlib
    FL = importlib.reload(FL)
import todays_best as TB

ET = pytz.timezone("US/Eastern")
C.base_css()
C.page_header("🎯", "Test list",
              "Every 🃏 Bet, 💰 Money pick and 🧪 close-gap pick on today's boards, every sport, in one list — the "
              "picks you're testing, and nothing else. Follows the boards as the lines move.")

_now = datetime.now(ET)
c1, c2, c3 = st.columns([1, 2, 1])
day = c1.date_input("Date", _now.date(), key="tl_day", format="MM/DD/YYYY").strftime("%Y-%m-%d")
kinds = c2.pills("Show", list(FL.KINDS), selection_mode="multi", default=list(FL.DEFAULT_KINDS), key="tl_kinds2",
                 help="Bets: 💰 Money pick (the 💰 rule where it's on) · 🃏 Bet (a tested tag whose earned chance clears "
                      "its price). Paper (tracked, never sized): 🧪 Close gap (college basketball, model and market within "
                      "2 points) · 🧪 Prop rule (the NFL / college football Unders) · ⏸ Paused / off rule (the 💰 rule "
                      "in sports or markets where it's off, the paused college basketball 💰 game lines, switched-off "
                      "🔒 markets) · 📉 Tag held back (a playable tag whose earned chance doesn't clear its price).")
if c3.button("🔄 Refresh now", help="Re-read the boards (they also refresh on their own every 5 minutes)."):
    st.cache_data.clear()


@st.cache_data(ttl=300, show_spinner="Reading today's boards…", max_entries=8)
def _boards(d):
    import customer_today as CT
    past = d < datetime.now(ET).strftime("%Y-%m-%d")
    props = (TB.collect(d, list(CT.PROPS_SPORTS), past=past).get("rows") or [])
    reads = []                                                  # Nov 26: every prop read, for the paper rules
    for sp in CT.PROPS_SPORTS:
        reads += [dict(r, sport=r.get("sport") or sp) for r in TB.load_reads(sp, d)]
    props = FL.merge_props(reads, props)
    try:
        winners = TB.winner_rows(d, past=past)
    except Exception:                                           # noqa: BLE001
        winners = []
    return props, winners, datetime.now(ET).strftime("%-I:%M %p")


try:
    props, winners, read_at = _boards(day)
except Exception as exc:                                        # noqa: BLE001
    st.warning(f"The boards couldn't be read just now ({type(exc).__name__}). Try Refresh in a minute.")
    st.stop()

every = FL.build(props, winners, kinds=FL.KINDS, parse_time=C._kick_dt)
sports_here = sorted({r["sport"] for r in every})
d1, d2 = st.columns([3, 1])
pick_sports = d1.multiselect("Sports", sports_here, placeholder="All sports", key="tl_sports")
hide_started = d2.toggle("Hide games that have started", value=day == _now.strftime("%Y-%m-%d"), key="tl_hide")
rows = FL.build(props, winners, kinds=kinds or FL.DEFAULT_KINDS, sports=pick_sports or None, parse_time=C._kick_dt)
if hide_started:
    def _gone(r):
        k = C._kick_dt(r.get("time"))
        try:
            return k is not None and k <= _now
        except TypeError:
            return False
    rows = [r for r in rows if not _gone(r)]

# ---------- Nov 26 (owner): what a chosen sportsbook and pick'em app offer right now, with a go / no-go ----------
import book_check as BC
import my_books as MB
import odds_api as O
import pickem as PK

b1, b2, b3 = st.columns([1.2, 1.2, 1])
_books = MB.sportsbooks()
base = MB.book()                                                # Nov 26: the baseline -- My sportsbook (DraftKings)
book = b1.selectbox("Check prices at", _books, index=_books.index(MB.book()) if MB.book() in _books else 0,
                    format_func=O.book_label, key="tl_book",
                    help="Scroll through the books: the price, what it needs, and Go / No go update for each.")
_apps = MB.apps()
app = b2.selectbox("Pick'em app", _apps, index=_apps.index(MB.app()) if MB.app() in _apps else 0,
                   format_func=MB.app_label, key="tl_app")
n_picks = b3.slider("Picks in the entry", 2, 6, 3, key="tl_n")
_pay = (PK.APPS.get(app) or {}).get("power") or {}
app_need = PK.breakeven(_pay[n_picks], n_picks) if _pay.get(n_picks) else None


@st.cache_data(ttl=300, show_spinner="Checking the books' current prices…", max_entries=16)
def _prop_offers(sp, d, extra):
    import best_bets_data as BBD
    api = BBD.get_odds_api_key()
    if not api:
        return []
    got = BBD.recent_offers(sp, d, api)
    if extra:
        got = BBD.merge_offers(got, BBD.fetch_pickem_extra_offers(sp, d, api))
    return got


@st.cache_data(ttl=300, show_spinner="Checking the books' current game lines…", max_entries=16)
def _game_events(sp):
    import best_bets_data as BBD
    import sports as _S
    api = BBD.get_odds_api_key()
    if not api:
        return []
    data, _h = O._get(f"sports/{_S.get(sp).odds_sport_key}/odds",
                      {"apiKey": api, "bookmakers": ",".join(_books), "markets": "h2h,spreads,totals",
                       "oddsFormat": "american", "dateFormat": "iso"})
    return data if isinstance(data, list) else []


_extra = app not in ("pick6", "prizepicks")                     # the boards' main fetch carries these two
_offers, _events = {}, {}
for _sp in sorted({r["sport"] for r in rows}):
    try:
        if any(r["open_as"] != "game" for r in rows if r["sport"] == _sp):
            _offers[_sp] = _prop_offers(_sp, day, _extra)
        if any(r["open_as"] == "game" for r in rows if r["sport"] == _sp):
            _events[_sp] = _game_events(_sp)
    except Exception:                                           # noqa: BLE001 -- a feed hiccup never blanks the list
        pass
for r in rows:
    try:
        if r["open_as"] == "game":
            ev = BC.find_event(_events.get(r["sport"]), r.get("home"), r.get("away"))
            q = BC.game_quotes(ev, r.get("market"), r.get("side"), r.get("home"), r.get("away"))
        else:
            q = BC.prop_quotes(_offers.get(r["sport"]), r.get("player"), r.get("market_key"), r.get("side"))
        r.update(BC.judge(r, q, book, _books))
        r["app_verdict"] = BC.judge_app(r, q, app, app_need)
        # Nov 26 (owner): the baseline book (My sportsbook) beside the selected one, and how each has moved
        bq = BC.at_book(q, r.get("line"), base, r.get("side") or "")
        r["base_price"], r["base_line"] = bq["price"], bq["line"]
        r["base_move"] = BC.compare(bq["price"], bq["line"], r.get("price"), r.get("line"), r.get("side") or "",
                                    "= unchanged")
        r["vs_base"] = ("— same book" if book == base else
                        BC.compare(r.get("book_price"), r.get("book_line"), bq["price"], bq["line"],
                                   r.get("side") or ""))
    except Exception:                                           # noqa: BLE001
        r.update({"book_verdict": "— Couldn't check", "app_verdict": "—"})

n = FL.counts(rows)
m1, m2, m3, m4 = st.columns(4)
m1.metric("💰 Money picks · 🃏 Bets", f"{n[FL.MONEY]} · {n[FL.BET]}", help="The real bets: tested and live.")
m2.metric("🧪 Close gap · prop rules", f"{n[FL.GAP]} · {n[FL.TRACK]}", help="Rules being tested forward: paper.")
m3.metric("⏸ Paused / off · 📉 Held back", f"{n[FL.PAUSED]} · {n[FL.HELD]}", help="Paper: what those rules would bet.")
m4.metric("Boards read at", read_at)
st.caption("**Bet** rows are the tested picks. **Paper** rows are every rule still being tested, paused or held back — "
           "track them (or log them at a small test stake) so each one builds the record that decides whether it goes "
           "live. Rules that need the hourly board rebuild show up after the next one (:49 past the hour).")

try:                                                            # the close-gap rule's forward record, right here
    import candidate_rules as CR
    cg = CR.status_line("NCAAMB", day)
    if cg:
        st.caption(cg)
except Exception:                                               # noqa: BLE001
    pass

if not rows:
    st.info("Nothing on the list for these filters. That's an answer too: no tested pick qualifies right now. Boards "
            "rebuild every hour as the books post and move lines.")
    st.stop()

import card_links as CL                                         # a row opens its player or game card


def _open(r):
    if r["open_as"] == "game":
        CL.open_game(lambda x: r["sport"])(r["src"])
    else:
        CL.open_player(r["sport"])(r["src"])


_df = pd.DataFrame(FL.table(rows)).rename(columns={"Price": "Board price", "Needs": "Board needs",
                                                  "Edge": "Board edge"})
_bl = O.book_label(book)
_base_l = O.book_label(base)


def _q(price, line, pick_line):
    if price is None:
        return "—"
    return f"{price:+.0f}" + ("" if line in (None, pick_line) else f" at {line:g}")


_df.insert(_df.columns.get_loc("Board edge") + 1, f"{_base_l} now",
           [_q(r.get("base_price"), r.get("base_line"), r.get("line")) for r in rows])
_df.insert(_df.columns.get_loc(f"{_base_l} now") + 1, f"{_base_l} move", [r.get("base_move") or "—" for r in rows])
if book != base:
    _df.insert(_df.columns.get_loc(f"{_base_l} move") + 1, f"{_bl} now",
               [_q(r.get("book_price"), r.get("book_line"), r.get("line")) for r in rows])
    _df.insert(_df.columns.get_loc(f"{_bl} now") + 1, f"{_bl} vs {_base_l}", [r.get("vs_base") or "—" for r in rows])
_after = f"{_bl} vs {_base_l}" if book != base else f"{_base_l} move"
_df.insert(_df.columns.get_loc(_after) + 1, f"{_bl} needs", [FL.pct(r.get("book_need")) for r in rows])
_df.insert(_df.columns.get_loc(f"{_bl} needs") + 1, "Go?", [r.get("book_verdict") or "—" for r in rows])
_df.insert(_df.columns.get_loc("Go?") + 1, "Best price now",
           ["—" if r.get("best_price") is None else f"{r['best_price']:+.0f} {O.book_label(r['best_book'])}"
            for r in rows])
_df.insert(_df.columns.get_loc("Best price now") + 1, MB.app_label(app), [r.get("app_verdict") or "—" for r in rows])
st.caption(f"**{_base_l} now** is your book's price right now (My sportsbook, the baseline); **{_base_l} move** is "
           "how it has moved since the board read the pick (▲ better for you, ▼ worse, line changes first). "
           + (f"**{_bl} now** and **{_bl} vs {_base_l}** show the book picked above against your baseline. " if book != base
              else "Pick another book above to put its price beside your baseline. ")
           + f"**Go?** compares the earned chance with what **{_bl}'s price right now** needs: ✅ Go = 1+ point over "
           "break-even · 🟡 Thin = 0–1 point (shop the price) · ⛔ No go = under break-even · 🔁 = the book posts a "
           "different line (re-check: the chance was read at the pick's line) · 📝 Paper = a close-gap test pick (no "
           "chance of its own yet). **Best price now** is the best of every sportsbook at the pick's exact line. "
           f"**{MB.app_label(app)}**: is it on the app at the same line, and does its chance clear the "
           + (f"{app_need:.1%} each pick needs for a {n_picks}-pick entry." if app_need else "app's own price.")
           + " Prices refresh every 5 minutes.")
CL.table(_df, key=f"tl_table_{day}", items=rows, open_fn=_open, hide_index=True,
         width="stretch", caption="Tap a row for its card — the read, the recent games and the line history.",
         )
st.caption("**Chance** is the earned chance (how picks like it have actually done). **Needs** is what the price needs "
           "to break even; a price with * is the standard −110, shown where the boards saved no quote for that side. Close-gap picks have no chance of their own yet: they're a rule being tested forward, so "
           "track them on paper. Prices are the best the boards saw at their last read; check your book before you "
           "bet. Started games drop off the list.")

# ---------- Nov 26 (owner: "Do I have log capability from the site?"): log straight from the list ----------
with st.expander("📝 Log bets from this list", expanded=False):
    _labels = [f"{r['time']} · {r['kind']} · {r['pick']}" for r in rows]
    _pick = st.multiselect("Picks to log", list(range(len(rows))), format_func=lambda i: _labels[i], key="tl_log_pick",
                           placeholder="Choose the picks you placed")
    l1, l2, l3, l4 = st.columns(4)
    _mode = l1.radio("As", ["Singles", "Parlay", "Both"], key="tl_log_mode")
    _stake = l2.number_input("Stake per single ($)", min_value=0.5, value=2.70, step=0.5, key="tl_log_stake")
    _items = [it for it in (FL.log_item(rows[i], book) for i in _pick) if it]
    _auto = TB.parlay_odds([it["price"] for it in _items]) if len(_items) >= 2 else None
    _pstake = l3.number_input("Parlay stake ($)", min_value=0.5, value=2.70, step=0.5, key="tl_log_pstake")
    _pprice = l4.number_input("Parlay price (your slip's)", value=int(_auto or 100), step=5, key=f"tl_log_pprice_{_auto}",
                              help="Starts at the legs' prices multiplied together; a same-game parlay usually "
                                   "pays less -- type the price on your slip.")
    st.caption(f"Singles log at **{_bl}**'s current price when it posts the pick's line (else the boards' price and "
               "book) -- check it against your slip, and fix any difference in the Bet Log. Each bet is tagged by "
               "type (💰 money pick, 🧪 close-gap test, 🃏 tested pick), so the Bet Log and My Coach grade it as "
               "the model's call. The nightly review settles them.")
    if _pick and len(_items) < len(_pick):
        st.warning(f"{len(_pick) - len(_items)} of the chosen picks have no price or line to log; log those in the "
                   "Bet Log by hand.")
    if st.button("Log them", type="primary", disabled=not _items, key="tl_log_go"):
        try:
            _res = TB.log_selection(_items, _mode, float(_stake), float(_pstake), int(_pprice), True, "test-list", day,
                                    book=book)
            st.success(f"Logged {len(_res.get('singles') or [])} single(s)"
                       + (" and the parlay" if _res.get("ticket") else "")
                       + (f"; {_res['skipped']} already in the Bet Log were skipped." if _res.get("skipped") else "."))
        except Exception as exc:                                # noqa: BLE001
            st.error(f"Couldn't log them ({type(exc).__name__}: {str(exc)[:160]}). Nothing partial was hidden -- "
                     "check the Bet Log.")

