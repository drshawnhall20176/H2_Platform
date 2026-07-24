"""
Best Bets — the model's strongest leans across the whole slate, with reasoning.
"""

import streamlit as st
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import pandas as pd
from datetime import datetime
import pytz

import sports
import best_bets_data as BBD
import grading
import quick_log

_active = sports.active()
E, P = _active.engine, _active.projections

st.title("⭐ Best Bets")
st.caption(f"The model's strongest leans across the slate — ranked, reasoned, and by time slot "
           f"— {_active.icon} {_active.label}")

if not sports.require_live_engine("Best Bets"):
    st.stop()

eastern = pytz.timezone("US/Eastern")
game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER   # now shared — see sports.py


@st.cache_data(ttl=300, show_spinner=False)
def load_best_bets_mlb(date_str: str, fip_constant: float, preferred_book: str):
    plays, meta, available_books = BBD.load_mlb_best_bets_board(date_str, fip_constant, preferred_book)
    slot_by_game = {m["label"]: (game_dt(m.get("game_date")), m.get("venue")) for m in meta}
    for pl in plays:
        dt, _ = slot_by_game.get(pl["Game"], (None, None))
        pl["Slot"] = slot_of(dt)
        pl["Time"] = dt.strftime("%I:%M %p").lstrip("0") + " ET" if dt else "TBD"
    return plays, meta, available_books


@st.cache_data(ttl=300, show_spinner=False)
def load_best_bets_generic(sport_key: str, date_str: str):
    """Any sport whose engine/projections don't need MLB's statcast/weather enrichment path —
    currently WNBA, and any future sport built the same way."""
    plays, meta = BBD.load_generic_best_bets_board(sport_key, date_str)
    slot_by_game = {m["label"]: game_dt(m.get("game_date")) for m in meta}
    for pl in plays:
        dt = slot_by_game.get(pl["Game"])
        pl["Slot"] = slot_of(dt)
        pl["Time"] = dt.strftime("%I:%M %p").lstrip("0") + " ET" if dt else "TBD"
    return plays, meta


# --- controls ---------------------------------------------------------------
# Load first (to get the real available_books from tonight's API response),
# then render the selector with the real list. On the very first load, session
# state is empty so the selector shows all books as a fallback; after the load
# completes and stores the real list, a rerun updates the selector automatically.
if _active.key == "MLB":
    c1, c2 = st.columns([2, 1])
    with c1: target = st.date_input("Slate date", datetime.now())
    with c2: fip_constant = st.number_input("FIP constant", value=E.FIP_CONSTANT_DEFAULT, step=0.01)
    date_str = target.strftime("%Y-%m-%d")
    # Render selector before the load using whatever's already in session state.
    # On first load this shows all books as a safe fallback; after the load completes and
    # stores the real book list, a rerun updates it to tonight's actual coverage.
    preferred_book = BBD.render_book_selector(key_prefix="best_bets", date_str=date_str)
    prev_books = BBD.get_available_books_for_date(date_str)
    with st.spinner("Scanning the slate..."):
        plays, meta, available_books = load_best_bets_mlb(date_str, fip_constant, preferred_book)
    if BBD.get_available_books_for_date(date_str) != prev_books:
        st.rerun()
else:
    target = st.date_input("Slate date", datetime.now(eastern))
    date_str = target.strftime("%Y-%m-%d")
    with st.spinner("Scanning the slate..."):
        plays, meta = load_best_bets_generic(_active.key, date_str)

if not plays:
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
    mkt_pick = st.multiselect("Markets", markets, default=markets)
with f4: min_conv = st.slider("Min conviction", 1.0, 3.0, 1.2, 0.1)
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
df = pd.DataFrame(view)[["ModelProb", "Conviction", "Time", "Slot", "Player", "Team", "Market", "Side",
                         "_display_line", "Fair", "Game", "Why"]]
df = df.rename(columns={"ModelProb": "Model %", "_display_line": "Line", "Why": "Why the model likes it"})
st.dataframe(df.style.format({"Model %": "{:.0%}", "Conviction": "{:.2f}×", "Fair": "{:+d}"},
                             na_rep="—")
             .theme_gradient(cmap="Greens", subset=["Model %"]),
             use_container_width=True, hide_index=True, height=400)

# Quick-log widget, added directly on request: during a real, narrow pick-making window, having
# to separately re-enter a pick into Bet Log is real friction that gets skipped in favor of just
# making the pick. Owner-only (quick_log itself enforces this).
quick_log.render_quick_log(view, date_str, _active.key, key_prefix="best_bets")

if any(p.get("_bullpen_blended") for p in view):
    st.caption("🔄 = re-priced using this hitter's own real vs-starter/vs-bullpen exposure split, "
              "not just the starter's rate applied to all of his projected plate appearances — a "
              "real, confirmed correction (see \"Why the model likes it\" for that specific play's "
              "own exposure split). Scoped to the top hitter-market candidates only, not the "
              "whole slate, for real cost reasons — a play outside that scope still uses the "
              "starter-only read, which is usually the same number anyway when a hitter has "
              "little or no real bullpen exposure to begin with.")
if any(p.get("LineSource") == "book" for p in view):
    st.caption("📊 = this play's line is a real, live sportsbook number (from The Odds API, "
              "the same source Edge Board already uses) — the probability and grade are computed "
              "against this real line, not a generic placeholder. A plain number with no 📊 "
              "means the API key isn't configured, or this specific player/market had no coverage "
              "in the real book data, so the platform's own DEFAULT_LINES placeholder was used "
              "instead. To enable real lines everywhere, add ODDS_API_KEY to your Streamlit "
              "secrets — same key Edge Board already requires.")

# --- DIAGNOSTIC INSPECTOR --------------------------------------------------
st.markdown("---")
st.subheader("🔍 Inspect Bet Diagnostics")

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
            st.dataframe(log_df, hide_index=True, use_container_width=True)
            st.caption("Most recent game first. This is the exact data the bootstrap resampled from — "
                       "no park factor, weather, or opponent-strength adjustment yet (v1 model).")

# --- footer ----------------------------------------------------------------
st.caption("Conviction shades darker for stronger leans. ...")
with st.expander("How 'best' is defined here (read me)"):
    st.markdown("...")
