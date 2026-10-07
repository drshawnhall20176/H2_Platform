"""
Media Room — curated "selections we found interesting," built for a podcast/Discord segment.
 
Not picks, not locks, not advice. Each selection shows the side/line, the plain-English CASE
(the model's reasoning), and an honest value read. Two modes:
  • Conviction (free)      — ranks by how far the model diverges from a typical line; shows fair price.
  • Live value (uses odds) — ranks by real EV% against live prices, identical math to the Edge Board.
Plays whose opposing starter is undetermined (TBD) are excluded — the matchup can't be priced.
(For WNBA this filter is a harmless no-op — see selections.filter_known_pitcher's docstring.)
"""
 
import os
 
import streamlit as st
import components as C
from datetime import datetime  # noqa
 
import sports
import odds_api as O
import selections as SEL
import retro as R
import best_bets_data as BBD
import media_focus as MF
import promotions as PR

_active = sports.active()

# UFC is outcome-based -- Media Room's discussion hooks and content generation
# are built on counting-stat projections that don't exist for UFC.
if not _active.has_projections:
    C.base_css()
    C.page_header("📣", "H2 Sports Media", "Curated plays with the reasoning, ready for the show")
    st.info("🥊 Media Room content generation doesn't apply to UFC — the discussion hooks "
            "and analysis are built on player stat projections. Head to **UFC Fight Card** "
            "for tonight's bouts and odds.")
    st.stop()
E, P = _active.engine, _active.projections

if not sports.require_live_engine("Media Room"):
    st.stop()

C.base_css()
st.markdown("""
<style>
.sel-card {background:#1a1f2b;border:1px solid #2d3344;border-left:5px solid #7c3aed;
           border-radius:10px;padding:14px 18px;margin-bottom:12px;}
.sel-card h4 {margin:0 0 6px;font-size:17px;color:#f8fafc;}
.sel-card .case {color:#c7ccd6;font-size:14px;margin:2px 0;}
.sel-card .rc {color:#9aa4b2;font-size:13px;font-style:italic;margin-top:6px;}
.sel-badge {display:inline-block;background:#7c3aed;color:#fff;font-size:12px;
            padding:2px 9px;border-radius:999px;margin-left:6px;vertical-align:middle;}
.sel-val {display:inline-block;background:#16783c;color:#f8fafc;font-size:12px;
          padding:2px 9px;border-radius:999px;margin-left:6px;vertical-align:middle;}
</style>
""", unsafe_allow_html=True)
 
C.page_header("📣", f"H2 Sports Media — Selections  ·  {_active.icon} {_active.label}",
             "Curated plays we found interesting, with the reasoning — ready for the show and the Discord")
 
SIDE_PHRASE = {
    ("Batter HR", "Over"): "to homer", ("Batter Total Bases", "Over"): "Over 1.5 total bases",
    ("Batter Total Bases", "Under"): "Under 1.5 total bases", ("Batter Total Hits", "Over"): "to record a hit",
    ("Batter Total Hits", "Under"): "to be held hitless", ("Batter Strikeouts", "Over"): "to strike out",
    ("Batter Strikeouts", "Under"): "to avoid the K", ("Pitcher Strikeouts", "Over"): "Over on strikeouts",
    ("Pitcher Strikeouts", "Under"): "Under on strikeouts", ("Pitcher Outs", "Over"): "Over on outs",
    ("Pitcher Outs", "Under"): "Under on outs", ("Pitcher Walks", "Over"): "Over on walks",
    ("Pitcher Walks", "Under"): "Under on walks",
    ("Points", "Over"): "Over on points", ("Points", "Under"): "Under on points",
    ("Rebounds", "Over"): "Over on rebounds", ("Rebounds", "Under"): "Under on rebounds",
    ("Assists", "Over"): "Over on assists", ("Assists", "Under"): "Under on assists",
    ("Threes Made", "Over"): "Over on threes", ("Threes Made", "Under"): "Under on threes",
    ("Anytime TD", "Over"): "to score a touchdown", ("First TD Scorer", "Over"): "to score the first TD",
    ("Last TD Scorer", "Over"): "to score the last TD", ("Passing TDs", "Over"): "Over on passing TDs",
    ("Pass Attempts", "Over"): "Over on pass attempts", ("Rush Attempts", "Over"): "Over on rush attempts",
}
# Yes/no touchdown-scorer markets read "Anytime", not "Over 0.5".
_YES_NO_MARKETS = {"Anytime TD", "First TD Scorer", "Last TD Scorer"}
 
 
def line_label(p):
    if p.get("Market") in _YES_NO_MARKETS:
        return {"Anytime TD": "Anytime", "First TD Scorer": "First TD", "Last TD Scorer": "Last TD"}[p["Market"]]
    return f"{p['Side']} {p['Line']:g}"
 
 
