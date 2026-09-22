"""
Slip Lab — find, build and pressure-test singles and parlays from one book's REAL lines, then lock
them in.

The flow, top to bottom:
  1. Pick a slate date and a book (DraftKings, FanDuel, Hard Rock Bet, PrizePicks, DK Pick6, Bet365 ...).
  1b. TIME SLOT + GAME — the same two filters as every other page, at the top; they narrow the suggested
     tickets, the leg pool and the full menu (one game selected = no per-game leg cap on the suggestions).
  2. SUGGESTED TICKETS — ready-made singles and parlay / pick'em tickets built from the props the
     model prices at that book, three ways (safest, best value, balanced), each already run through
     the correlated simulation. "Load into slip" sends one to step 4.
  3. LEG POOL — browse every leg and tick the ones you want. Either the model-priced props (same
     numbers as Best Bets, with a "confidence floor" showing how much to trust each), or the book's
     FULL MENU: game lines, alternates, team totals, period markets and every player prop the book
     lists (fetched on demand, with a credit estimate first).
  4. YOUR SLIP — pick how it pays (parlay / singles / Power / Flex / Pick6), edit any probability or
     price, and see the instant math.
  5. PRESSURE TEST — correlated Monte Carlo, model-uncertainty worlds, overconfidence haircuts, a
     leg ranking (which legs are strongest, which drag), leg-drop analysis and a repeat-play
     bankroll projection, then a plain-language read.
  6. LOCK IT IN — send the tested slip to the Bet Log with the same widget every other page uses.

All the math lives in slip_lab.py / slip_sim.py / slip_suggest.py / book_menu.py (unit-tested);
this file is layout only.
"""

import hashlib
import json
import time
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import pytz
import streamlit as st

import components as C
import styling  # noqa: F401  (installs the theme-proof styles)
import best_bets_data as BBD
import book_menu as BM
import odds_api as O
import quick_log
import slip_lab as SL
import slip_sim as SIM
import slip_suggest as SS
import sports

_active = sports.active()
E, P = _active.engine, _active.projections

C.base_css()
C.page_header("🧪", "Slip Lab",
              f"Model singles and parlays from a real book's lines, pressure-test them, then lock them in — "
              f"{_active.icon} {_active.label}")

try:
    if st.secrets.get("AUDIENCE", "owner") != "owner":
        st.info("Slip Lab is part of the owner tools.")
        st.stop()
except Exception:
    pass  # no secrets file (local run) — treated as the owner build, same as quick_log

if not sports.require_live_engine("Slip Lab"):
    st.stop()
if not _active.has_projections:
    st.info("🥊 Slip Lab doesn't apply to UFC — fights are outcome-based, not counting-stat props. "
            "Head to **UFC Fight Card** in the sidebar.")
    st.stop()

eastern = pytz.timezone("US/Eastern")
SPORT_KEY = _active.key
API_KEY = BBD.get_odds_api_key()

MODE_LABELS = {
    "parlay": "Parlay — every leg must hit",
    "singles": "Singles — each leg its own bet",
    "power": "PrizePicks Power Play — every pick must hit",
    "flex": "PrizePicks Flex Play — pays for most picks hitting",
    "pick6": "DK Pick6 — every pick must hit",
}
MAX_LEGS = 12


def _am(x):
    return "—" if x is None or pd.isna(x) else f"{x:+.0f}"


def _pct(x, digits=1):
    return "—" if x is None or pd.isna(x) else f"{x * 100:.{digits}f}%"


def _ss(key, default):
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


# --------------------------------------------------------------------------- 1. controls
c_date, c_book = st.columns([1, 2])
with c_date:
    target = st.date_input("Slate date", datetime.now(eastern), key="slip_lab_date")
date_str = target.strftime("%Y-%m-%d")

label_to_key = {label: key for key, label in O.ALL_BOOKS.items()}
with c_book:
    default_label = O.ALL_BOOKS.get(O.DEFAULT_BOOK, "DraftKings")
    labels = list(label_to_key)
    book_label = st.selectbox(
        "📖 Book", labels, index=labels.index(default_label) if default_label in labels else 0,
        key="slip_lab_book_selector",
        help="Sportsbooks (DraftKings, FanDuel, Hard Rock Bet, ...) price each side of a prop. "
             "PrizePicks and DK Pick6 post a line only — the entry pays a fixed multiplier. "
             "Bet365 has no US player-prop feed here, so its legs are typed in by hand.")
book = label_to_key[book_label]
is_pickem = O.is_pickem_book(book)
is_manual = O.is_manual_book(book)
book_kind = ("pick'em app — fixed line, entry pays a multiplier" if is_pickem else
             "typed in by hand — no live prop feed for this book" if is_manual else "sportsbook — real price on each side")
st.caption(f"**{book_label}**: {book_kind}.")

# The board itself is always built against a real, fetched book: the chosen one when The Odds
# API carries it, DraftKings' board for a manual (Bet365) selection.
board_book = O.DEFAULT_BOOK if is_manual else book

with st.spinner(f"Loading {_active.label} board and lines..."):
    try:
        if SPORT_KEY == "MLB":
            plays, meta, _avail = BBD.load_mlb_best_bets_board(date_str, E.FIP_CONSTANT_DEFAULT, board_book, None, None)
            offers = BBD.fetch_mlb_real_lines(date_str, API_KEY, board_book)[1] if API_KEY else []
        else:
            plays, meta, _avail = BBD.load_generic_best_bets_board(SPORT_KEY, date_str, board_book)
            offers = []
            if API_KEY and _active.markets:
                try:
                    offers = BBD.fetch_generic_offers(SPORT_KEY, date_str, API_KEY)
                except Exception:
                    offers = []
    except Exception:
        st.warning(f"No slate data available for {_active.label} on {date_str}. Normal during the "
                   "off-season — try a date with games, or switch sports.")
        st.stop()
offers = offers or []

plays = [pl for pl in (plays or []) if sports.has_started(pl.get("GameDate")) is not True]
if not plays:
    st.info(f"No {_active.label} plays on the board for {date_str} (or every game has started). "
            "Try another date, hit Refresh, or switch sports.", icon="📅")
    st.stop()

if not API_KEY:
    st.warning("No Odds API key is configured, so there are no real book prices. You can still build "
               "legs from the model board and type in the prices your book shows.")
else:
    live_books = O.books_in_offers(offers)
    if live_books and not is_manual and book not in live_books:
        st.warning(f"{book_label} hasn't posted lines for this slate yet (or isn't in the feed for these "
                   "markets), so legs show without a price. Try again closer to game time, or type in the "
                   "price your book shows.")
    elif live_books:
        st.caption("Lines posted today by: " + ", ".join(O.book_label(b) for b in live_books))

pool = SL.build_leg_pool(plays, offers, book, _active.market_map, P.normalize_name,
                         single_line_markets=_active.single_line_markets)
pool_by_id = {l["id"]: l for l in pool}

# --------------------------------------------------------------------------- slip state
ctx = (SPORT_KEY, date_str)
if st.session_state.get("slip_lab_ctx") != ctx:
    st.session_state["slip_lab_ctx"] = ctx
    st.session_state["slip_lab_legs"] = []
    st.session_state["slip_lab_result"] = None
    st.session_state["slip_lab_ver"] = st.session_state.get("slip_lab_ver", 0) + 1
legs = _ss("slip_lab_legs", [])
ver = _ss("slip_lab_ver", 0)

# Switching book re-prices the legs already on the slip from the new book's real prices. A leg
# from a book's full menu belongs to THAT book's menu, so it loses its price on a switch.
if st.session_state.get("slip_lab_book_seen") != book:
    st.session_state["slip_lab_book_seen"] = book
    for i, leg in enumerate(legs):
        fresh = pool_by_id.get(leg["id"])
        if fresh is not None and leg.get("source") == "board":
            legs[i] = dict(fresh, p=leg["p"], stake=leg.get("stake"))
        elif leg.get("source") in ("board", "menu"):
            legs[i] = dict(leg, price=None, at_book=False, book=book)
    st.session_state["slip_lab_ver"] = ver = ver + 1


