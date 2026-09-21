"""
Slip Lab — build a slip from one book's REAL lines, then pressure-test it before you lock it in.

The flow, top to bottom:
  1. Pick a slate date and a book (DraftKings, FanDuel, Hard Rock Bet, PrizePicks, DK Pick6, Bet365 ...).
  2. The leg pool is the same board Best Bets already computed (same model probabilities, same real
     Odds API lines) with THIS book's price on each side — or, for a pick'em app, whether the app
     posts the line at all. Bet365 has no US prop feed on The Odds API, so there you type the line
     and price in by hand.
  3. Add legs, pick how the slip pays (parlay / singles / PrizePicks Power or Flex / Pick6), and see
     the instant independent-legs math.
  4. "Run pressure test": correlated Monte Carlo (same-player and same-game legs move together),
     model-uncertainty worlds, overconfidence haircuts, "the book is right" scenario, leg-by-leg
     drop analysis and a repeat-play bankroll projection — then a plain-language read.
  5. Lock it in to the Bet Log with the same widget every other page uses.

All the math lives in slip_lab.py / slip_sim.py (unit-tested); this file is layout only.
"""

import hashlib
import json
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import pytz
import streamlit as st

import components as C
import styling  # noqa: F401  (installs the theme-proof styles)
import best_bets_data as BBD
import odds_api as O
import quick_log
import slip_lab as SL
import slip_sim as SIM
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

# Switching book re-prices the legs already on the slip from the new book's real prices.
if st.session_state.get("slip_lab_book_seen") != book:
    st.session_state["slip_lab_book_seen"] = book
    for i, leg in enumerate(legs):
        fresh = pool_by_id.get(leg["id"])
        if fresh is not None and leg.get("source") == "board":
            legs[i] = dict(fresh, p=leg["p"], stake=leg.get("stake"))
        elif leg.get("source") == "board":
            legs[i] = dict(leg, price=None, at_book=False, book=book)
    st.session_state["slip_lab_ver"] = ver = ver + 1

# --------------------------------------------------------------------------- 2. leg pool
C.section_header("🎯", "Leg pool", f"Every prop on the board, priced at {book_label}", "#1f6feb")

markets_present = sorted({l["market"] for l in pool})
games_present = sorted({l["game"] for l in pool if l.get("game")})
f1, f2, f3, f4 = st.columns([2, 2, 1.3, 1.7])
with f1:
    sel_markets = st.multiselect("Markets", markets_present,
                                 default=[m for m in (_active.default_markets or markets_present) if m in markets_present]
                                 or markets_present, key="slip_lab_f_markets")
with f2:
    game_pick = st.selectbox("Game", ["All games"] + games_present, key="slip_lab_f_game")
with f3:
    side_pick = st.radio("Side", ["Both", "Over", "Under"], horizontal=True, key="slip_lab_f_side")
with f4:
    sort_pick = st.selectbox("Sort by", ["Model %", "EV at this book", "Edge vs market", "Conviction"],
                             key="slip_lab_f_sort")
g1, g2, g3 = st.columns([2, 2, 2])
with g1:
    min_p = st.slider("Min model %", 0, 95, 50, 5, key="slip_lab_f_minp")
with g2:
    name_q = st.text_input("Player search", key="slip_lab_f_name", placeholder="e.g. Judge")
with g3:
    only_posted = st.checkbox(f"Only legs {book_label} posts", value=bool(API_KEY) and not is_manual,
                              key="slip_lab_f_posted",
                              help="Hide legs the chosen book doesn't have a line for.")

view = [l for l in pool
        if l["market"] in sel_markets
        and (game_pick == "All games" or l.get("game") == game_pick)
        and (side_pick == "Both" or l["side"] == side_pick)
        and l["p"] * 100 >= min_p
        and (not name_q or name_q.lower() in str(l["player"]).lower())
        and (not only_posted or l["at_book"])]
sort_key = {"Model %": lambda l: -l["p"],
            "EV at this book": lambda l: -(l["ev_pct"] if l["ev_pct"] is not None else -1e9),
            "Edge vs market": lambda l: -(l["edge"] if l["edge"] is not None else -1e9),
            "Conviction": lambda l: -(l["conviction"] if l["conviction"] is not None else -1e9)}[sort_pick]
view.sort(key=sort_key)
shown = view[:300]

if not shown:
    st.info("No legs match the current filters — loosen the min model %, markets or the "
            f"\"only legs {book_label} posts\" box.")