def headline(p):
    verb = SIDE_PHRASE.get((p["Market"], p["Side"]), f"{p['Side']} {p['Line']:g}")
    vs = f" vs {p['Opp']}" if p.get("Opp") else ""
    return f"{p['Player']} ({p['Team']}) {verb}{vs}"
 
 
def value_text(p):
    if p.get("EV") is not None:
        live = f"{p['LivePrice']:+.0f}" if p.get("LivePrice") is not None else "—"
        return f"Live value: {p['EV']:+.1f}% at {live} ({p['Book']})." if p.get("Book") else \
               f"Live value: {p['EV']:+.1f}% at {live}."
    # A real captured price may already be sitting on this play (RealPrice, from the same
    # already-fetched board data build_mlb_board uses -- no extra Odds API cost, unlike the
    # dedicated "Live value" EV fetch above) even in this free/Conviction mode. Show it directly
    # instead of the old blanket "prices not checked" disclaimer, which was true before RealPrice
    # existed but isn't always true anymore.
    if p.get("PriceSource") == "book" and p.get("RealPrice") is not None:
        book_str = f" ({p['RealPriceBook']})" if p.get("RealPriceBook") else ""
        return f"Real price: {p['RealPrice']:+.0f}{book_str}."
    fair = f"{p['Fair']:+.0f}" if p.get("Fair") is not None else "—"
    return f"Fair price ~{fair} (model estimate — flip on Live value for a live EV% read)."
 
 
def reality_check(p):
    prob = f"{p['ModelProb']*100:.0f}%"
    return (f"Reality check: model ~{prob} to cash — a lean we found interesting, not a lock. "
            + value_text(p) + " Only worth backing if you beat the number.")
 
 
def get_key():
    try:
        return st.secrets["ODDS_API_KEY"]
    except Exception:
        return os.environ.get("ODDS_API_KEY")
 
 


@st.cache_data(ttl=300, show_spinner=False)
def load_plays_mlb(date_str, ev_mode, book):
    """Every candidate play for the slate (NOT yet curated — curation happens per game/day below).
    Same shared pipeline as before (BBD.build_mlb_board: real lines/prices for the chosen book, no
    duplicate logic). `book` is part of the cache key on purpose — see build_mlb_board's docstring."""
    import statcast_data as SC

    fip_constant = E.FIP_CONSTANT_DEFAULT
    api_key = get_key()
    rows, meta, plays, _books = BBD.build_mlb_board(date_str, fip_constant, odds_api_key=api_key,
                                                    preferred_book=book)
    plays = SEL.filter_known_pitcher(plays)   # drop TBD-pitcher plays
    sc, k = SC.load_cached()                  # shared platform-wide cache (see its docstring)

    ev_used = False
    if ev_mode:
        key = get_key()
        if key:
            index = P.build_projection_index(rows, meta, statcast=sc, statcast_k=k)
            markets = sorted(set(SEL.MARKET_TO_ODDS_KEY.values()))
            offers, _ = O.fetch_slate_props(date_str, key, markets)
            edges, _ = O.compute_edges(index, offers)
            SEL.attach_live_ev(plays, edges)
            plays = [p for p in plays if p.get("EV") is not None]
            ev_used = True
    return plays, meta, ev_used


@st.cache_data(ttl=300, show_spinner=False)
def load_plays_generic(sport_key, date_str, ev_mode, book):
    """Same shared board every other page uses (BBD.load_generic_best_bets_board — real lines/prices
    for the chosen book, one cached odds fetch shared across pages), so a selection's price here is
    the one Best Bets shows."""
    sport = sports.get(sport_key)
    engine, proj = sport.engine, sport.projections
    plays, meta, _books = BBD.load_generic_best_bets_board(sport_key, date_str, book)
    plays = SEL.filter_known_pitcher(plays)

    ev_used = False
    if ev_mode and sport.has_projections:
        key = get_key()
        if key:
            rows, _meta = engine.build_slate(date_str)
            index = proj.build_projection_index(rows, meta)
            offers, _ = O.fetch_slate_props(date_str, key, sport.markets, sport=sport.odds_sport_key)
            edges, _ = O.compute_edges(index, offers, projections_module=proj)
            SEL.attach_live_ev(plays, edges, market_map=sport.market_map)
            plays = [p for p in plays if p.get("EV") is not None]
            ev_used = True
    return plays, meta, ev_used


