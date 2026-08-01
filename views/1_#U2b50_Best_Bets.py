"""
Best Bets — the model's strongest leans across the whole slate, with reasoning.
"""

import streamlit as st
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import components as C
import pandas as pd
from datetime import datetime
import pytz

import sports
import best_bets_data as BBD
import grading
import quick_log

_active = sports.active()
E, P = _active.engine, _active.projections

C.base_css()
C.page_header("⭐", "Best Bets",
             f"The model's strongest leans across the slate — ranked, reasoned, and by time slot "
             f"— {_active.icon} {_active.label}")

if not sports.require_live_engine("Best Bets"):
    st.stop()

eastern = pytz.timezone("US/Eastern")
game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER   # now shared — see sports.py


@st.cache_data(ttl=300, show_spinner=False)
def load_best_bets_mlb(date_str: str, fip_constant: float, preferred_book: str,
                       venue_split=None, time_split=None):
    plays, meta, available_books = BBD.load_mlb_best_bets_board(
        date_str, fip_constant, preferred_book, venue_split, time_split)
    slot_by_game = {m["label"]: (game_dt(m.get("game_date")), m.get("venue")) for m in meta}
    for pl in plays:
        dt, _ = slot_by_game.get(pl["Game"], (None, None))
        pl["Slot"] = slot_of(dt)
        pl["Time"] = dt.strftime("%I:%M %p").lstrip("0") + " ET" if dt else "TBD"
    return plays, meta, available_books


@st.cache_data(ttl=300, show_spinner=False)
def load_best_bets_generic(sport_key: str, date_str: str):
    """Any sport whose engine/projections don't need MLB's statcast/weather enrichment path —
    currently NFL, WNBA, and any future sport built the same way."""
    plays, meta, available_books = BBD.load_generic_best_bets_board(sport_key, date_str)
    slot_by_game = {m["label"]: game_dt(m.get("game_date")) for m in meta}
    for pl in plays:
        dt = slot_by_game.get(pl["Game"])
        pl["Slot"] = slot_of(dt)
        pl["Time"] = dt.strftime("%I:%M %p").lstrip("0") + " ET" if dt else "TBD"
    return plays, meta, available_books


# --- controls ---------------------------------------------------------------
# Load first (to get the real available_books from tonight's API response),
# then render the selector with the real list. On the very first load, session
# state is empty so the selector shows all books as a fallback; after the load
# completes and stores the real list, a rerun updates the selector automatically.
if _active.key == "MLB":
    c1, c2, c3 = st.columns([3, 1, 2])
    with c1: target = st.date_input("Slate date", datetime.now())
    with c2: fip_constant = st.number_input("FIP constant", value=E.FIP_CONSTANT_DEFAULT, step=0.01)
    date_str = target.strftime("%Y-%m-%d")
    with c3: preferred_book = BBD.render_book_selector(key_prefix="best_bets", date_str=date_str)
    venue_split, time_split = BBD.render_split_selector(key_prefix="best_bets")
    with st.spinner("Scanning the slate..."):
        plays, meta, available_books = load_best_bets_mlb(
            date_str, fip_constant, preferred_book, venue_split, time_split)
    # Guarantees THIS session's own quick_log real-price side-channel is populated, regardless
    # of whether load_best_bets_mlb above was a cache hit for this session specifically -- see
    # ensure_mlb_offers_session_state's own docstring for the real, confirmed cross-session bug
    # this fixes. Called here, in genuinely uncached top-level page code, not inside any
    # @st.cache_data-wrapped function (which would silently reintroduce the identical bug).
    BBD.ensure_mlb_offers_session_state(date_str, BBD.get_odds_api_key(), preferred_book)
    plays = BBD.filter_by_split_situation(plays, venue_split, time_split)
    ss_key = f"_available_books_{date_str}"
    if st.session_state.get(ss_key) != available_books:
        st.session_state[ss_key] = available_books
        st.rerun()
else:
    if not _active.has_projections:
        st.info("🥊 This page doesn't apply to UFC — fights are outcome-based, not "
                "counting-stat-based. Head to **UFC Fight Card** in the sidebar.")
        st.stop()
    c1, c2 = st.columns([2, 1])
    with c1: target = st.date_input("Slate date", datetime.now(eastern))
    date_str = target.strftime("%Y-%m-%d")
    with c2: preferred_book = BBD.render_book_selector(
        key_prefix=f"{_active.key.lower()}_best_bets", date_str=date_str)
    # Store preferred book for load_generic_best_bets_board to read
    st.session_state[f"_preferred_book_{_active.key.lower()}"] = preferred_book
    with st.spinner("Scanning the slate..."):
        try:
            plays, meta, available_books = load_best_bets_generic(_active.key, date_str)
        except Exception:
            if _active.key == "NFL":
                st.warning(f"No NFL slate data available for {date_str}. "
                          "**Preseason games (August) aren't supported** — the projection model "
                          "requires recent game logs that don't exist yet for 2026. "
                          "NFL Best Bets will be live when the regular season starts "
                          "(Week 1 begins September 4, 2026).")
            else:
                st.warning(f"No slate data available for {_active.label} on {date_str}. "
                          "Try a date when games are scheduled.")
            st.stop()
    ss_key = f"_available_books_{_active.key}_{date_str}"
    if st.session_state.get(ss_key) != available_books:
        st.session_state[ss_key] = available_books
        st.rerun()

    diag = st.session_state.get(f"_real_lines_diag_{_active.key}_{date_str}")
    if diag:
        if diag["error"]:
            st.caption(f"⚪ Live line fetch failed ({diag['error']}) — showing the model's own "
                      f"default lines instead of real {preferred_book} numbers.")
        elif not diag["attempted"]:
            reason = "no Odds API key configured" if not diag["api_key_present"] else \
                     f"{_active.label} has no markets configured yet"
            st.caption(f"⚪ Live line fetch not attempted ({reason}) — showing the model's own "
                      f"default lines.")
        elif diag["offers"] == 0:
            st.caption(f"⚪ The live fetch ran, but {preferred_book} (or the Odds API) has 0 "
                      f"props posted for {_active.label} on this date yet — showing the model's "
                      f"own default lines, not real book numbers. Common well before a season "
                      f"starts or for lower-profile games.")
        elif diag["matched_lines"] == 0:
            st.caption(f"⚪ The live fetch found {diag['offers']} real offer(s), but none matched "
                      f"a player/market on this slate by name — showing the model's own default "
                      f"lines. Worth a closer look if this persists once real games are close.")
        else:
            st.caption(f"🟢 Using real {preferred_book} lines where available "
                      f"({diag['matched_lines']} player/market line(s) matched from "
                      f"{diag['offers']} live offer(s)) — the model's own defaults fill in the rest.")

if not plays:
    if not _active.has_projections:
        st.info("🥊 Best Bets doesn't apply to UFC — fights are outcome-based, not counting-stat-based. "
               "Head to **UFC Fight Card** in the sidebar for tonight's bouts, moneyline odds, "
               "method of victory lines, and fight duration props.")
    else:
        st.info("No plays for this date.")
    st.stop()

# --- filters ---------------------------------------------------------------
slots_present = sorted({p["Slot"] for p in plays}, key=lambda s: SLOT_ORDER.get(s, 9))
f1, f2 = st.columns(2)
with f1:
    slot_pick = st.selectbox("Time slot", ["All slate"] + slots_present)
slot_plays = plays if slot_pick == "All slate" else [p for p in plays if p["Slot"] == slot_pick]

# Game filter, added directly on request — the same shared pattern Graded Picks/Bullpen Watch/
# Game Watch already use: chronological by each game's own real start time, "Game" defaulting to
# "All games in this slot" so nothing is hidden unless actively narrowed. Built from meta (now
# returned in full by both loaders above) rather than re-deriving game times from the plays
# list's own already-formatted "Time" strings, which aren't safe to sort chronologically as
# plain text (e.g. "10:15 AM ET" would incorrectly string-sort before "3:07 PM ET").
game_date_by_label = {m["label"]: m.get("game_date") for m in meta}
games_in_slot = sorted({p["Game"] for p in slot_plays},
                       key=lambda g: game_date_by_label.get(g) or "~")


def _game_label_fmt(g: str) -> str:
    dt = game_dt(game_date_by_label.get(g))   # already Eastern-localized by game_dt itself
    return g if dt is None else f"{dt.strftime('%-I:%M %p ET')} — {g}"


with f2:
    game_pick = st.selectbox("Game", ["All games in this slot"] + games_in_slot,
                             format_func=lambda g: _game_label_fmt(g)
                             if g != "All games in this slot" else g)
slot_plays = (slot_plays if game_pick == "All games in this slot"
             else [p for p in slot_plays if p["Game"] == game_pick])

f3, f4, f5 = st.columns(3)
with f3:
    markets = sorted({p["Market"] for p in plays})
    # Same real, deliberate curation as Suggested Parlays/Graded Picks/Speculative Basket -- see
    # sports.py's own comment for the full reasoning. Intersected with markets so a curated-in
    # market genuinely absent from tonight's board never appears as a phantom default; falls
    # back to every market for any sport without a curation yet.
    _default_markets = (_active.default_markets or markets)
    _default_mkt_pick = [m for m in _default_markets if m in markets] or markets
    mkt_pick = st.multiselect("Markets", markets, default=_default_mkt_pick)
with f4: min_conv = st.slider("Min conviction", 1.0, 3.0, 1.2, 0.1,
                              help="Conviction is now measured against the real, live no-vig "
                                   "market probability for a play whenever one exists (📊 on "
                                   "the grade badge elsewhere on this platform), not always this "
                                   "platform's own hand-typed guess at what's typical for the "
                                   "market. That's a genuinely harder, more honest bar to clear "
                                   "— seeing fewer plays pass the same threshold than you might "
                                   "remember isn't a bug, it's real market data replacing a "
                                   "guess.")
with f5:
    # A separate, ABSOLUTE floor from Min conviction above -- Conviction is relative to each
    # market's own typical reference rate, so the same Conviction value means different real
    # probability depending on the market. Added directly on request: a real, sharp trader's
    # own manual process wanted "only show me plays at least X% likely," which Conviction alone
    # doesn't directly answer. Defaults to 0 (no floor) so nobody's existing view changes unless
    # they actively set one.
    min_prob_pct = st.slider("Min probability %", 0, 100, 0, 5,
                             help="Raw ModelProb floor, independent of Min conviction -- 0 means "
                                 "no floor. Two plays can share the same Conviction at very "
                                 "different raw probabilities, since Conviction is relative to "
                                 "each market's own typical reference rate.")

# A REAL BUG FIX, caught directly in production: clearing the Markets multiselect down to zero
# selections used to raise a raw KeyError, not a friendly message. Root cause: pd.DataFrame([])
# on an empty `view` produces a DataFrame with ZERO COLUMNS (nothing to infer them from), and the
# very next line selects specific columns out of it -- a KeyError, since none of those columns
# exist on a columnless frame. A "no plays match" info message already existed further down the
# page, but only right before the Diagnostic Inspector section, well AFTER the crash-prone
# DataFrame code -- it could never actually be reached in this exact scenario. Fixed by checking
# BEFORE building the board, with a specific, more directly actionable message for the single
# most common real cause (zero markets selected) separate from the general "adjust your filters"
# case.
if not mkt_pick:
    st.info("Select at least one market above to see plays.")
    st.stop()

view = [p for p in slot_plays if p["Market"] in mkt_pick and p["Conviction"] >= min_conv]
view = grading.filter_min_probability(view, min_prob_pct / 100.0)
# A REAL, CONFIRMED FIX, not the original design -- re-sorted here by ModelProb (real
# probability of hitting), not left in the plays list's own Conviction-descending order. Same
# real reasoning as the fix already made to Command Center's "Tonight's top leans": Conviction
# measures edge relative to a market-typical reference rate, not absolute likelihood, and a real
# betting decision should lead with "how likely is this," not "how much better than typical is
# this market's own reference rate." min_conv above still requires real, validated edge before a
# play is even eligible -- this reorders WITHIN that already-graded set, it doesn't remove the
# floor.
view.sort(key=lambda p: p["ModelProb"], reverse=True)

if not view:
    st.info("No plays match the current filters — adjust the time slot, game, markets, min "
           "conviction, or min probability.")
    st.stop()

# --- the board -------------------------------------------------------------
for p in view:
    if p.get("_bullpen_blended"):
        p["Player"] = f"🔄 {p['Player']}"   # compact, visible marker — no new column needed
    # Mark each play's line source directly in the Line column display so nobody is ever
    # looking at a line without knowing whether it's a real, live number or a generic
    # placeholder -- "📊 3.5" for a real book line, plain "3.5" for the default. Added directly
    # on request after a real, reported discrepancy (a play showing "Under 5.5" for a pitcher
    # whose real DraftKings line was 3.5). The 📊 marker is the same posture as 🔄 above --
    # visible in the existing Line column, no extra column needed.
    if p.get("LineSource") == "book":
        p["_display_line"] = f"📊 {p['Line']:g}"
    else:
        p["_display_line"] = f"{p['Line']:g}" if p.get("Line") is not None else "—"
    # Same real-vs-placeholder marker applied to the PRICE, not just the line -- a real, confirmed
    # systemic gap this closes: the line has been real since the July 24 wiring, but the price
    # shown alongside it was ALWAYS the model's own theoretical number (Fair), with zero attempt
    # to check for a real captured price at that same real line. "📊 -140" is a real DraftKings
    # price; a plain "+138" with no marker is still the model's own independent estimate.
    if p.get("PriceSource") == "book" and p.get("RealPrice") is not None:
        p["_display_price"] = f"📊 {p['RealPrice']:+d}"
    else:
        p["_display_price"] = f"{p['Fair']:+d}" if p.get("Fair") is not None else "—"
df = pd.DataFrame(view)[["ModelProb", "Conviction", "Time", "Slot", "Player", "Team", "Market", "Side",
                         "_display_line", "_display_price", "Game", "Why"]]
df = df.rename(columns={"ModelProb": "Model %", "_display_line": "Line",
                        "_display_price": "Fair", "Why": "Why the model likes it"})
st.dataframe(df.style.format({"Model %": "{:.0%}", "Conviction": "{:.2f}×"}, na_rep="—")
             .theme_gradient(cmap="Greens", subset=["Model %"]),
             width="stretch", hide_index=True, height=400)

# Quick-log widget, added directly on request: during a real, narrow pick-making window, having
# to separately re-enter a pick into Bet Log is real friction that gets skipped in favor of just
# making the pick. Owner-only (quick_log itself enforces this).
# _real_offers side-channel: the SAME real sportsbook offers this page already fetched to price
# its own board (see best_bets_data.load_generic_best_bets_board) -- reused here so a logged
# pick gets a real captured price when one exists, instead of quick_log always falling back to
# the model's own Fair odds.
_real_offers = st.session_state.get(f"_real_offers_{_active.key}_{date_str}") or []
quick_log.render_quick_log(view, date_str, _active.key, key_prefix="best_bets", offers=_real_offers)

if any(p.get("_bullpen_blended") for p in view):
    st.caption("🔄 = re-priced using this hitter's own real vs-starter/vs-bullpen exposure split, "
              "not just the starter's rate applied to all of his projected plate appearances — a "
              "real, confirmed correction (see \"Why the model likes it\" for that specific play's "
              "own exposure split). Scoped to the top hitter-market candidates only, not the "
              "whole slate, for real cost reasons — a play outside that scope still uses the "
              "starter-only read, which is usually the same number anyway when a hitter has "
              "little or no real bullpen exposure to begin with.")
if any(p.get("LineSource") == "book" for p in view):
    st.caption("📊 = a real, live sportsbook number (from The Odds API, the same source Edge "
              "Board already uses), shown in BOTH the Line and Fair columns independently — a "
              "real line doesn't guarantee a real price, and vice versa, so each is marked on "
              "its own. **Line:** the probability and grade are computed against this real "
              "number, not a generic placeholder. **Fair:** this is the real captured price a "
              "book is actually offering right now, not the model's own theoretical estimate. "
              "A plain number with no 📊 in either column means the API key isn't configured, "
              "or this specific player/market/side had no real coverage, so the platform's own "
              "placeholder (for Line) or the model's own independent estimate (for Fair) was "
              "used instead. To enable real lines and prices everywhere, add ODDS_API_KEY to "
              "your Streamlit secrets — same key Edge Board already requires.")

# --- DIAGNOSTIC INSPECTOR --------------------------------------------------
st.divider()
C.section_header("🔍", "Inspect Bet Diagnostics")

# No "if not view" check needed here -- the earlier checks (zero markets selected, or zero plays
# matching the rest of the filters) already st.stop() the whole page before this point, so `view`
# is guaranteed non-empty by the time execution reaches here.

# Searchable picker: the box is type-to-search, so just start typing a player's name to jump to
# them — no scrolling. Plays are already ordered by ModelProb, so the most likely leans are on top.
selected_idx = st.selectbox(
    "Select a play to inspect for model hallucinations (type a name to search)",
    options=range(len(view)),
    format_func=lambda i: (f"{view[i]['ModelProb']:.0%}  ·  {view[i]['Player']}  ·  "
                           f"{view[i]['Market']} {view[i]['Side']} {view[i]['Line']:g}"))

p = view[selected_idx]
with st.expander("Diagnostic Inspector", expanded=True):
    # What's real vs. model-generated for THIS specific play, all in one place -- Conviction is
    # a raw numeric column in the main table above (can't carry an inline 📊 marker the way the
    # Line/Fair text columns can), so this is the actual place to see it clearly per play.
    rc1, rc2, rc3 = st.columns(3)
    conv_src = p.get("ConvictionSource", "model_typical")
    rc1.metric("Conviction basis",
              "📊 Real market" if conv_src == "book" else "Model-typical guess",
              help="Whether this play's Conviction (and therefore its grade and rank) is "
                   "measured against the real, live no-vig market probability for this exact "
                   "bet, or this platform's own hand-set estimate of what's typical for this "
                   "market category. Real market data is the more rigorous, more honest "
                   "comparison — it reflects what's actually being offered right now, not a "
                   "guess.")
    price_src = p.get("PriceSource", "model_fair")
    rc2.metric("Price basis", "📊 Real book price" if price_src == "book" else "Model estimate")
    line_src = p.get("LineSource", "default")
    rc3.metric("Line basis", "📊 Real book line" if line_src == "book" else "Platform default")
    if conv_src != "book":
        st.caption("No real two-sided book price was available for this specific play, so its "
                  "Conviction/grade fell back to this platform's own reasoned-but-unvalidated "
                  "estimate of a typical rate for this market. Not wrong, just less rigorous "
                  "than a real market comparison — worth knowing before trusting the grade at "
                  "face value.")

    if _active.key == "MLB":
        pa = p.get("PA")
        phr = p.get("ParkHR", 1.0)
        wxc = p.get("WxHR", 1.0)
        temp = p.get("Temp")
        temp_pct = p.get("WxTempPct")
        wind_pct = p.get("WxWindPct")
        wind_desc = p.get("WxDesc")
        driver = p.get("WxDriver")

        col1, col2, col3 = st.columns(3)
        # Plate appearances with a graduated confidence label (not just a binary warning)
        if pa is None:
            col1.metric("Plate Appearances (PA/BF)", "N/A")
        else:
            sample = "thin" if pa < 50 else "moderate" if pa < 200 else "robust"
            col1.metric("Plate Appearances (PA/BF)", f"{pa:.1f}", help="Season sample behind the projection")
            col1.caption(f"sample: **{sample}**")
        col2.metric("Park HR Factor", f"{phr:.2f}", help="Multi-year park data — stable, high-confidence")
        col3.metric("Weather Factor", f"{wxc:.2f}")

        # --- weather decomposition: split the factor into temperature vs wind, with a trust note ---
        if temp_pct is not None or wind_pct is not None:
            t_txt = (f"Temperature {int(temp)}°F ({temp_pct:+.0f}%)" if temp is not None
                     else f"Temperature ({temp_pct:+.0f}%)")
            w_txt = f"Wind — {wind_desc} ({wind_pct:+.0f}%)" if wind_desc else f"Wind ({wind_pct:+.0f}%)"
            st.markdown(f"**Weather {wxc:.2f} =** {t_txt}  ·  {w_txt}")
            if wind_pct is not None and abs(wind_pct) < 1:
                st.caption("↳ The wind is a crosswind / negligible — this factor is essentially **all "
                           "temperature**, a robust and well-understood effect. Trust it.")
            elif driver == "wind":
                st.caption("↳ This boost **leans on the wind** (the out-to-CF component), which is more "
                           "variable than heat — worth a glance at the actual conditions before leaning on it.")
            else:
                st.caption("↳ Driven mostly by **temperature** (robust), with a modest wind contribution.")

        # --- warnings, now confidence-aware ---
        if pa is not None and pa < 50:
            st.warning(f"⚠️ Low sample: projecting on only ~{pa:.0f} PA — regress hard, treat with caution.")

        stack = phr * wxc
        if stack > 1.15:
            # A stack driven by heat + park (both high-confidence) is NOT a 'perfect storm'. Only the
            # WIND-driven portion is genuinely fragile, so only sound the alarm when wind is doing the work.
            if wind_pct is not None and wind_pct >= 5:
                st.warning(f"⚠️ Multiplier stack (+{(stack - 1) * 100:.0f}%) leans on a **wind boost "
                           f"(+{wind_pct:.0f}%)** — the least reliable input. Verify the wind is real before trusting it.")
            else:
                st.info(f"ℹ️ Park × weather is ~+{(stack - 1) * 100:.0f}%, but it's driven by **heat and park** "
                        "(high-confidence inputs), not a phantom wind boost — reasonable to trust.")
    else:
        # No park/weather/platoon signals exist for basketball — the honest inspector here is
        # just the receipts: the player's actual last-N games for this exact stat, so you can see
        # precisely what the bootstrap model resampled from rather than trusting a black box.
        log = p.get("_game_log") or []
        stat_key = p.get("_stat_key")
        if not log or not stat_key:
            st.caption("No recent-game log attached to this play.")
        else:
            n = len(log)
            hits = sum(1 for g in log if (g.get(stat_key, 0) > p["Line"] if p["Side"] == "Over"
                                          else g.get(stat_key, 0) < p["Line"]))
            avg = sum(g.get(stat_key, 0) for g in log) / n
            c1, c2, c3 = st.columns(3)
            c1.metric("Games sampled", n, help="How many recent games the bootstrap model drew from")
            c2.metric(f"Cleared {p['Line']:g}", f"{hits}/{n}")
            c3.metric("Recent average", f"{avg:.1f}")
            if n < 6:
                st.warning(f"⚠️ Short sample: only {n} recent games — the model can't yet see outcomes "
                           "this player hasn't produced in that window. Treat with extra caution.")

            def _fmt_date(iso):
                try:
                    return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%b %-d")
                except (ValueError, TypeError, AttributeError):
                    return iso or "—"

            log_df = pd.DataFrame([{"Date": _fmt_date(g.get("date")), "Opponent": g.get("opp") or "—",
                                    stat_key.upper(): g.get(stat_key, 0), "Minutes": g.get("min", 0)}
                                   for g in log])
            st.dataframe(log_df, hide_index=True, width="stretch")
            st.caption("Most recent game first. This is the exact data the bootstrap resampled from — "
                       "no park factor, weather, or opponent-strength adjustment yet (v1 model).")

# --- footer ----------------------------------------------------------------
st.caption("Conviction shades darker for stronger leans. ...")
with st.expander("How 'best' is defined here (read me)"):
    st.markdown("...")
