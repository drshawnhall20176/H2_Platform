"""
UFC Fight Card — tonight's bouts with odds and fight duration. Phase 1: data surface only,
no model. Community members pick fighters; the page shows the odds context and implied
probabilities so picks are grounded rather than pure gut.

What the community was doing manually (Baby J posting Erceg at -115, everyone
tailing without context) is replaced with a structured fight card showing:
- Each bout's moneyline with implied probability for each fighter
- Fight duration over/under
- Which fights are on the early card vs. main card

Method of victory odds (KO/TKO, Submission, Decision) are NOT currently shown -- confirmed
live that The Odds API rejects these markets for MMA with a real INVALID_MARKET error; its own
docs describe current MMA coverage as fight-winner odds "with more markets on the way," not a
subscription-tier limit. See ufc_engine.py's own module docstring for the full reasoning. The
display code for this already exists and activates automatically the moment the API adds
support -- re-enabling it later is a one-line change in ufc_engine.UFC_MARKETS, not a rebuild.

Phase 2: conviction scoring from community pick aggregation + historical
fighter finishing rate will follow once the data layer is proven live.
"""
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import components as C

import sports
from sports import require_sport

require_sport("UFC")

import ufc_engine as E
import quick_log
from odds_api import american_to_decimal, US_BOOKS

C.base_css()
C.page_header("🥊", "UFC Fight Card",
             "Tonight's bouts — odds, implied probabilities, and method of victory lines. "
             "Phase 1: data surface. Model conviction scores coming in Phase 2.")

# ── API key check ──────────────────────────────────────────────────────────
try:
    api_key = st.secrets.get("ODDS_API_KEY") or os.environ.get("ODDS_API_KEY")
except Exception:
    api_key = os.environ.get("ODDS_API_KEY")

if not api_key:
    st.warning("No ODDS_API_KEY configured — UFC odds require the same API key as MLB/NFL. "
               "Add it to your Streamlit secrets to enable this page.")
    st.stop()

# ── Date picker ───────────────────────────────────────────────────────────
eastern = datetime.now(E._EASTERN)
target = st.date_input("Event date", eastern)
date_str = target.strftime("%Y-%m-%d")

# ── Book selector ─────────────────────────────────────────────────────────
book_keys = list(US_BOOKS.keys())
book_labels = [US_BOOKS[k] for k in book_keys]
preferred_label = st.selectbox("📖 Sportsbook", book_labels,
                               index=book_keys.index("draftkings") if "draftkings" in book_keys else 0)
preferred_book = book_keys[book_labels.index(preferred_label)]

# ── Load fight card ───────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def load_card(date_str: str, api_key: str):
    return E.get_ufc_events(api_key, date_str)

try:
    with st.spinner("Loading fight card..."):
        events = load_card(date_str, api_key)
except E.OddsAPIError as e:
    st.error(f"⚠️ Odds API error while loading the fight card: {e}")
    st.caption("This is a real API failure (bad key, rate limit, or an unsupported market for "
              "this event/date) — not \"no events scheduled.\" If this persists, check the "
              "message above against The Odds API's own error code reference.")
    st.stop()

if not events:
    # Nov 7: this used to show a hard-coded July 25 Abu Dhabi card as a "demo", which read as the platform being stale.
    # Now: say plainly there's nothing on this date, and offer the dates that do have bouts.
    st.info(f"No MMA bouts are listed for {target:%a %b %-d}. Completed bouts drop out of the odds feed, so a card "
            "that already finished won't show here.")
    try:
        _upcoming = [d for d in E.card_dates(api_key) if d >= datetime.now(E._EASTERN).strftime("%Y-%m-%d")][:6]
    except Exception:                                           # noqa: BLE001
        _upcoming = []
    if _upcoming:
        st.markdown("**Upcoming card dates:** " + " · ".join(
            datetime.strptime(d, "%Y-%m-%d").strftime("%a %b %-d") for d in _upcoming) + " — pick one above.")
    st.stop()