# --------------------------------------------------------------------------- loading tickets into the slip
def _load_legs(new_legs, mode, stake=None, message=""):
    """Callback for every 'Load into slip' button: replace the slip, set how it pays, and clear any
    stale result. Runs BEFORE the page re-renders, so the widgets pick the new values up."""
    ss = st.session_state
    ss["slip_lab_legs"] = [dict(l, stake=float(l.get("stake") or 10.0)) for l in new_legs]
    ss["slip_lab_mode"] = mode
    ss["slip_lab_parlay_price"] = 0          # a typed price belonged to the previous slip
    if stake:
        ss["slip_lab_stake_in"] = float(max(1.0, round(stake, 2)))
    ss["slip_lab_result"] = None
    ss["slip_lab_ver"] = ss.get("slip_lab_ver", 0) + 1
    ss["slip_lab_flash"] = message or f"Loaded {len(new_legs)} leg(s) into Your slip below."


def _load_ticket(key):
    tk = st.session_state.get("slip_lab_ticket_store", {}).get(key)
    if tk:
        _load_legs(tk["legs"], tk["mode"], stake=tk.get("stake") or 10.0,
                   message=f"Loaded the {SS.ticket_title(tk)} into Your slip below — run the pressure test to "
                           "see how it holds up.")


def _load_singles(key):
    rows = st.session_state.get("slip_lab_single_store", {}).get(key) or []
    if rows:
        _load_legs([dict(r["leg"], stake=(r["stake"] or 10.0)) for r in rows], "singles",
                   message=f"Loaded {len(rows)} singles into Your slip below (a stake of 10 where the sizing rule "
                           "gave 0 — edit any stake in the table).")


flash = st.session_state.pop("slip_lab_flash", None)
if flash:
    st.success(flash + " ⬇️")

with st.expander("🧭 How to use Slip Lab — start here", expanded=not legs):
    st.markdown(
        "**1. Pick the book you'll bet at** (top of the page).  \n"
        "**2. Look at *Suggested tickets*.** Slip Lab ranks every prop the model prices at that book and "
        "builds the singles and parlays it thinks are best, three ways — *safest*, *best value*, *balanced*. "
        "Use **Time slot** and **Game** above them to narrow the slate (pick one game and the suggestions come "
        "only from it). Press **Load into slip** on one you like.  \n"
        "**3. Or build your own.** In *Leg pool*, tick legs — the model's props, or switch to **Full book menu** "
        "to see everything the book offers (spreads, totals, team totals, alternate lines, every player prop).  \n"
        "**4. Press *Run pressure test*.** The **Leg ranking** tab shows which legs are strongest and which are "
        "dragging the slip down; the other tabs show what happens if the model is a bit too confident.  \n"
        "**5. Lock it in** to the Bet Log.")
    st.caption("What the numbers can and can't tell you: a leg's *hit chance* is the model's probability — a "
               "simulation can't make a leg likelier than the model says. What it adds is (a) the **confidence "
               "floor** — how low the true chance plausibly is given how few games back the number — and (b) how "
               "the legs interact. Legs from the book's menu that the model doesn't price use the book's own "
               "probability, so they carry no edge unless you enter your own number.")

# The Time slot / Game filters are drawn into this slot at the TOP of the page (so they read as page-wide,
# like every other page), but their options depend on the leg pool and the fetched menu, which are built
# further down — so the widgets are filled in once those exist. The suggestions below them respect them too.
filter_box = st.container()
sugg_box = st.container()

# --------------------------------------------------------------------------- 2. leg pool
can_menu = bool(API_KEY) and not is_pickem and not is_manual
src_options = ["🎯 Model-priced props", "📖 Full book menu"]
C.section_header("🎯", "Leg pool", f"Pick legs to build a slip — priced at {book_label}", "#1f6feb")
src = st.radio("Where do legs come from?", src_options, horizontal=True, key="slip_lab_src",
               help="Model-priced props are the ones the model has a view on (with an edge you can trust or not). "
                    "The full book menu is everything the book lists, fetched on demand.")
use_menu = src == src_options[1]
if use_menu and not can_menu:
    st.info("The full menu is available for sportsbooks with an Odds API key. Pick'em apps (PrizePicks, DK Pick6) "
            "only post a line per player, which the model-priced list already covers, and Bet365 has no feed here "
            "— use *Add a leg by hand* for anything else.")
    use_menu = False

menu_legs = []
if use_menu:
    menu_key = (SPORT_KEY, date_str, book)
    menu = st.session_state.get("slip_lab_menu")
    if not menu or menu.get("ctx") != menu_key:
        menu = {"ctx": menu_key, "quotes": [], "events": {}, "pairs": set(), "unavailable": set(),
                "errors": [], "remaining": None, "ts": None, "aborted": None}
        st.session_state["slip_lab_menu"] = menu

    @st.cache_data(ttl=300, show_spinner=False)
    def _events_for_date(api_key, odds_sport, day):
        rows = []
        for e in O.fetch_events(api_key, sport=odds_sport):
            if O._eastern_date_str(e.get("commence_time")) == day:
                rows.append({"id": e["id"], "away": e.get("away_team"), "home": e.get("home_team"),
                             "commence": e.get("commence_time")})
        return rows

    def _clock(iso):
        try:
            return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(eastern).strftime("%I:%M %p").lstrip("0")
        except (ValueError, TypeError):
            return ""

    try:
        events = _events_for_date(API_KEY, _active.odds_sport_key, date_str)
    except Exception as exc:                                    # noqa: BLE001
        events = []
        st.warning(f"Couldn't load the games list from The Odds API ({exc}).")
    groups = BM.catalog(_active.odds_sport_key, _active.markets)
    with st.expander("📖 Fetch the book's menu", expanded=not menu["quotes"]):
        if not events:
            st.info("The Odds API lists no games for this date yet.")
        else:
            ev_by_label = {f"{e['away']} @ {e['home']} · {_clock(e['commence'])}".strip(" ·"): e for e in events}
            # When a single game is picked in the Time slot / Game filter, fetch just that game's menu by
            # default (fewer credits). The board's own offers tie each Odds API event to the board's game label.
            filt_game = st.session_state.get("slip_lab_game")
            if st.session_state.get("slip_lab_menu_game_seen") != filt_game:
                st.session_state["slip_lab_menu_game_seen"] = filt_game
                if filt_game and filt_game != SL.ALL_GAMES:
                    ev_game = BM.label_events({e["id"]: e for e in events}, [], BM.board_player_info(pool, P.normalize_name),
                                              P.normalize_name, offers=offers)
                    hit = [lbl for lbl, e in ev_by_label.items()
                           if ev_game.get(e["id"], {}).get("game") == filt_game.split("|")[0]]
                    if hit:
                        st.session_state["slip_lab_menu_games"] = hit
            m1, m2 = st.columns(2)
            with m1:
                sel_games = st.multiselect("Games", list(ev_by_label), default=list(ev_by_label)[:1],
                                           key="slip_lab_menu_games")
            with m2:
                default_groups = [g for g in ("Game lines", "Team totals") if g in groups]
                sel_groups = st.multiselect("What to fetch", list(groups), default=default_groups,
                                            key="slip_lab_menu_groups")
            mkeys = BM.all_keys(groups, sel_groups)
            cost = BM.estimate_cost(len(sel_games), len(mkeys))
            st.caption(f"{len(sel_games)} game(s) × {len(mkeys)} market(s) → up to **{cost} Odds API credits** "
                       f"(one request per game and market at {book_label} only; you're billed for markets the book "
                       "actually returns, so this is a ceiling).")
            ok_to_go = True
            if cost > 150:
                ok_to_go = st.checkbox(f"I understand this may use up to {cost} credits", key="slip_lab_menu_confirm")
            b1, b2 = st.columns([1, 1])
            with b1:
                go_fetch = st.button("📥 Fetch menu", type="primary", disabled=not (sel_games and mkeys and ok_to_go),
                                     key="slip_lab_menu_fetch")
            with b2:
                if st.button("🗑️ Clear fetched menu", key="slip_lab_menu_clear", disabled=not menu["quotes"]):
                    st.session_state["slip_lab_menu"] = None
                    st.rerun()
            if go_fetch:
                ids = [ev_by_label[g]["id"] for g in sel_games]
                bar = st.progress(0.0, text="Fetching...")
                res_m = BM.fetch_menu(API_KEY, _active.odds_sport_key, ids, mkeys, book,
                                      progress=lambda d, n: bar.progress(d / max(n, 1), text=f"Fetched {d} of {n}"))
                bar.empty()
                pairs = {(e, m) for e in ids for m in mkeys}
                menu["quotes"] = [q for q in menu["quotes"] if (q["event_id"], q["market"]) not in pairs] + res_m["quotes"]
                menu["events"].update(res_m["events"])
                menu["pairs"] |= pairs
                menu["unavailable"] |= set(res_m["unavailable"])
                menu["errors"] = res_m["errors"]
                menu["remaining"] = res_m["remaining"] or menu["remaining"]
                menu["aborted"] = res_m["aborted"]
                menu["ts"] = time.time()
                st.rerun()
    if menu.get("aborted"):
        st.error(f"The fetch stopped early: {menu['aborted']}")
    if menu["ts"]:
        age = (time.time() - menu["ts"]) / 60
        n_unavail = len({m for _, m in menu["unavailable"]})
        st.caption(f"Menu fetched {age:.0f} min ago · {len(menu['quotes']):,} prices from {len(menu['events'])} game(s)"
                   + (f" · {n_unavail} market(s) not offered for this sport/book" if n_unavail else "")
                   + (f" · {menu['remaining']} credits remaining" if menu.get("remaining") else "")
                   + (" · **prices may have moved — refetch before betting**" if age > 10 else ""))
        if menu["errors"]:
            with st.expander(f"{len(menu['errors'])} request(s) failed"):
                st.dataframe(pd.DataFrame(menu["errors"]), hide_index=True, width="stretch")
    board_info = BM.board_player_info(pool, P.normalize_name)
    labels_m = BM.label_events(menu["events"], menu["quotes"], board_info, P.normalize_name, offers=offers)
    menu_legs = BM.build_menu_legs(menu["quotes"], labels_m, book, market_map=_active.market_map,
                                   info=board_info, normalize_name=P.normalize_name)
    menu_legs = BM.attach_model(menu_legs, BM.model_index(pool, _active.market_map, P.normalize_name),
                                P.normalize_name)
    if menu["quotes"] and not menu_legs:
        st.info("The menu came back with nothing usable for the markets chosen.")
    elif not menu["quotes"]:
        st.info("Fetch a menu above to browse it here.")