else:
    pool_df = pd.DataFrame([{
        "Add": False, "Player": l["player"], "Team": l.get("team"), "Game": l.get("game"),
        "Market": l["market"], "Side": l["side"], "Line": l["line"], "Model %": l["p"] * 100,
        ("Posts line" if is_pickem else "Price"): (("✓" if l["at_book"] else "—") if is_pickem else l["price"]),
        "Best price": l["best_price"], "Best at": O.book_label(l["best_book"]) if l["best_book"] else None,
        "Market %": None if l["p_mkt"] is None else l["p_mkt"] * 100,
        "Edge (pts)": None if l["edge"] is None else l["edge"] * 100,
        "EV %": l["ev_pct"],
    } for l in shown])
    for col in ("Price", "Best price", "Market %", "Edge (pts)", "EV %"):
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
                "Model %": st.column_config.NumberColumn(format="%.1f"),
                "Price": st.column_config.NumberColumn(format="%+d"),
                "Best price": st.column_config.NumberColumn(format="%+d"),
                "Market %": st.column_config.NumberColumn(format="%.1f"),
                "Edge (pts)": st.column_config.NumberColumn(format="%+.1f"),
                "EV %": st.column_config.NumberColumn(format="%+.1f"),
            })
        add_clicked = st.form_submit_button("➕ Add checked legs to slip", type="primary")
    if len(view) > len(shown):
        st.caption(f"Showing the top {len(shown)} of {len(view)} legs — narrow the filters to see the rest.")
    if add_clicked:
        default_stake = float(st.session_state.get("slip_lab_single_stake", 10.0))
        have = {l["id"] for l in legs}
        msgs = []
        for idx in edited.index[edited["Add"]]:
            cand = shown[idx]
            if cand["id"] in have:
                continue
            twin = [x for x in legs if (x["player"], x["market"], x["line"]) == (cand["player"], cand["market"], cand["line"])]
            if twin:
                msgs.append(f"Skipped {SL.leg_label(cand)} — the slip already has the other side of that prop.")
                continue
            if len(legs) >= MAX_LEGS:
                msgs.append(f"A slip holds at most {MAX_LEGS} legs here.")
                break
            legs.append(dict(cand, stake=default_stake))
            have.add(cand["id"])
        for m in msgs:
            st.warning(m)
        st.session_state["slip_lab_ver"] = ver + 1
        st.session_state["slip_lab_result"] = None
        st.rerun()

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
        game_opts = ["(none)"] + games_present
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
    "Leg": SL.leg_label(l), "Game": l.get("game"), "Model %": l["p"] * 100,
    "Price": l.get("price"), "Stake $": l.get("stake") or 10.0,
    "Market %": None if l.get("p_mkt") is None else l["p_mkt"] * 100,
    "Posted": "✓" if l.get("at_book") else "—", "Remove": False,
} for l in legs])
slip_df["Price"] = pd.to_numeric(slip_df["Price"], errors="coerce")
slip_df["Market %"] = pd.to_numeric(slip_df["Market %"], errors="coerce")
slip_edit = st.data_editor(
    slip_df, hide_index=True, column_order=["Remove", "Leg", "Model %"] + ([] if is_pickem else ["Price"]) + ["Stake $", "Market %", "Posted", "Game"], key=f"slip_lab_slip_{ver}", width="stretch",
    disabled=["Leg", "Game", "Market %", "Posted"],
    column_config={
        "Model %": st.column_config.NumberColumn(min_value=1.0, max_value=99.0, step=0.5, format="%.1f"),
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
    leg["p"] = round(min(0.99, max(0.01, float(row["Model %"]) / 100.0)), 4)
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
    stake = (st.number_input("Stake for the entry ($)", min_value=1.0, value=10.0, step=1.0,
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
    typed_price = st.number_input(
        "Parlay price shown on your book's slip (American, 0 = multiply the legs)", value=0, step=10,
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

    t_hits, t_stress, t_legs, t_repeat = st.tabs(
        ["📊 Hit distribution", "🌪️ Stress tests", "🔎 Leg by leg", "🔁 Repeat play"])

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
st.caption(f"You tested a {tested_stake} — enter the same stake below. Each leg is logged at the price on your "
           "slip (the table above), not re-looked-up, so what you tested is what gets recorded.")
# offers=None on purpose: every leg already carries the price it was tested at (or none, which logs the
# model's own fair price), so the Bet Log must not go looking for a different book's price to substitute.
quick_log.render_quick_log(SL.legs_to_plays(legs), date_str, SPORT_KEY, key_prefix="slip_lab",
                           expanded=True, is_parlay=(mode != "singles"), offers=None)