st.success(f"Found {len(events)} bout{'s' if len(events) != 1 else ''} on the card for {target:%a %b %-d}.")


# ── The whole card at a glance (Nov 7): one odds request for every bout, earliest first ──
@st.cache_data(ttl=600, show_spinner=False)
def load_card_odds(date_str: str, api_key: str):
    return E.get_card(api_key, date_str)


try:
    _card = load_card_odds(date_str, api_key)
except Exception as _exc:                                       # noqa: BLE001
    _card = []
    st.caption(f"Couldn't load the card's prices in one call ({str(_exc)[:80]}); each bout below loads its own.")
if _card:
    _main_only = st.toggle("Main cards only (bouts a major US sportsbook prices — the UFC card)", value=True,
                           key="ufc_main_only",
                           help="The odds feed lists every MMA promotion; regional shows are priced only by offshore "
                                "books. Also drops a stale listing when a fighter's opponent changed.")
    _all_n = len(_card)
    if _main_only:
        _card = E.main_card_only(_card) or _card
        _main_ids = {b["id"] for b in _card}
        events = [e for e in events if e.get("id") in _main_ids] or events
        if len(_card) < _all_n:
            st.caption(f"Showing {len(_card)} of {_all_n} listed bouts; {_all_n - len(_card)} from smaller promotions hidden.")

    def _fmt(v):
        return "—" if v is None else f"{float(v):+.0f}"

    _rows = []
    for b in _card:
        fav_a = b["p_a"] is not None and b["p_a"] >= 0.5
        _rows.append({"Time (ET)": pd.to_datetime(b["commence"]).tz_convert("America/New_York").strftime("%-I:%M %p"),
                      "Bout": f"{b['a']} vs {b['b']}",
                      "Favorite": "—" if b["p_a"] is None else (b["a"] if fav_a else b["b"]),
                      "Market chance": None if b["p_a"] is None else (b["p_a"] if fav_a else 1 - b["p_a"]),
                      "Best price, 1st named": _fmt(b["best_a"]), "Best price, 2nd named": _fmt(b["best_b"]),
                      f"Moneyline ({preferred_label})": E.book_lines(b, preferred_book)["ml"],
                      f"Spread ({preferred_label})": E.book_lines(b, preferred_book)["spread"],
                      f"Total rounds ({preferred_label})": E.book_lines(b, preferred_book)["total"],
                      "Books": b["books"]})
    _df = pd.DataFrame(_rows)
    st.dataframe(_df, hide_index=True, width="stretch",
                 column_config={"Market chance": st.column_config.NumberColumn(
                     format="percent", help="The books' no-vig chance for the favorite (median across books).")})
    st.caption("The whole card from one odds request, earliest bout first. **Market chance** is what the books' prices "
               "imply with the vig removed — there's no UFC model yet, so it's the market's read, not a pick. Moneyline, "
               "spread and total rounds are the selected book's (another book's when it hasn't posted one). Method of "
               "victory, KO/TKO-only, submission-only, significant strikes, takedowns and round props aren't in the "
               "odds feed the platform uses, so they can't show here — check them at the book. Each bout's detail is below.")

# ── Per-fight odds ────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def load_bout_odds(event_id: str, api_key: str, book: str):
    event_data = E.get_event_odds(event_id, api_key, book=book)
    try:    # keep the pre-fight prices for the morning review (fail-soft; never blocks the page)
        import ufc_review as UR
        import model_store as MS
        if not UR._started(event_data.get("commence_time"), datetime.now(timezone.utc)):
            MS.save_ufc_odds([UR.record_from_event(event_data)])
    except Exception:                                           # noqa: BLE001
        pass
    return E.parse_bout_odds(event_data, preferred_book=book)