@st.cache_data(ttl=300, show_spinner=False)
def load_td_pool(sport_key, date_str, book):
    """Anytime-TD plays for EVERY eligible player (including those under the typical-rate cutoff that
    Best Bets drops) — the field for TD promotions and the player check. [] for sports without one."""
    sport = sports.get(sport_key)
    proj = sport.projections
    if not sport.has_projections or not hasattr(proj, "build_td_pool"):
        return []
    rows, _meta = sport.engine.build_slate(date_str)
    offers, key = [], get_key()
    if key and sport.markets:
        try:
            offers = BBD.fetch_generic_offers(sport_key, date_str, key)
        except Exception:
            offers = []
    return proj.build_td_pool(rows, offers=offers, preferred_book=book)


_pool_state = {}


def get_td_pool():
    """Today's TD pool, loaded once per run and only when something needs it."""
    if "pool" not in _pool_state:
        with st.spinner("Loading every player's touchdown profile..."):
            allp = load_td_pool(_active.key, date_str, board_book)
        _pool_state["pool"] = MF.plays_on_date(allp, date_str)
    return _pool_state["pool"]


c_date, c_book = st.columns([1, 2])
with c_date:
    target = st.date_input("Slate date", MF.today_eastern())
date_str = target.strftime("%Y-%m-%d")
C.season_notice(_active.key, date_str)   # NBA preseason / early-season data warning (no-op otherwise)

# Book selector — the same 📖 Book pick Slip Lab uses (every sportsbook + the pick'em apps + Bet365).
# It sets whose prices the selections show AND whose promotions are suggested below.
_label_to_key = {label: key for key, label in O.ALL_BOOKS.items()}
_labels = list(_label_to_key)
_pref = st.session_state.get(f"_preferred_book_{_active.key.lower()}", O.DEFAULT_BOOK)
_default_label = O.ALL_BOOKS.get(_pref, O.ALL_BOOKS.get(O.DEFAULT_BOOK, "DraftKings"))
with c_book:
    book_label = st.selectbox(
        "📖 Book", _labels, index=_labels.index(_default_label) if _default_label in _labels else 0,
        key="media_room_book_selector",
        help="Prices on the selections come from this book where it posts them, and the promotions "
             "section suggests plays for what this book is running. PrizePicks and DK Pick6 post a "
             "line only; Bet365 has no live US prop feed here.")
book = _label_to_key[book_label]
# The board is always priced against a real sportsbook feed: the chosen book when it is one,
# DraftKings' otherwise (pick'em apps and Bet365 have no two-sided prices to show).
board_book = book if book in O.US_BOOKS else O.DEFAULT_BOOK
if board_book != book:
    st.caption(f"**{book_label}** has no two-sided sportsbook prices here — selections show "
               f"{O.ALL_BOOKS[board_book]} prices; the promotions below are for {book_label}.")

c2, c3, c4 = st.columns([1, 1, 2])
with c2:
    n = st.slider("How many selections", 5, 8, 6)
with c3:
    cap = st.slider("Max per market", 1, 3, 2)
with c4:
    ev_mode = st.toggle("Rank by live value (uses odds quota)", value=False,
                        help="On: pulls live prices and ranks by real EV% (same math as the Edge Board). "
                             "Off: ranks by model conviction and shows fair price — no odds spent.")

with st.spinner("Curating selections..."):
    if _active.key == "MLB":
        all_plays, meta, ev_used = load_plays_mlb(date_str, ev_mode, board_book)
    else:
        all_plays, meta, ev_used = load_plays_generic(_active.key, date_str, ev_mode, board_book)

# --- the day's games: a weekly slate (NFL/NCAAF) is narrowed to the chosen date -----------------
day_plays = MF.plays_on_date(all_plays, date_str)
games = MF.games_on_date(meta, day_plays, date_str)
n_games = len(games)