source_legs = menu_legs if use_menu else pool
_sfx = "_menu" if use_menu else ""


def _basis(l):
    return {"market": "Book no-vig", "implied": "Book implied*", "yours": "Yours"}.get(l.get("p_source"), "Model")


def _fkey(name, options):
    """Widget key that changes when the option list does, so a stale selection can't outlive its options."""
    return f"slip_lab_f_{name}{_sfx}_" + hashlib.md5("|".join(map(str, options)).encode()).hexdigest()[:6]


markets_present = sorted({l["market"] for l in source_legs})

# Time slot + Game — the same pair every other page carries: the slot buckets games by real Eastern start
# time, the game list is chronological with the start time shown, and it defaults to everything in the slot.
# Page-wide: options come from the board's legs AND any fetched menu, and the choice narrows the leg pool,
# the menu list and the Suggested tickets.
all_filter_legs = list(pool) + list(menu_legs)
dh = SL.dh_labels(pool, menu_legs)
slot_options = [SL.ALL_SLOTS] + SL.slots_present(all_filter_legs)
if st.session_state.get("slip_lab_slot") not in slot_options:      # a stale pick can't outlive its option
    st.session_state["slip_lab_slot"] = SL.ALL_SLOTS
with filter_box:
    st.caption("🕒 **Narrow the slate** — the Time slot and Game you pick here apply to the suggested tickets and "
               "the leg pool below. Leave both on \"All\" to see everything.")
    h1, h2 = st.columns(2)
    with h1:
        slot_pick = st.selectbox("Time slot", slot_options, key="slip_lab_slot")
    game_opts_f = SL.game_choices(SL.filter_slot_game(all_filter_legs, slot_pick, SL.ALL_GAMES, dh), dh)
    game_label = dict(game_opts_f)
    game_options = [SL.ALL_GAMES] + [k for k, _ in game_opts_f]
    if st.session_state.get("slip_lab_game") not in game_options:
        st.session_state["slip_lab_game"] = SL.ALL_GAMES
    with h2:
        game_pick = st.selectbox("Game", game_options, format_func=lambda k: game_label.get(k, k),
                                 key="slip_lab_game")
single_game = game_pick != SL.ALL_GAMES
narrowed = slot_pick != SL.ALL_SLOTS or single_game

f1, f3, f4 = st.columns([3, 1.5, 2])
with f1:
    default_mk = markets_present if use_menu else (
        [m for m in (_active.default_markets or markets_present) if m in markets_present] or markets_present)
    sel_markets = st.multiselect("Markets", markets_present, default=default_mk, key=_fkey("markets", markets_present))
with f3:
    side_pick = st.radio("Side", ["Both", "Over", "Under"], horizontal=True, key="slip_lab_f_side" + _sfx)
with f4:
    sort_pick = st.selectbox("Sort by", ["Confidence floor", "Model %", "EV at this book", "Edge vs market", "Conviction"],
                             key="slip_lab_f_sort" + _sfx,
                             help="Confidence floor = the low end of how likely the leg really is, given how many "
                                  "games back the model's number. It ranks a well-supported 60% above a thin one.")
g1, g2, g3 = st.columns([2, 2, 2])
with g1:
    min_p = st.slider("Min hit chance %", 0, 95, 0 if use_menu else 50, 5, key="slip_lab_f_minp" + _sfx)
with g2:
    name_q = st.text_input("Player / team search", key="slip_lab_f_name" + _sfx, placeholder="e.g. Judge")
with g3:
    only_posted = st.checkbox(f"Only legs {book_label} posts", value=bool(API_KEY) and not is_manual,
                              key="slip_lab_f_posted" + _sfx,
                              help="Hide legs the chosen book doesn't have a line for.")

filtered = [l for l in SL.filter_slot_game(source_legs, slot_pick, game_pick, dh)
            if l["market"] in sel_markets
            and (side_pick == "Both" or l["side"] == side_pick)
            and (not name_q or name_q.lower() in str(l["player"]).lower())
            and (not only_posted or l["at_book"])]
view = [l for l in filtered if l["p"] * 100 >= min_p]
scores = SS.score_lookup(view[:1500]) if view else {}
sort_key = {"Confidence floor": lambda l: -scores.get(l["id"], {}).get("floor", 0.0),
            "Model %": lambda l: -l["p"],
            "EV at this book": lambda l: -(l["ev_pct"] if l["ev_pct"] is not None else -1e9),
            "Edge vs market": lambda l: -(l["edge"] if l["edge"] is not None else -1e9),
            "Conviction": lambda l: -(l["conviction"] if l["conviction"] is not None else -1e9)}[sort_pick]
view.sort(key=sort_key)
shown = view[:300]

if not shown:
    if use_menu and not menu_legs:
        pass
    else:
        st.info("No legs match the current filters — loosen the time slot, game, min hit chance, markets or the "
                f"\"only legs {book_label} posts\" box.")