def _impl_prob(american: float) -> float:
    """Implied probability from American odds (includes vig)."""
    d = american_to_decimal(american)
    return round(1 / d, 3) if d > 0 else 0.0

def _no_vig_prob(odds_a: float, odds_b: float):
    """Remove vig and return fair probabilities for a two-outcome market."""
    p_a = _impl_prob(odds_a)
    p_b = _impl_prob(odds_b)
    total = p_a + p_b
    if total <= 0:
        return p_a, p_b
    return round(p_a / total, 3), round(p_b / total, 3)

def _fmt_american(v) -> str:
    if v is None:
        return "—"
    return f"+{int(v)}" if int(v) > 0 else str(int(v))

def _prob_bar(prob: float, label: str, color: str):
    """Simple inline probability display."""
    pct = f"{prob*100:.0f}%"
    return f"**{label}** — {pct} implied"

# Main card first (API returns main event first)
st.divider()
C.section_header("🎯", "Fight Card")

for i, event in enumerate(events):
    fighter_a = event.get("home_team", "Fighter A")
    fighter_b = event.get("away_team", "Fighter B")
    commence = event.get("commence_time", "")
    event_id = event.get("id", "")

    # Parse ET time
    try:
        dt = datetime.strptime(commence[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        et = dt.astimezone(E._EASTERN)
        time_str = et.strftime("%-I:%M %p ET")
    except Exception:
        time_str = "TBD"

    card_label = "🏆 Main Event" if i == 0 else (
                 "⭐ Co-Main Event" if i == 1 else f"Bout {i + 1}")

    with st.expander(f"{card_label} · {fighter_a} vs. {fighter_b} · {time_str}", expanded=(i < 3)):

        try:
            with st.spinner("Loading odds..."):
                odds = load_bout_odds(event_id, api_key, preferred_book)
        except E.OddsAPIError as e:
            st.warning(f"⚠️ Odds API error for this bout: {e}")
            st.caption("A real API failure, not \"no odds posted yet\" — if this is an "
                      "INVALID_MARKET error, one of this platform's requested markets "
                      "(h2h/totals/method-of-victory) isn't yet supported for this specific "
                      "event; tell Claude the exact message above so the request can be "
                      "narrowed to what's actually available.")
            continue

        if not odds:
            st.caption("No odds available yet for this bout.")
            continue

        # ── Moneyline ─────────────────────────────────────────────────────
        h2h = odds.get("h2h") or {}
        odds_a = h2h.get(fighter_a)
        odds_b = h2h.get(fighter_b)

        if odds_a is not None and odds_b is not None:
            p_a, p_b = _no_vig_prob(odds_a, odds_b)
            favorite = fighter_a if p_a > p_b else fighter_b
            underdog = fighter_b if p_a > p_b else fighter_a
            fav_prob = max(p_a, p_b)
            dog_prob = min(p_a, p_b)
            fav_odds = odds_a if p_a > p_b else odds_b
            dog_odds = odds_b if p_a > p_b else odds_a

            col1, col2 = st.columns(2)
            with col1:
                st.metric(label=f"🔵 {favorite} (Favorite)",
                          value=_fmt_american(fav_odds),
                          delta=f"{fav_prob*100:.0f}% implied (no-vig)")
            with col2:
                st.metric(label=f"🔴 {underdog} (Underdog)",
                          value=_fmt_american(dog_odds),
                          delta=f"{dog_prob*100:.0f}% implied (no-vig)")

            # Bet logging -- ADDED DIRECTLY ON REQUEST. Reuses the SAME shared quick_log widget
            # every other page already uses (Best Bets, Graded Picks, Game Watch's own moneyline
            # logging above), by building a team-level "play" dict (Player=None, Market=
            # "Moneyline") rather than a whole separate logging system for UFC specifically.
            #
            # This page is explicitly "Phase 1: data surface only, no model" (see this file's
            # own module docstring) -- there is no real model price to log as a fallback "Fair"
            # the way Game Watch's own win-probability estimate provides. Using the real, live
            # h2h odds already fetched for THIS SAME bout for both roles here is the honest
            # choice, not a compromise: "Fair" is the real market price (there's no separate
            # model number to prefer over it), and "ModelProb" is the real no-vig probability
            # already computed above for the metrics themselves, not a fabricated prediction.
            # bout_moneylines is built from this exact same real fetch, so quick_log's own real-
            # price lookup will always find a genuine match here -- never the Fair fallback,
            # since the "Fair" value already IS the real price in this specific case.
            bout_moneylines = {fighter_a: {preferred_book: odds_a}, fighter_b: {preferred_book: odds_b}}
            ml_plays = [
                {"Player": None, "PlayerId": None, "Game": f"{fighter_a} vs. {fighter_b}",
                 "Market": "Moneyline", "Side": fighter_a, "Line": None,
                 "Fair": odds_a, "ModelProb": p_a},
                {"Player": None, "PlayerId": None, "Game": f"{fighter_a} vs. {fighter_b}",
                 "Market": "Moneyline", "Side": fighter_b, "Line": None,
                 "Fair": odds_b, "ModelProb": p_b},
            ]
            quick_log.render_quick_log(ml_plays, date_str, "UFC", key_prefix=f"ufc_{event_id}",
                                       moneylines=bout_moneylines)

        # ── Point Spread (Nov 7) ───────────────────────────────────────────
        spreads, sp_pts = odds.get("spreads") or {}, odds.get("_spread_points") or {}
        if spreads and sp_pts:
            st.markdown("**➗ Point Spread**")
            _sc = st.columns(len(spreads))
            for _col, (_name, _price) in zip(_sc, spreads.items()):
                _pt = sp_pts.get(_name)
                _col.metric(_name, f"{_pt:+g}" if _pt is not None else "—", _fmt_american(_price), delta_color="off")

        # ── Fight Duration ─────────────────────────────────────────────────
        totals = odds.get("totals") or {}
        total_point = odds.get("_total_point")
        if totals and total_point is not None:
            over_odds = totals.get("Over")
            under_odds = totals.get("Under")
            st.markdown(f"**⏱️ Fight Duration — {total_point} Rounds**")
            dcol1, dcol2 = st.columns(2)
            with dcol1:
                st.metric("Over (goes to distance)", _fmt_american(over_odds))
            with dcol2:
                st.metric("Under (early finish)", _fmt_american(under_odds))

            # Bet logging -- ADDED DIRECTLY ON REQUEST, extending the same real logging already
            # wired for Moneyline above to this second real market. Same honest choice as
            # Moneyline: no separate model price exists for this page yet, so the real, live
            # totals odds already shown above are used directly as "Fair", and the real no-vig
            # probability (the same real helper the Moneyline metrics above already use) stands
            # in for "ModelProb" rather than a fabricated number.
            #
            # Genuinely different market shape from Moneyline, not a copy-paste: Over/Under
            # isn't a "team name" pick real_moneyline_price can match against, so there's no
            # separate moneylines-style lookup here -- the real, already-fetched odds ARE the
            # entry price directly, with no further lookup needed or possible.
            if over_odds is not None and under_odds is not None:
                p_over, p_under = _no_vig_prob(over_odds, under_odds)
                dur_plays = [
                    {"Player": None, "PlayerId": None, "Game": f"{fighter_a} vs. {fighter_b}",
                     "Market": "Fight Duration", "Side": "Over", "Line": total_point,
                     "Fair": over_odds, "ModelProb": p_over},
                    {"Player": None, "PlayerId": None, "Game": f"{fighter_a} vs. {fighter_b}",
                     "Market": "Fight Duration", "Side": "Under", "Line": total_point,
                     "Fair": under_odds, "ModelProb": p_under},
                ]
                quick_log.render_quick_log(dur_plays, date_str, "UFC", key_prefix=f"ufc_dur_{event_id}")

        # ── Method of Victory ─────────────────────────────────────────────
        # Real, registered canonical market names (sports.py's own UFC market_map), NOT the
        # emoji-prefixed display labels in `methods` below -- bet logging needs the same real
        # market name every other logged pick on this platform uses, not a display-only string.
        method_market_names = {
            "🤛 KO/TKO": "Win by KO/TKO", "🤸 Submission": "Win by Sub", "📋 Decision": "Win by Decision",
        }
        methods = {
            "🤛 KO/TKO":    odds.get("fighter_wins_by_ko_tko") or {},
            "🤸 Submission": odds.get("fighter_wins_by_submission") or {},
            "📋 Decision":  odds.get("fighter_wins_by_decision") or {},
        }

        has_method = any(m for m in methods.values())
        if has_method:
            st.markdown("**Method of Victory**")
            method_rows = []
            method_plays = []
            for method_label, method_odds in methods.items():
                if not method_odds:
                    continue
                for fighter, o in method_odds.items():
                    if o is not None:
                        method_rows.append({
                            "Method": method_label,
                            "Fighter": fighter,
                            "Odds": _fmt_american(o),
                            "Implied %": f"{_impl_prob(o)*100:.0f}%",
                        })
                        # Bet logging -- ADDED DIRECTLY ON REQUEST, dormant until the Odds API
                        # actually supports these markets (see this file's own module docstring
                        # on the real, confirmed INVALID_MARKET rejection) -- gated behind the
                        # exact same has_method/method_odds checks that already gate the display
                        # above, so this activates automatically the moment real data exists,
                        # with no further changes needed here. Each (method, fighter) is its own
                        # independent real proposition, not a two-sided market like Moneyline or
                        # Fight Duration (KO/TKO and Submission for the SAME fighter aren't
                        # opposite sides of one bet), so this is one play per real, priced
                        # outcome, not a paired Over/Under or head-to-head shape. "Fair" is the
                        # real, live method-of-victory odds directly, same honest choice as
                        # every other market on this page; "ModelProb" uses the real implied
                        # probability already computed for the display table above (WITH vig,
                        # since a real no-vig removal needs the other real outcomes for this
                        # exact fighter+method combination, which aren't independently offered
                        # here) -- an honest, clearly-labeled approximation, not a fabricated one.
                        method_plays.append({
                            "Player": None, "PlayerId": None,
                            "Game": f"{fighter_a} vs. {fighter_b}",
                            "Market": method_market_names[method_label], "Side": fighter,
                            "Line": None, "Fair": o, "ModelProb": _impl_prob(o),
                        })
            if method_rows:
                mdf = pd.DataFrame(method_rows)
                st.dataframe(mdf, hide_index=True, width="stretch")
                quick_log.render_quick_log(method_plays, date_str, "UFC", key_prefix=f"ufc_method_{event_id}")

        # ── Community Pick Helper ──────────────────────────────────────────
        # Phase 1: show what the odds say, let community add conviction
        if odds_a is not None and odds_b is not None:
            st.caption(
                f"**Reading the market:** {fighter_a} {_fmt_american(odds_a)} / "
                f"{fighter_b} {_fmt_american(odds_b)} — "
                f"the market gives {favorite} a {fav_prob*100:.0f}% chance (no-vig). "
                f"Log your pick in the Bet Log to track CLV vs. where this closes."
            )

# ── Footer ──────────────────────────────────────────────────────────────
st.divider()
st.caption("📊 Odds from The Odds API — same source as MLB/NFL Edge Board. "
           "Implied probabilities are no-vig (vig removed from the two-sided market). "
           "Method of victory markets aren't shown yet — The Odds API's own current MMA "
           "coverage doesn't include them, not a subscription-tier limit; this will light up "
           "automatically once they add support. Phase 2 will add finishing rate history and "
           "conviction scoring against the community's own pick distribution.")
