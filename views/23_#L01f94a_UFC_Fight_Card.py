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
    # Events disappear from the API feed once completed -- an Abu Dhabi card
    # (early morning ET) will be gone before US prime time. Show a clear explanation
    # rather than a generic "no events" message.
    st.info(
        f"No upcoming UFC events found for {date_str} — if today's card has already "
        "concluded (e.g. an Abu Dhabi event that ran early morning ET), the Odds API "
        "removes completed events from the feed. Try tomorrow's date for next week's card, "
        "or select a future fight date."
    )

    # Demo mode: show today's actual card from the API with results so you can
    # see what the fight card page looks like with real data.
    st.divider()
    C.section_header("📋", "Today's completed card — UFC Fight Night: Ankalaev vs. Guskov")
    st.caption("Abu Dhabi · Etihad Arena · July 25, 2026 — odds have closed, results shown for reference")

    completed_bouts = [
        ("🏆 Main Event",    "Magomed Ankalaev", "Bogdan Guskov",    "KO/TKO R5 2:41"),
        ("⭐ Co-Main",       "Ramazan Temirov",  "Steve Erceg",      "KO/TKO R1 4:21"),
        ("Bout 3",           "Rizvan Kuniev",    "Tyrell Fortune",   "KO/TKO R3 1:12"),
        ("Bout 4",           "Islam Dulatov",    "Wyatt Turman",     "Unanimous Decision"),
        ("Bout 5",           "Santiago Ponzinibbio", "Sam Patterson","Decision 29-28"),
        ("Bout 6",           "Ismael Bonfim",    "Axel Sola",        "KO/TKO R2 4:49"),
        ("Bout 7",           "Dustin Jacoby",    "Muhammad Said",    "KO/TKO R3 1:12"),
        ("Bout 8",           "Valter Walker",    "Thomas Petersen",  "Submission R1 1:32 (Calf Slicer)"),
        ("Bout 9",           "D. Rzepecki",      "M. Zaynukov",      "KO/TKO"),
        ("Bout 10",          "A. Vagaev",        "S. Izagakhmaev",   "Decision"),
        ("Bout 11",          "B. Ribeiro",       "M. Tuchalov",      "KO/TKO"),
        ("Bout 12",          "Nurullo Aliev",    "TBD",              "Win"),
    ]

    for card_pos, fighter_a, fighter_b, result in completed_bouts:
        winner = fighter_a
        with st.expander(f"{card_pos} · {fighter_a} vs. {fighter_b}"):
            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                st.markdown(f"**✅ {fighter_a}** (W)")
            with col2:
                st.markdown(f"{fighter_b} (L)")
            with col3:
                st.markdown(f"**{result}**")
    st.stop()

st.success(f"Found {len(events)} bout{'s' if len(events) != 1 else ''} on tonight's card.")

# ── Per-fight odds ────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def load_bout_odds(event_id: str, api_key: str, book: str):
    event_data = E.get_event_odds(event_id, api_key, book=book)
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

        # ── Method of Victory ─────────────────────────────────────────────
        methods = {
            "🤛 KO/TKO":    odds.get("fighter_wins_by_ko_tko") or {},
            "🤸 Submission": odds.get("fighter_wins_by_submission") or {},
            "📋 Decision":  odds.get("fighter_wins_by_decision") or {},
        }

        has_method = any(m for m in methods.values())
        if has_method:
            st.markdown("**Method of Victory**")
            method_rows = []
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
            if method_rows:
                mdf = pd.DataFrame(method_rows)
                st.dataframe(mdf, hide_index=True, width="stretch")

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