else:
    pool_df = pd.DataFrame([{
        "Add": False, "Player": l["player"], "Team": l.get("team"), "Game": l.get("game"),
        "Market": l["market"], "Side": l["side"], "Line": l["line"], "Hit chance %": l["p"] * 100,
        "Floor %": scores.get(l["id"], {}).get("floor", float("nan")) * 100, "Basis": _basis(l),
        ("Posts line" if is_pickem else "Price"): (("✓" if l["at_book"] else "—") if is_pickem else l["price"]),
        "Best price": l["best_price"], "Best at": O.book_label(l["best_book"]) if l["best_book"] else None,
        "Market %": None if l["p_mkt"] is None else l["p_mkt"] * 100,
        "Edge (pts)": None if l["edge"] is None else l["edge"] * 100,
        "EV %": l["ev_pct"],
    } for l in shown])
    for col in ("Price", "Best price", "Market %", "Edge (pts)", "EV %", "Floor %"):
        if col in pool_df and not (col == "Price" and is_pickem):
            pool_df[col] = pd.to_numeric(pool_df[col], errors="coerce")
    pool_sig = hashlib.md5("|".join(l["id"] for l in shown).encode()).hexdigest()[:10]
    with st.form("slip_lab_pool_form"):
        edited = st.data_editor(
            pool_df, hide_index=True, height=min(520, 60 + 35 * len(pool_df)),
            key=f"slip_lab_pool_{ver}_{pool_sig}", width="stretch",
            disabled=[c for c in pool_df.columns if c != "Add"],
            column_config={
                "Add": st.column_config.CheckboxColumn("Add", width="small"),
                "Line": st.column_config.NumberColumn(format="%g"),
                "Hit chance %": st.column_config.NumberColumn(format="%.1f"),
                "Floor %": st.column_config.NumberColumn(format="%.1f", help="Low end of the plausible true hit "
                                                         "chance (25th percentile of the model's uncertainty)."),
                "Price": st.column_config.NumberColumn(format="%+d"),
                "Best price": st.column_config.NumberColumn(format="%+d"),
                "Market %": st.column_config.NumberColumn(format="%.1f"),
                "Edge (pts)": st.column_config.NumberColumn(format="%+.1f"),
                "EV %": st.column_config.NumberColumn(format="%+.1f"),
            })
        add_clicked = st.form_submit_button("➕ Add checked legs to slip", type="primary")
    if len(view) > len(shown):
        st.caption(f"Showing the top {len(shown)} of {len(view)} legs — narrow the filters to see the rest.")
    if use_menu:
        st.caption("**Basis** says where the hit chance comes from: *Model* = the model's own number; *Book no-vig* = the "
                   "book's price with its margin removed (no edge by construction); *Book implied\\** = a one-sided "
                   "price, which still includes the margin. Type your own probability into the slip table to test a view.")
    if add_clicked:
        default_stake = float(st.session_state.get("slip_lab_single_stake", 10.0))
        msgs = []
        for idx in edited.index[edited["Add"]]:
            cand = shown[idx]
            why = SL.conflicts(legs, cand)
            if why:
                if not why.startswith("that leg is already"):
                    msgs.append(f"Skipped {SL.leg_label(cand)} — {why}.")
                continue
            if len(legs) >= MAX_LEGS:
                msgs.append(f"A slip holds at most {MAX_LEGS} legs here.")
                break
            legs.append(dict(cand, stake=default_stake))
        for m in msgs:
            st.warning(m)
        st.session_state["slip_lab_ver"] = ver + 1
        st.session_state["slip_lab_result"] = None
        st.rerun()

# --------------------------------------------------------------------------- 1b. suggested tickets
with sugg_box:
    C.section_header("🏆", "Suggested tickets", f"What the model likes at {book_label} — load one to pressure-test it",
                     "#16783c")
    if is_manual:
        st.info("Bet365 has no live prop feed here, so there's nothing to rank — build a slip by hand below.")
    else:
        with st.expander("Suggestion settings", expanded=False):
            t1, t2, t3, t4 = st.columns(4)
            with t1:
                size_opts = [2, 3, 4, 5, 6] if is_pickem else [2, 3, 4, 5]
                sug_sizes = st.multiselect("Ticket sizes (legs)", size_opts, default=[2, 3, 4], key="slip_lab_sug_sizes")
            with t2:
                sug_minp = st.slider("Min hit chance per leg %", 30, 80, 45, 5, key="slip_lab_sug_minp",
                                     help="Legs below this are never put in a ticket.")
            with t3:
                sug_per_game = st.select_slider("Max legs from one game", [1, 2, 3], value=2, key="slip_lab_sug_pg",
                                                disabled=single_game,
                                                help="1 = every leg from a different game (least correlated). Off "
                                                     "while a single game is selected in the Game filter — every "
                                                     "leg has to come from that game.")
            with t4:
                sug_n = st.slider("Singles to list", 3, 10, 5, key="slip_lab_sug_n")
        sug_bank = float(st.session_state.get("slip_lab_bankroll", 1000.0))
        eff_per_game = SS.NO_GAME_CAP if single_game else sug_per_game       # no cap when only one game is in play
        # In the model-priced view the suggestions respect the Markets / Game / Side / search filters above
        # (not the hit-chance slider — they have their own). In the full-menu view they come from the
        # model-priced props in the chosen Time slot / Game (the other menu filters don't apply to them).
        # Either way only legs the MODEL prices are used.
        sug_input = SL.filter_slot_game(pool, slot_pick, game_pick, dh) if use_menu else filtered
        sug_sig = hashlib.md5(json.dumps({
            "b": book, "s": sorted(sug_sizes or []), "m": sug_minp, "g": eff_per_game, "n": sug_n, "bank": sug_bank,
            "legs": [(l["id"], l["p"], l.get("price"), l.get("n_eff"), l.get("at_book"), l.get("p_source"))
                     for l in sug_input]}, sort_keys=True, default=str).encode()).hexdigest()
        cached = st.session_state.get("slip_lab_sugg")
        if cached and cached["sig"] == sug_sig:
            sug = cached["out"]
        else:
            with st.spinner("Ranking legs and building tickets..."):
                sug = SS.suggest_tickets(sug_input, book, sizes=sug_sizes or [2, 3], max_per_game=eff_per_game,
                                         min_leg_p=sug_minp / 100.0, n_singles=sug_n, bankroll=sug_bank)
            st.session_state["slip_lab_sugg"] = {"sig": sug_sig, "out": sug}
        st.session_state["slip_lab_ticket_store"] = {f"t{i}": t for i, t in enumerate(sug["tickets"])}
        st.session_state["slip_lab_single_store"] = {"likely": sug["singles"]["likely"], "value": sug["singles"]["value"]}

        narrow_txt = ""
        if narrowed:
            bits = []
            if slot_pick != SL.ALL_SLOTS:
                bits.append(f"the **{slot_pick}** time slot")
            if game_pick != SL.ALL_GAMES:
                bits.append("**" + game_label.get(game_pick, game_pick.split("|")[0]) + "**")
            narrow_txt = "Narrowed to " + " · ".join(bits) + " by the Time slot / Game filters above. "
        if single_game:
            narrow_txt += ("With one game selected there is no limit on legs from the same game. Legs in one game move "
                           "together: tickets are ranked as if legs were independent, then the numbers shown come from "
                           "the correlated simulation — trust those numbers over the order. ")
        st.caption(narrow_txt
                   + f"Ranked from {sug['eligible']} model-priced leg(s) that {book_label} posts. These are candidates to "
                   "pressure-test, not picks: every number comes from the model, and *confidence floor* shows how much "
                   "each depends on a small sample.")
        wx_lines = SL.game_weather_lines(sug_input, dh)
        if wx_lines:
            st.caption("🌤️ **Why** (below) is the model's own real reasoning for each leg. Real game conditions "
                       "(MLB only) — the model only feeds weather into Batter HR and Batter Total Bases "
                       "probabilities, shown here as context for every game either way:  \n"
                       + "  \n".join(wx_lines))

        def _singles_table(rows, key, title, blurb):
            st.markdown(f"**{title}**")
            st.caption(blurb)
            if not rows:
                st.caption("Nothing qualifies right now.")
                return
            st.dataframe(pd.DataFrame([{
                "Leg": SL.leg_label(r["leg"]), "Hit chance": r["score"]["p"], "Floor": r["score"]["floor"],
                "Price": r["leg"]["price"], "EV %": r["score"]["ev_pct"], "EV at floor %": r["score"]["ev_floor_pct"],
                "Chance +EV": r["score"]["p_ev_pos"], "Suggested stake $": r["stake"], "Grade": r["grade"],
                "Why": SL.leg_why(r["leg"]) or "—",
            } for r in rows]), hide_index=True, width="stretch", column_config={
                "Hit chance": st.column_config.NumberColumn(format="percent"),
                "Floor": st.column_config.NumberColumn(format="percent"),
                "Price": st.column_config.NumberColumn(format="%+d"),
                "EV %": st.column_config.NumberColumn(format="%+.1f"),
                "EV at floor %": st.column_config.NumberColumn(format="%+.1f"),
                "Chance +EV": st.column_config.NumberColumn(format="percent"),
                "Suggested stake $": st.column_config.NumberColumn(format="$%.2f")})
            st.button(f"Load these {len(rows)} as a singles slip", key=f"slip_lab_load_{key}",
                      on_click=_load_singles, args=(key,))

        if not is_pickem:
            _singles_table(sug["singles"]["likely"], "likely", "🎯 Most likely to hit",
                           "Highest confidence floor first. A likely leg isn't necessarily good value — check EV.")
            _singles_table(sug["singles"]["value"], "value", "💎 Best value",
                           "Only legs where the model beats the price, ranked by EV if the leg hits at its floor.")
            st.caption("Suggested stake = quarter-Kelly on the confidence floor, capped at 2% of your bankroll "
                       "(0 = no edge at the floor). Bankroll comes from the box in *Your slip*.")

        st.markdown("**🎫 " + ("Entries" if is_pickem else "Parlays") + "**")
        strat_pick = st.radio("Show", ["All"] + list(SS.STRATEGIES), horizontal=True, key="slip_lab_sug_strat",
                              help=" · ".join(f"{k}: {v}" for k, v in SS.STRATEGIES.items()))
        tickets = [(f"t{i}", t) for i, t in enumerate(sug["tickets"]) if strat_pick == "All" or strat_pick in t["strategies"]]
        if not tickets:
            st.caption("No ticket to show — see the notes below.")
        for key, tk in tickets:
            with st.container(border=True):
                head, btn = st.columns([4, 1.4])
                with head:
                    st.markdown(f"**{SS.ticket_title(tk)}** · " + " · ".join(f"*{s_}*" for s_ in tk["strategies"]))
                with btn:
                    st.button("➕ Load into slip", key=f"slip_lab_load_{key}", on_click=_load_ticket, args=(key,),
                              type="primary")
                st.markdown("  \n".join(
                    f"▸ **{SL.leg_label(l)}** — {l['p'] * 100:.0f}% hit, floor {sug['scores'][l['id']]['floor'] * 100:.0f}%"
                    + ("" if l.get("price") is None else f", {l['price']:+.0f}")
                    + (f" · {l['game']}" if l.get("game") else "")
                    + (f"  \n   *{SL.leg_why(l)}*" if SL.leg_why(l) else "") for l in tk["legs"]))
                tk_wx = SL.game_weather_lines(tk["legs"], dh)
                if tk_wx:
                    st.caption("🌤️ " + "  \n🌤️ ".join(tk_wx))
                ev_show = tk["ev"] if tk["ev"] is not None else tk["ev_indep"]
                pays = (f"{tk['decimal']:.2f}x ({SL.decimal_to_american(tk['decimal']):+d})" if tk["mode"] == "parlay"
                        else f"up to {tk['decimal']:.1f}x")
                bits = [f"**Pays** {pays}",
                        f"**All legs hit** {(tk['p_all'] if tk['p_all'] is not None else tk['p_all_indep']) * 100:.1f}%",
                        f"**EV** {ev_show * 100:+.0f}%"
                        + ("" if tk["ev_haircut"] is None else f" ({tk['ev_haircut'] * 100:+.0f}% if the model is 3 pts high)")]
                if tk["p_ev_positive"] is not None:
                    bits.append(f"**+EV in** {tk['p_ev_positive'] * 100:.0f}% of uncertainty worlds")
                bits.append("**Stake** " + ("—" if not tk["stake"] else f"{tk['stake']:.2f} USD"))
                st.caption(" · ".join(bits))
        for n in sug["notes"]:
            st.caption("ℹ️ " + n)
        st.caption("Parlay prices here multiply each leg's own price; a sportsbook re-prices same-game legs, so "
                   "type the price your slip actually shows into *Your slip* before you rely on the EV.")