if not games or not day_plays:
    msg = ("No live-value plays cleared the filters today." if (ev_mode and games)
           else "No games on this date. Pick a date with scheduled games.")
    st.info(msg)
    other = MF.other_days_with_games(meta, date_str)
    if other:
        st.caption("This slate has games on: " + ", ".join(other) + " — pick one of those dates.")
    st.stop()

rank_key = "EV" if ev_used else "Conviction"
st.markdown(f"### 🗓️ {MF.slate_phrase(games, date_str, _active.key)}")

# Time slot + Game — the same pair every other page carries: the slot buckets games by real Eastern
# start time, the game list is chronological with the start time shown, and both default to everything.
_slot_opts = MF.slot_options(games)
if st.session_state.get("media_room_slot") not in _slot_opts:      # a stale pick can't outlive its option
    st.session_state["media_room_slot"] = MF.ALL_SLATE
fs1, fs2 = st.columns(2)
with fs1:
    slot_pick = st.selectbox("Time slot", _slot_opts, key="media_room_slot")
_game_opts = MF.game_options(games, slot_pick)
_game_label = dict(_game_opts)
_game_keys = [MF.ALL_GAMES_IN_SLOT] + [k for k, _ in _game_opts]
if st.session_state.get("media_room_game") not in _game_keys:
    st.session_state["media_room_game"] = MF.ALL_GAMES_IN_SLOT
with fs2:
    game_pick = st.selectbox("Game", _game_keys, key="media_room_game",
                             format_func=lambda k: _game_label.get(k, k))
focus_games = MF.select_games(games, slot_pick, game_pick)
focus_plays = [p for g in focus_games for p in MF.plays_for_game(day_plays, g)]
if n_games == 1:
    st.caption(f"Only one game on the ticket — the whole segment is built around "
               f"**{games[0]['matchup']}**.")
elif len(focus_games) == 1:
    st.caption(f"Segment built around **{focus_games[0]['matchup']}** ({focus_games[0]['time_text']}).")
breakdown = False
if len(focus_games) > 1:
    breakdown = st.toggle("Break it down game by game", value=len(focus_games) <= 6,
                          help="On: the top selections for each game, in kickoff order. "
                               "Off: the top selections across the whole day.")

# --- build the sections: [(heading, [plays])] --------------------------------------------------
if breakdown:
    sections = [(f"{g['matchup']} · {g['time_text']}", picks) for g, picks in
                MF.curate_per_game(focus_plays, focus_games, P.curate_selections,
                                   per_game=3, per_market_cap=cap, rank_key=rank_key)]
else:
    head = (f"{focus_games[0]['matchup']} · {focus_games[0]['time_text']}" if len(focus_games) == 1
            else "Top selections across the day")
    sections = [(head, P.curate_selections(focus_plays, n=n, per_market_cap=cap, rank_key=rank_key))]
sel = [p for _h, picks in sections for p in picks]

if not sel:
    st.info("No selections cleared the filters for this focus.")

mode_label = "ranked by **live EV%**" if ev_used else "ranked by **model conviction** (prices not checked)"
st.caption(f"{n_games} game{'s' if n_games != 1 else ''} on the ticket · {len(sel)} selections · "
           f"{mode_label} · TBD-pitcher plays excluded")
if ev_mode and not ev_used:
    st.warning("Live value is on but no Odds API key was found — showing conviction instead. Add "
               "ODDS_API_KEY in secrets to enable live EV.", icon="⚠️")

# --- result lights: grade past-date selections by the pick's SIDE and LINE -----------------
# Only for finalized (past) dates — today's games have no results, so no lights are shown.
# Graded via retro.grade_play so a 🟢/🔴 matches how the Retrospective and Bet Log score:
# an Under is 🟢 only if the player stayed UNDER the line, not if he "did something".
_is_past = target < MF.today_eastern()
_results = {}
if _is_past:
    try:
        _results = E.get_player_results(date_str)
    except Exception:
        _results = {}
_graded_on = _is_past and bool(_results)


def result_mark(p):
    """🟢 hit / 🔴 miss / 🟡 no result (didn't appear), or '' when the date isn't finalized."""
    if not _graded_on:
        return ""
    hit = R.grade_play(p["Market"], p["Side"], p.get("Line"), _results.get(p.get("PlayerId")))
    return "🟢" if hit is True else "🔴" if hit is False else "🟡"


if _graded_on:
    _marks = [result_mark(p) for p in sel]
    _h, _m, _p = _marks.count("🟢"), _marks.count("🔴"), _marks.count("🟡")
    _tally = f"🟢 {_h}  ·  🔴 {_m}" + (f"  ·  🟡 {_p}" if _p else "")
    st.markdown(f"### 🚦 Selection scorecard — {_tally}")
    if _h + _m:
        st.caption(f"The model went **{_h}-for-{_h + _m}** on {date_str}'s selections "
                   f"(graded by the pick's side and line). 🟡 = player didn't appear / no result.")
elif _is_past:
    st.caption("🚦 Results for this date aren't available to grade yet.")

# --- on-screen cards -------------------------------------------------------
_i = 0
for heading, picks in sections:
    if breakdown or len(focus_games) == 1:
        st.markdown(f"#### 🏟️ {heading}")
    if not picks:
        st.caption("Nothing we love in this one — a fine thing to say on the show.")
    for p in picks:
        _i += 1
        val = (f"<span class='sel-val'>{p['EV']:+.1f}% EV</span>" if p.get("EV") is not None else "")
        mark = result_mark(p)
        mark_html = f"{mark} " if mark else ""
        st.markdown(
            f"""<div class="sel-card">
            <h4>{mark_html}{_i}. {headline(p)} <span class="sel-badge">{p['Market']} · {line_label(p)}</span>{val}</h4>
            <div class="case"><b>The case:</b> {p['Why']}.</div>
            <div class="rc">{reality_check(p)}</div>
            </div>""", unsafe_allow_html=True)

# --- sportsbook promotions (for the book picked above) ---------------------------------------
C.section_header("💰", f"{book_label} promotions")
st.caption("Promo terms change weekly and this page can't read a sportsbook's live promo page — "
           "these come from a hand-kept list of recurring promos plus any you add. Switch on the ones "
           "actually running for this slate, and confirm the terms in the book's app.")
if "custom_promos" not in st.session_state:
    st.session_state["custom_promos"] = []
available = PR.catalog_for(_active.key, st.session_state["custom_promos"], book=book, date_str=date_str)
_weekday = target.strftime("%A")

with st.expander(f"➕ Add a {book_label} promotion that's running (this session only)"):
    with st.form("add_promo", clear_on_submit=True):
        pname = st.text_input("Promotion name", placeholder="Anytime TD boost")
        pkind = st.selectbox("What kind of picks fit it?", list(PR.KINDS),
                             format_func=lambda k: {"longest_td": "Longest TD", "anytime_td": "Anytime TD",
                                                    "first_td": "First TD scorer", "last_td": "Last TD scorer",
                                                    "first_last_td": "First/Last TD pool",
                                                    "boost": "Profit boost (best-priced plays)",
                                                    "sgp": "Same-game parlay",
                                                    "info": "Just mention it (no picks)"}[k])
        psum = st.text_area("How it works (your words)", height=70)
        if st.form_submit_button("Add promotion"):
            try:
                st.session_state["custom_promos"].append(
                    PR.make_custom_promo(book, pname, _active.key, pkind, psum))
                st.rerun()
            except ValueError as e:
                st.error(str(e))

promo_lines = []
if not available:
    others = sorted({O.ALL_BOOKS.get(p["book"], p["book"]) for p in
                     PR.catalog_for(_active.key, st.session_state["custom_promos"], date_str=date_str)})
    msg = f"No {book_label} promotions on file for {_active.label} on a {_weekday}."
    if others:
        msg += " On file for this day: " + ", ".join(others) + " — switch the 📖 Book above to see them."
    st.info(msg + f" If {book_label} is running something, add it above and the model will suggest who fits.")
    if O.is_pickem_book(book):
        st.caption("Pick'em apps post a fixed line and pay by entry multiplier — use the selections above as "
                   "candidates, and check each line in the app before using it.")