# --- manual leg ------------------------------------------------------------------------------
with st.expander("✍️ Add a leg by hand — Bet365, or any line the board doesn't list", expanded=is_manual and not legs):
    st.caption("Type in exactly what your book shows. If the player is on the board, the model's own "
               "recent-game hit rate at your line is filled in for you; otherwise enter your probability.")
    board_players = sorted({pl["Player"] for pl in plays if pl.get("Player")})
    m1, m2, m3, m4 = st.columns([2, 2, 1, 1])
    with m1:
        who = st.selectbox("Player", ["— type a name —"] + board_players, key="slip_lab_m_who")
        typed = st.text_input("Name (if not on the list)", key="slip_lab_m_typed") if who == "— type a name —" else ""
    player_name = typed.strip() if who == "— type a name —" else who
    with m2:
        mk_options = sorted(_active.market_map)
        m_market = st.selectbox("Market", mk_options, key="slip_lab_m_market")
    with m3:
        m_side = st.radio("Side", ["Over", "Under"], key="slip_lab_m_side")
    with m4:
        m_line = st.number_input("Line", value=0.5, step=0.5, key="slip_lab_m_line")
    src_play = next((pl for pl in plays if pl.get("Player") == player_name and pl.get("Market") == m_market
                     and pl.get("_game_log") and pl.get("_stat_key")), None)
    suggested = None
    if src_play is not None:
        vals = [g.get(src_play["_stat_key"]) for g in src_play["_game_log"]]
        p_over = SL.empirical_over_prob([v for v in vals if v is not None], float(m_line))
        if p_over is not None:
            suggested = p_over if m_side == "Over" else 1 - p_over
    m5, m6, m7 = st.columns(3)
    with m5:
        m_prob = st.number_input(
            "Your probability this side hits (%)", 1.0, 99.0,
            float(round((suggested if suggested is not None else 0.5) * 100, 1)), 0.5,
            key=f"slip_lab_m_p_{player_name}_{m_market}_{m_side}_{m_line}",
            help=("Filled from the last games at this line, shrunk toward 50% for small samples."
                  if suggested is not None else "No game log on the board for this player/market — enter your own number."))
    with m6:
        m_price = st.number_input("American price (0 = none)", value=0, step=5, key="slip_lab_m_price")
    with m7:
        game_opts = ["(none)"] + sorted({l["game"] for l in list(pool) + list(menu_legs) if l.get("game")})
        default_game = next((pl.get("Game") for pl in plays if pl.get("Player") == player_name), None)
        m_game = st.selectbox("Game (for correlation)", game_opts,
                              index=game_opts.index(default_game) if default_game in game_opts else 0,
                              key=f"slip_lab_m_game_{player_name}")
    if st.button("➕ Add this leg", key="slip_lab_m_add"):
        if not player_name:
            st.warning("Enter a player name.")
        elif len(legs) >= MAX_LEGS:
            st.warning(f"A slip holds at most {MAX_LEGS} legs here.")
        else:
            leg = SL.manual_leg(player=player_name, market=m_market, side=m_side, line=float(m_line),
                                p=m_prob / 100.0, price=float(m_price) if m_price else None,
                                game=None if m_game == "(none)" else m_game,
                                n_eff=len(src_play["_game_log"]) if src_play is not None else 10.0, book=book,
                                why="entered by hand" if suggested is None else "hit rate at your line, last games")
            if any(x["id"] == leg["id"] for x in legs):
                st.warning("That leg is already on the slip.")
            else:
                leg["stake"] = float(st.session_state.get("slip_lab_single_stake", 10.0))
                legs.append(leg)
                st.session_state["slip_lab_ver"] = ver + 1
                st.session_state["slip_lab_result"] = None
                st.rerun()

# --------------------------------------------------------------------------- 3. the slip
C.section_header("🧾", "Your slip", "Edit a probability or price directly in the table; tick Remove to drop a leg", "#8957e5")
if not legs:
    st.info("Add legs from the pool above (tick the box, then press the button) to start a slip.")
    st.stop()