else:
    by_id = {p["id"]: p for p in available}
    live_ids = st.multiselect("Promotions running for this slate", list(by_id), default=list(by_id),
                              key=f"media_room_promos_{book}_{date_str}_{len(st.session_state['custom_promos'])}",   # a newly added promo starts switched on
                              format_func=lambda i: by_id[i]["name"])
    for pid in live_ids:
        promo = by_id[pid]
        st.markdown(f"#### 🎰 {book_label} — {promo['name']}")
        st.markdown(f"{promo.get('summary') or 'See the book for terms.'}")
        st.caption(f"Source: {promo.get('source', '')} · {promo.get('note', '')}")
        promo_lines += [f"🎰 {PR.promo_blurb(promo, book_label)}", f"   ⚠️ {promo.get('note', '')}"]
        _, _, how = PR.KINDS[promo["kind"]]
        any_picks = False
        for g in focus_games:
            gplays = MF.plays_for_game(focus_plays, g)
            if PR.KINDS[promo["kind"]][0] == [PR.ANYTIME_TD]:
                # The whole field, not just the players above the typical-rate cutoff (see build_td_pool).
                gplays = MF.plays_for_game(get_td_pool(), g) or gplays
            picks = PR.promo_picks(gplays, promo, n=4 if promo["kind"] == "sgp" else 3)
            if not picks:
                continue
            any_picks = True
            ghead = f"{g['matchup']} · {g['time_text']}"
            st.markdown(f"**Who we like for it — {ghead}** <span style='color:#9aa4b2'>({how})</span>",
                        unsafe_allow_html=True)
            promo_lines.append(f"   Who we like — {ghead}:")
            for k, pk in enumerate(picks, 1):
                st.markdown(f"{k}. {PR.pick_line(pk)}")
                promo_lines.append(f"     {k}) {PR.pick_line(pk)}")
        if not any_picks and promo["kind"] != "info":
            st.caption("The model has no priced candidates for this promotion in the chosen game(s).")
        if promo["kind"] in ("longest_td", "first_last_td"):
            st.caption("Popularity isn't measured — \"likely a popular name\" just means one of the model's "
                       "three likeliest scorers. Not a lock, not advice; bet responsibly.")
        promo_lines.append("")

# --- player check ----------------------------------------------------------------------------
C.section_header("🔎", "Check a player")
st.caption("Type a name to see how he fits King of the End Zone — chance to score, big-play ability, where he "
           "ranks in his game, and the caveats. Searches every player on the day's slate.")
check_lines = []
_q = st.text_input("Player", placeholder="e.g. Devaughn Vele", key="media_room_player_check")
if _q.strip():
    _pool = get_td_pool()
    if not _pool:
        st.info(f"The player check isn't available for {_active.label} yet.")
    else:
        _hits = PR.find_players(_q, _pool)
        if not _hits:
            st.warning(f"No player matching \"{_q.strip()}\" on this day's slate with a touchdown market. "
                       f"Check the spelling, or the player may not meet the model's playing-time floor.")
        for _p in _hits:
            _game_pool = [x for x in _pool if x["Game"] == _p["Game"] and x["GameDate"] == _p["GameDate"]]
            _pf = PR.player_profile(_p, _game_pool, first_td_plays=day_plays)
            _pl = PR.profile_lines(_pf)
            st.markdown(f"**{_pl[0]}**")
            for _line in _pl[1:]:
                st.markdown(_line)
            check_lines += _pl + [""]

# --- copy-all block --------------------------------------------------------
C.section_header("📋", "Copy for the show / Discord")
st.caption("One click the copy icon (top-right of the block) to grab the whole segment.")
lines = [f"🎙️ H2 Sports Media — Selections we found interesting · {date_str}",
         MF.slate_phrase(games, date_str, _active.key),
         f"📖 Prices/promotions: {book_label}",
         f"({'live value' if ev_used else 'model conviction — prices not checked'})", ""]
if _graded_on and (_h + _m):
    lines.append(f"🚦 Scorecard: {_h}-for-{_h + _m}  ({_tally})")
    lines.append("")
_i = 0
for heading, picks in sections:
    if breakdown or len(focus_games) == 1:
        lines += [f"🏟️ {heading}", ""]
    for p in picks:
        _i += 1
        mark = result_mark(p)
        prefix = f"{mark} " if mark else ""
        lines.append(f"{prefix}{_i}) {headline(p)}  [{p['Market']} · {line_label(p)}]")
        lines.append(f"   The case: {p['Why']}.")
        lines.append(f"   {reality_check(p)}")
        lines.append("")
if promo_lines:
    lines += [f"💰 {book_label} promotions", ""] + promo_lines
if check_lines:
    lines += ["🔎 Player check", ""] + check_lines
lines.append("⚖️ For entertainment. Selections we found interesting with our reasoning — not locks "
             "and not betting advice. Variance is real; always check the price and bet responsibly.")
st.code("\n".join(lines), language=None)