slip_df = pd.DataFrame([{
    "Leg": SL.leg_label(l), "Game": l.get("game"), "Prob %": l["p"] * 100, "Basis": _basis(l),
    "Price": l.get("price"), "Stake $": l.get("stake") or 10.0,
    "Market %": None if l.get("p_mkt") is None else l["p_mkt"] * 100,
    "Posted": "✓" if l.get("at_book") else "—", "Remove": False,
} for l in legs])
slip_df["Price"] = pd.to_numeric(slip_df["Price"], errors="coerce")
slip_df["Market %"] = pd.to_numeric(slip_df["Market %"], errors="coerce")
slip_edit = st.data_editor(
    slip_df, hide_index=True,
    column_order=["Remove", "Leg", "Prob %"] + ([] if is_pickem else ["Price"]) + ["Stake $", "Basis", "Market %", "Posted", "Game"],
    key=f"slip_lab_slip_{ver}", width="stretch",
    disabled=["Leg", "Game", "Basis", "Market %", "Posted"],
    column_config={
        "Prob %": st.column_config.NumberColumn(min_value=1.0, max_value=99.0, step=0.5, format="%.1f",
                                                help="The chance this leg hits. Edit it to test your own view — a leg "
                                                     "whose number you change is marked Yours."),
        "Price": st.column_config.NumberColumn(format="%+d", help="American price at the chosen book. "
                                               "Type the one your slip shows if it's blank."),
        "Stake $": st.column_config.NumberColumn(min_value=0.0, step=1.0, format="$%.2f",
                                                 help="Used in Singles mode (one stake per leg)."),
        "Market %": st.column_config.NumberColumn(format="%.1f"),
    })
removed = False
for i, row in slip_edit.iterrows():
    if row["Remove"]:
        removed = True
        continue
    leg = legs[i]
    new_p = round(min(0.99, max(0.01, float(row["Prob %"]) / 100.0)), 4)
    if leg.get("source") == "menu" and abs(new_p - leg["p"]) > 1e-9:
        leg["p_source"] = "yours"                       # the user's own number: now a model view, not the book's
        leg["why"] = "your own probability"
    leg["p"] = new_p
    pr = row["Price"]
    leg["price"] = None if pd.isna(pr) or pr == 0 else float(pr)
    leg["stake"] = float(row["Stake $"]) if not pd.isna(row["Stake $"]) else 0.0
    leg["ev_pct"] = (None if leg["price"] is None
                     else round((leg["p"] * O.american_to_decimal(leg["price"]) - 1.0) * 100.0, 2))
if removed:
    keep = [l for l, (_, r) in zip(legs, slip_edit.iterrows()) if not r["Remove"]]
    legs[:] = keep
    st.session_state["slip_lab_ver"] = ver + 1
    st.session_state["slip_lab_result"] = None
    st.rerun()

if is_pickem:
    missing = [SL.leg_label(l) for l in legs if not l.get("at_book")]
    if missing:
        st.warning(f"{book_label} doesn't post these at the line shown: " + "; ".join(missing)
                   + ". Swap them for legs it does post, or the entry can't be placed as built.")

# --- how it pays ------------------------------------------------------------------------------
if is_pickem:
    mode_opts = ["power", "flex"] if book == "prizepicks" else ["pick6"]
else:
    mode_opts = ["parlay", "singles"]
p1, p2, p3 = st.columns([3, 1.3, 1.3])
with p1:
    mode = st.radio("How does this slip pay?", mode_opts, format_func=MODE_LABELS.get, horizontal=False,
                    key="slip_lab_mode")
with p2:
    st.session_state.setdefault("slip_lab_stake_in", 10.0)
    stake = (st.number_input("Stake for the entry ($)", min_value=1.0, step=1.0,
                             key="slip_lab_stake_in") if mode != "singles" else 0.0)
    if mode == "singles":
        st.number_input("Default stake per single ($)", min_value=1.0, value=10.0, step=1.0,
                        key="slip_lab_single_stake", help="Applied to legs you add next; edit any leg's stake in the table.")
with p3:
    bankroll = st.number_input("Bankroll ($)", min_value=10.0, value=1000.0, step=50.0, key="slip_lab_bankroll")

decimal_override = None
table = None
tables_for_drop = {}
if mode == "parlay":
    st.session_state.setdefault("slip_lab_parlay_price", 0)
    typed_price = st.number_input(
        "Parlay price shown on your book's slip (American, 0 = multiply the legs)", step=10,
        key="slip_lab_parlay_price",
        help="Books re-price same-game parlays for correlation. If your slip shows a different price than "
             "the product of the legs, type it here — the pressure test uses it.")
    if typed_price:
        decimal_override = O.american_to_decimal(typed_price)
elif mode in SIM.PAYOUT_TABLES:
    k = len(legs)
    default_tbl = SL.default_table(mode, k)
    with st.expander(f"Payout table for a {k}-pick {mode.title() if mode != 'pick6' else 'Pick6'} entry "
                     "(edit if your promo or state pays differently)", expanded=default_tbl is None):
        if default_tbl is None:
            st.warning(f"No built-in payout for {k} picks — enter the multiplier your app shows.")
            default_tbl = {k: 0.0}
        tbl_df = pd.DataFrame({"Hits": sorted(default_tbl, reverse=True),
                               "Pays (× stake)": [default_tbl[h] for h in sorted(default_tbl, reverse=True)]})
        tbl_edit = st.data_editor(tbl_df, hide_index=True, disabled=["Hits"], key=f"slip_lab_tbl_{mode}_{k}",
                                  column_config={"Pays (× stake)": st.column_config.NumberColumn(min_value=0.0, step=0.1, format="%.2fx")})
        table = {int(r["Hits"]): float(r["Pays (× stake)"]) for _, r in tbl_edit.iterrows()}
        tables_for_drop = {k: table}
        st.caption("Defaults are PrizePicks' standard payouts; they change with promos, state, and goblin/"
                   "demon lines. Pick6 shows base payouts only — Extra Winnings boosts aren't modelled, "
                   "so EV here is conservative." if mode == "pick6" else
                   "Defaults are PrizePicks' standard payouts; they change with promos, state, and goblin/demon lines.")

stakes = [l.get("stake") or 0.0 for l in legs]
payout = SL.slip_payout(mode, legs, decimal_override=decimal_override, table=table,
                        stakes=stakes if mode == "singles" else None)
if payout is None:
    if mode == "parlay" and len(legs) < 2:
        st.info("A parlay needs at least two legs — add another, or switch to Singles.")
    elif mode in ("parlay", "singles"):
        st.info("Every leg needs a price to be priced as a sportsbook slip — type the missing prices into "
                "the table's Price column (or use a different book).")
    else:
        st.info("Add more picks (or fill in the payout table) to price this entry.")
    st.stop()

hl = SL.headline(legs, payout)
ev = hl["ev_per_dollar"]
tiles = [{"icon": "🧮", "value": str(hl["k"]), "label": "Legs"}]
if mode == "singles":
    total = sum(stakes)
    tiles += [{"icon": "💵", "value": f"&#36;{total:,.0f}", "label": "Total staked"},
              {"icon": "📈", "value": f"{ev * 100:+.1f}%", "label": "EV per $1 (independent)",
               "trend": "good" if ev > 0 else "bad"},
              {"icon": "💰", "value": f"{ev * total:+,.2f} USD", "label": "Expected profit"}]
else:
    off = hl.get("offered_decimal")
    tiles += [{"icon": "🎯", "value": _pct(hl["p_all_independent"]), "label": "All legs hit (independent)"},
              {"icon": "🏷️", "value": (f"{off:.2f}x" if off else "table"), "label": "Offered payout"},
              {"icon": "⚖️", "value": (f"{hl['fair_decimal']:.2f}x" if hl.get("fair_decimal") else "—"),
               "label": "Fair payout (model)"},
              {"icon": "📈", "value": f"{ev * 100:+.1f}%", "label": "EV per $1 (independent)",
               "trend": "good" if ev > 0 else "bad"}]
    if hl.get("breakeven_leg_prob"):
        avg_p = sum(l["p"] for l in legs) / len(legs)
        tiles.append({"icon": "🎚️", "value": _pct(hl["breakeven_leg_prob"]),
                      "label": f"Break-even per leg (yours avg {_pct(avg_p, 0)})"})
C.kpi_row(tiles)
st.caption("These are the quick numbers with every leg treated as independent. The pressure test below "
           "adds correlation, model uncertainty and stress scenarios — which is where slips usually change.")

# --------------------------------------------------------------------------- 4. pressure test
C.section_header("🔥", "Pressure test", "Correlated simulation + stress scenarios before you commit", "#f0883e")
with st.expander("Test settings", expanded=False):
    s1, s2, s3 = st.columns(3)
    with s1:
        rho_player = st.slider("Same-player correlation", 0.0, 0.7, 0.30, 0.05, key="slip_lab_rho_p",
                               help="How strongly two legs on the same player move together (e.g. points and "
                                    "3-pointers made). Sign is handled automatically for Over/Under mixes.")
        rho_game = st.slider("Same-game correlation", 0.0, 0.3, 0.08, 0.01, key="slip_lab_rho_g",
                             help="Shared game environment: pace, blowouts, weather.")
    with s2:
        evidence = st.slider("Evidence weight", 0.5, 2.0, 1.0, 0.1, key="slip_lab_evidence",
                             help="1.0 = trust the sample size behind each leg as-is. Lower it to say the model "
                                  "is less reliable than its sample suggests (wider uncertainty).")
        n_sims = st.select_slider("Simulations", [5000, 10000, 20000, 50000], value=20000, key="slip_lab_nsims")
    with s3:
        n_slips = st.slider("Repeat-play length (slips)", 10, 500, 100, 10, key="slip_lab_nslips",
                            help="How many times you'd place this same kind of slip in a row.")

sig = hashlib.md5(json.dumps({
    "book": book, "mode": mode, "stake": stake, "bank": bankroll, "dec": decimal_override, "table": table,
    "legs": [(l["id"], l["p"], l.get("price"), l.get("stake")) for l in legs]}, sort_keys=True, default=str
).encode()).hexdigest()

if st.button("🧪 Run pressure test", type="primary", key="slip_lab_run"):
    with st.spinner("Simulating..."):
        res = SL.run_pressure_test(
            legs, mode, payout, stake=stake, bankroll=bankroll, stakes=stakes if mode == "singles" else None,
            tables=tables_for_drop or None, decimal_override=decimal_override, rho_player=rho_player,
            rho_game=rho_game, evidence_mult=evidence, n_sims=int(n_sims), n_slips=int(n_slips))
    st.session_state["slip_lab_result"] = {"sig": sig, "res": res, "payout_mode": payout["mode"], "k": len(legs)}

stored = st.session_state.get("slip_lab_result")
if not stored:
    st.info("Set up the slip, then press **Run pressure test** — it takes a few seconds.")
elif stored["sig"] != sig:
    st.warning("The slip has changed since the last test — run it again to refresh these results.")

if stored and stored["sig"] == sig:
    res = stored["res"]
    k = res["k"]
    ev_t = "good" if res["ev"] > 0 else "bad"
    C.kpi_row([
        {"icon": "📈", "value": f"{res['ev'] * 100:+.1f}%", "label": "EV per $1 (correlated)", "trend": ev_t},
        {"icon": "✅", "value": _pct(res["p_profit"]), "label": "Chance the slip profits"},
        {"icon": "💥", "value": _pct(res["p_total_loss"]), "label": "Chance of losing the whole stake"},
        {"icon": "🎯", "value": _pct(res["p_all"]),
         "label": f"All {k} hit (independent {_pct(res['p_all_independent'])})"},
        {"icon": "🌐", "value": _pct(res["p_ev_positive"], 0), "label": "Uncertainty worlds where it's +EV",
         "help": "Share of plausible 'true probability' worlds in which this slip has positive EV."},
    ])
    st.caption(f"Model-uncertainty band on EV (5th–95th percentile): {res['ev_p05'] * 100:+.1f}% to "
               f"{res['ev_p95'] * 100:+.1f}%, median {res['ev_p50'] * 100:+.1f}%.")

    for level, text in res["verdict"]:
        {"good": st.success, "warn": st.warning, "bad": st.error, "info": st.info}[level](text)

    t_rank, t_hits, t_stress, t_legs, t_repeat = st.tabs(
        ["🏅 Leg ranking", "📊 Hit distribution", "🌪️ Stress tests", "🔎 Drop a leg", "🔁 Repeat play"])

    with t_rank:
        # Which legs are strongest? Hit chance (simulated) and the confidence floor, side by side.
        sc = SS.leg_scorecard(legs, evidence_mult=res["settings"]["evidence_mult"])
        sim_hit = {l["id"]: h for l, h in zip(legs, res["leg_hit_rate"])}
        drop_effect = {d["leg"]: d["delta_ev"] for d in res["leg_drop"]}
        for r_ in sc:
            r_["sim_hit"] = sim_hit.get(r_["id"], r_["p"])
            r_["effect"] = drop_effect.get(r_["label"]) if res["mode"] != "singles" else None
            r_["grade"] = SS.grade(r_)
        best, worst = sc[0], sc[-1]
        st.success(f"**Strongest leg: {best['label']}** — hits {best['sim_hit'] * 100:.0f}% in the simulation, "
                   f"and even at the low end of the model's uncertainty it's {best['floor'] * 100:.0f}% "
                   f"({best['evidence']} evidence, {best['n_eff']:.0f} games behind it).")
        if len(sc) > 1:
            eff = worst.get("effect")
            tail = ("." if eff is None else
                    f"; the slip is {abs(eff) * 100:.1f} EV-points better without it — worth dropping." if eff < 0 else
                    f"; even so it adds {eff * 100:.1f} EV-points to the slip, so it's still pulling its weight.")
            msg = (f"**Weakest leg: {worst['label']}** — {worst['sim_hit'] * 100:.0f}% to hit, "
                   f"{worst['floor'] * 100:.0f}% at the low end" + tail)
            (st.warning if (eff is not None and eff < 0) else st.info)(msg)
        st.dataframe(pd.DataFrame([{
            "Rank": r_["rank"], "Leg": r_["label"], "Hit chance": r_["sim_hit"], "Confidence floor": r_["floor"],
            "Evidence": r_["evidence"], "Price": r_["price"], "EV %": r_["ev_pct"],
            "EV at floor %": r_["ev_floor_pct"], "Chance price is +EV": r_["p_ev_pos"],
            "Effect on slip (EV pts)": r_["effect"], "Grade": r_["grade"],
        } for r_ in sc]), hide_index=True, width="stretch", column_config={
            "Hit chance": st.column_config.NumberColumn(format="percent"),
            "Confidence floor": st.column_config.NumberColumn(format="percent"),
            "Price": st.column_config.NumberColumn(format="%+d"),
            "EV %": st.column_config.NumberColumn(format="%+.1f"),
            "EV at floor %": st.column_config.NumberColumn(format="%+.1f"),
            "Chance price is +EV": st.column_config.NumberColumn(format="percent"),
            "Effect on slip (EV pts)": st.column_config.NumberColumn(
                format="percent", help="How much EV this leg adds to the slip (negative = the slip is better without it).")})
        fig = go.Figure()
        ordered = list(reversed(sc))
        fig.add_bar(y=[r_["label"] for r_ in ordered], x=[r_["sim_hit"] * 100 for r_ in ordered], orientation="h",
                    name="Hit chance", marker_color="#1f6feb",
                    error_x=dict(type="data", symmetric=False,
                                 array=[(r_["ceiling"] - r_["sim_hit"]) * 100 for r_ in ordered],
                                 arrayminus=[(r_["sim_hit"] - r_["floor"]) * 100 for r_ in ordered]))
        fig.update_layout(height=max(200, 60 + 42 * len(sc)), xaxis_title="Chance the leg hits (%) — whiskers span "
                          "the plausible range", margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
        st.plotly_chart(fig, width="stretch")
        st.caption("Read this table with one fact in mind: a leg's simulated hit chance is the model's own probability — "
                   "the simulation can't make a leg likelier than the model says. What separates the rows is the "
                   "**confidence floor** (a number resting on few games can sit far below its headline), whether the "
                   "**price is still +EV** across the plausible range, and how much each leg **adds to or drags** the "
                   "slip. Legs priced off the book's own probabilities (Basis: Book) have no edge to rank.")

    with t_hits:
        xs = [f"{h} hit{'s' if h != 1 else ''}" for h in range(k + 1)]
        fig = go.Figure()
        fig.add_bar(x=xs, y=[v * 100 for v in res["hit_dist"]], name="Simulated (correlated)")
        fig.add_bar(x=xs, y=[v * 100 for v in res["hit_dist_independent"]], name="If legs were independent",
                    opacity=0.6)
        fig.update_layout(barmode="group", yaxis_title="Probability (%)", height=340,
                          margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.12))
        st.plotly_chart(fig, width="stretch")
        rows = []
        for h in range(k + 1):
            if payout["mode"] == "parlay":
                pays = payout["decimal"] if h == k else 0.0
            elif payout["mode"] == "table":
                pays = payout["table"].get(h, 0.0)
            else:
                pays = None
            rows.append({"Hits": h, "Simulated": res["hit_dist"][h], "Independent": res["hit_dist_independent"][h],
                         **({"Pays (× stake)": pays} if pays is not None else {})})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
            "Simulated": st.column_config.NumberColumn(format="percent"),
            "Independent": st.column_config.NumberColumn(format="percent"),
            "Pays (× stake)": st.column_config.NumberColumn(format="%.2fx")})
        st.caption("Correlation fattens both tails: more all-or-nothing outcomes than independence predicts. "
                   "For an all-must-hit slip that usually helps the joint hit rate when legs are positively linked.")

    with t_stress:
        st.dataframe(pd.DataFrame([{
            "Scenario": s["scenario"], "EV per $1": s["ev"], "Chance of profit": s["p_profit"],
            "All legs hit": s["p_all"],
            "EV 5th pct": s.get("ev_p05"), "EV 95th pct": s.get("ev_p95"),
        } for s in res["scenarios"]]), hide_index=True, width="stretch", column_config={
            "EV per $1": st.column_config.NumberColumn(format="percent"),
            "Chance of profit": st.column_config.NumberColumn(format="percent"),
            "All legs hit": st.column_config.NumberColumn(format="percent"),
            "EV 5th pct": st.column_config.NumberColumn(format="percent"),
            "EV 95th pct": st.column_config.NumberColumn(format="percent")})
        if not any("no-vig" in s["scenario"] for s in res["scenarios"]):
            st.caption("The \"book is right\" row needs a two-sided price on every leg (an anytime-scorer leg or "
                       "a leg no book posted both sides of doesn't have one), so it's left out for this slip.")
        st.caption("Every scenario reuses the same random draws, so differences between rows are the "
                   "scenario itself, not simulation noise. \"Too bullish\" subtracts that many points from every "
                   "leg's probability. \"Book is right\" replaces the model with the book's own no-vig probability "
                   "where it posted both sides.")

    with t_legs:
        if res["mode"] == "singles":
            st.dataframe(pd.DataFrame([{"Leg": d["leg"], "Stand-alone EV per $1": d["delta_ev"]}
                                       for d in res["leg_drop"]]), hide_index=True, width="stretch",
                         column_config={"Stand-alone EV per $1": st.column_config.NumberColumn(format="percent")})
        else:
            st.dataframe(pd.DataFrame([{
                "Leg": d["leg"], "EV without it": d["ev_without"], "Chance of profit without it": d["p_profit_without"],
                "EV points it adds": d["delta_ev"]} for d in res["leg_drop"]]),
                hide_index=True, width="stretch", column_config={
                    "EV without it": st.column_config.NumberColumn(format="percent"),
                    "Chance of profit without it": st.column_config.NumberColumn(format="percent"),
                    "EV points it adds": st.column_config.NumberColumn(format="percent",
                                                                       help="Negative = the slip is better without this leg.")})
            st.caption("Each row re-prices the slip without that leg (a typed-in parlay price can't be re-derived, "
                       "so the smaller slip uses the product of its remaining legs' own prices)."
                       if decimal_override else
                       "Each row re-prices the slip without that leg. A negative last column means the slip "
                       "does better without it.")

    with t_repeat:
        rp = res["repeat"]
        xs = list(range(len(rp["fan"][50])))
        fig = go.Figure()
        fig.add_scatter(x=xs, y=rp["fan"][95], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip")
        fig.add_scatter(x=xs, y=rp["fan"][5], mode="lines", line=dict(width=0), fill="tonexty",
                        fillcolor="rgba(31,111,235,0.15)", name="5th–95th percentile")
        fig.add_scatter(x=xs, y=rp["fan"][75], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip")
        fig.add_scatter(x=xs, y=rp["fan"][25], mode="lines", line=dict(width=0), fill="tonexty",
                        fillcolor="rgba(31,111,235,0.30)", name="25th–75th percentile")
        fig.add_scatter(x=xs, y=rp["fan"][50], mode="lines", line=dict(color="#1f6feb", width=2), name="Median")
        fig.add_hline(y=1.0, line_dash="dot", line_color="#9aa4b2")
        fig.update_layout(height=360, xaxis_title="Slips placed", yaxis_title="Bankroll (× starting)",
                          margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.12))
        st.plotly_chart(fig, width="stretch")
        dd = rp["p_drawdown"]
        C.kpi_row([
            {"icon": "🏁", "value": _pct(rp["p_ahead"], 0), "label": f"Ahead after {rp['n_slips']} slips",
             "trend": "good" if rp["p_ahead"] >= 0.5 else "bad"},
            {"icon": "📉", "value": _pct(rp["final_p05"] - 1, 0), "label": "Worst 5% of runs (P&L)"},
            {"icon": "📊", "value": _pct(rp["final_p50"] - 1, 0), "label": "Median run (P&L)"},
            {"icon": "🌊", "value": _pct(dd.get(0.4, 0), 0), "label": "Ever down 40% from peak"},
        ])
        st.caption(f"Simulated at {rp['stake_fraction'] * 100:.1f}% of bankroll per slip, "
                   f"{rp['n_slips']} slips in a row, each path drawing its own \"true\" probabilities so "
                   "model uncertainty compounds the way it really does. Not a staking recommendation.")

    st.caption(f"Settings used: same-player ρ {res['settings']['rho_player']:.2f}, same-game ρ "
               f"{res['settings']['rho_game']:.2f}, evidence weight {res['settings']['evidence_mult']:.1f}, "
               f"{res['settings']['n_sims']:,} sims. Pressure-testing checks how fragile the model's edge is; "
               "it can't tell you the model is right. This is analysis, not betting advice.")

# --------------------------------------------------------------------------- 5. lock it in
C.section_header("🔒", "Lock it in", "Send the tested slip to the Bet Log", "#16783c")
if stored and stored["sig"] == sig:
    st.caption("This exact slip has been pressure-tested.")
else:
    st.caption("Tip: run the pressure test on this exact slip before logging it.")
if is_pickem:
    st.caption("Pick'em entries have no per-leg price — the Bet Log will record the model's own fair price "
               "for each pick; edit the entry stake/payout there after logging.")
tested_stake = (f"\\${sum(stakes):,.2f} across the singles" if mode == "singles" else f"\\${stake:,.2f} entry")
st.caption(f"You tested a {tested_stake} — the stake below is filled in to match (change it if you like). Each leg is "
           "logged at the price on your slip (the table above), not re-looked-up, so what you tested is what gets recorded.")
if any(l.get("kind") in SL.TEAM_KINDS or "(alt)" in str(l.get("market")) for l in legs):
    st.caption("Team, game-total and alternate-line legs are logged like any other, but the Bet Log can't "
               "auto-settle them yet — mark those won or lost there.")
# The logging widget opens on the slip you just tested: every leg ticked, the right mode, the tested stake.
_prefill_sig = hashlib.md5(json.dumps([mode, stake, stakes, [l["id"] for l in legs]], default=str).encode()).hexdigest()
if st.session_state.get("slip_lab_prefill_sig") != _prefill_sig:
    st.session_state["slip_lab_prefill_sig"] = _prefill_sig
    st.session_state.update(SL.quick_log_prefill("slip_lab", mode, stake, stakes, len(legs)))
# offers=None on purpose: every leg already carries the price it was tested at (or none, which logs the
# model's own fair price), so the Bet Log must not go looking for a different book's price to substitute.
quick_log.render_quick_log(SL.legs_to_plays(legs), date_str, SPORT_KEY, key_prefix="slip_lab",
                           expanded=True, is_parlay=(mode != "singles"), offers=None)
