"""
Highlights — saved, named filter criteria that auto-flag matching plays on today's board.

Modeled on a real workflow the community already runs through a third-party tool (PropFinder):
build a NAMED profile once ("Due for a Homer"), and every day the platform tells you who on
tonight's board actually matches it, instead of re-scanning the whole slate by eye. See
highlights.py's own module docstring for the full design reasoning.
"""

import datetime as _dt

import pandas as pd
import streamlit as st

import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import components as C
import sports
import best_bets_data as BBD
import highlights as H

_active = sports.active()
game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER

# Same grade colors already used on Graded Picks/Suggested Parlays/Speculative Basket -- reused
# directly here rather than re-invented, so a grade means the same thing, visually, everywhere
# on the platform.
GRADE_COLOR = {"A": "#16783c", "B": "#2e7d32", "C": "#b8860b", "D": "#6b7280"}


@st.cache_data(ttl=300, show_spinner=False)
def _load_highlights_board(date_str, fip_constant, preferred_book, venue_split, time_split):
    """Same real fix for a real, reported problem: this page used to call
    load_mlb_best_bets_board directly, uncached, in top-level page code -- meaning the entire
    expensive board build (odds fetch, Statcast merge, enrichment) re-ran on EVERY widget
    interaction, including ones with nothing to do with the board itself (picking a player from
    a dropdown, clicking a market radio, expanding "show all matches"). Every other
    recommendation page on this platform (Best Bets, Graded Picks, Suggested Parlays) already
    wraps this exact call in its own @st.cache_data loader for this exact reason -- this page
    just never got the same treatment."""
    return BBD.load_mlb_best_bets_board(date_str, fip_constant, preferred_book, venue_split, time_split)

C.base_css()
C.page_header("✨", "Highlights",
             "Save a named filter once, see who matches it every day — the same workflow as a "
             "PropFinder Highlight Profile, built on this platform's own real fields.")

if _active.key != "MLB":
    st.info("Highlights is MLB-only for now — the real fields these profiles filter on "
           "(Due, real captured prices, real market-based grading) aren't wired into other "
           "sports yet. Come back once you're on the MLB tab.")
    st.stop()

if not sports.require_live_engine("Highlights"):
    st.stop()

H.ensure_starter_profiles("MLB")

# Who's asking -- the same honest, no-real-login-yet convention betlog.py's own "trader" field
# already uses (see highlights.py's own docstring). A typed name, not an account.
with st.sidebar:
    st.subheader("Your name")
    my_name = st.text_input("For your personal profiles (optional)", value="",
                            help="Leave blank to only see shared house profiles. Type your "
                                "name to also see (and build) your own personal ones.")

# --- board + filters ------------------------------------------------------------
# Matchup-Lab/Best-Bets style filtering, added directly on request: a book selector (so
# PriceSource/ConvictionSource conditions like "Real-Price Locks" have real offers to match
# against -- a real, confirmed gap this closes, not previously wired in at all), venue/time
# split radios (the same real recompute-the-model toggle every other recommendation page
# shares), and Time slot/Game dropdowns (same shared pattern as Best Bets/Graded Picks/Matchup
# Lab) to narrow what's even eligible to match a profile in the first place.
c1, c2 = st.columns([2, 1])
with c1:
    target = st.date_input("Slate date", _dt.datetime.now())
    date_str = target.strftime("%Y-%m-%d")
with c2:
    preferred_book = BBD.render_book_selector(key_prefix="highlights", date_str=date_str)
venue_split, time_split = BBD.render_split_selector(key_prefix="highlights")

with st.spinner("Loading tonight's board..."):
    try:
        plays, meta, _books = _load_highlights_board(
            date_str, BBD.E.FIP_CONSTANT_DEFAULT, preferred_book, venue_split, time_split)
    except Exception:
        plays, meta = [], []
# Guarantees THIS session's own quick_log real-price side-channel is populated -- same
# established pattern as Best Bets/Graded Picks/Suggested Parlays/Speculative Basket.
BBD.ensure_mlb_offers_session_state(date_str, BBD.get_odds_api_key(), preferred_book)
plays = [pl for pl in plays if sports.has_started(pl.get("GameDate")) is not True]

if plays:
    slot_by_game = {m["label"]: game_dt(m.get("game_date")) for m in meta}
    for pl in plays:
        pl["Slot"] = slot_of(slot_by_game.get(pl["Game"]))

    f1, f2 = st.columns(2)
    with f1:
        slots_present = sorted({p["Slot"] for p in plays}, key=lambda s: SLOT_ORDER.get(s, 9))
        slot_pick = st.selectbox("Time slot", ["All slate"] + slots_present)
    plays = plays if slot_pick == "All slate" else [p for p in plays if p["Slot"] == slot_pick]

    games_in_slot = sorted({p["Game"] for p in plays},
                           key=lambda g: (slot_by_game.get(g) is None, slot_by_game.get(g) or _dt.datetime.min))
    with f2:
        game_pick = st.selectbox(
            "Game", ["All games in this slot"] + games_in_slot,
            format_func=lambda g: (g if g == "All games in this slot" else
                                   (f"{slot_by_game[g].strftime('%-I:%M %p ET')} — {g}"
                                    if slot_by_game.get(g) else g)))
    plays = plays if game_pick == "All games in this slot" else [p for p in plays if p["Game"] == game_pick]

profiles = H.list_profiles("MLB", owner=my_name or None)
result = H.highlights_by_profile(plays, profiles) if (plays and profiles) else []

# --- quick stats row ----------------------------------------------------------
n_shared = sum(1 for p in profiles if not p.get("owner"))
n_personal = sum(1 for p in profiles if p.get("owner"))
total_matches = sum(len(r["matches"]) for r in result)
top_profile = max(result, key=lambda r: len(r["matches"])) if result else None

s1, s2, s3, s4 = st.columns(4)
with s1: st.metric("Live plays tonight", len(plays))
with s2: st.metric("Profiles active", f"{n_shared} shared" + (f" + {n_personal} yours" if n_personal else ""))
with s3: st.metric("Total matches", total_matches)
with s4:
    st.metric("Top profile", f"{top_profile['emoji']} {top_profile['name']}" if top_profile else "—",
              f"{len(top_profile['matches'])} matches" if top_profile else None)

# --- build a new profile (moved to the top on request -- this is the thing a person actually
# comes here to DO; the results below are what they came back to CHECK) ---------------------
st.divider()
C.section_header("🛠️", "Build a new profile")

with st.container(border=True):
    st.caption("Every condition below runs against real fields already on tonight's board — "
              "nothing here is a placeholder or a guess. A play must clear EVERY condition you "
              "add to match (AND logic).")

    FIELD_HELP = {
        "Market": "e.g. Batter HR, Batter Total Bases, Pitcher Strikeouts",
        "Side": "Over or Under",
        "Grade": "This platform's own letter grade (A/B/C/D) — real, validated edge, computed live",
        "ModelProb": "The model's own real probability of hitting (0-1)",
        "Conviction": "Edge relative to what's typical for this market",
        "PriceSource": "\"book\" = a real captured sportsbook price exists; \"model_fair\" = theoretical only",
        "ConvictionSource": "\"book\" = graded against a real market rate; \"model_typical\" = a hand-typed guess",
        "LineSource": "\"book\" = a real captured line; \"default\" = placeholder",
        "OppERA": "The opposing starter's real season ERA",
        "Due": "Batter HR only — Statcast barrels running ahead of the real HR count (percentage points)",
        "AVG": "The batter's real season batting average",
        "SLG": "The batter's real season slugging percentage",
    }

    with st.form("new_profile_form", clear_on_submit=True):
        c_name, c_emoji, c_vis = st.columns([3, 1, 3])
        with c_name:
            name = st.text_input("Profile name", placeholder="e.g. Due for a Homer")
        with c_emoji:
            emoji = st.text_input("Emoji", value="⭐", max_chars=4)
        with c_vis:
            scope = st.radio("Visibility", ["Shared (everyone sees it)", "Personal (just me)"])

        st.markdown("**Conditions** (fill in the ones you want, leave the rest blank)")
        conditions = []
        preview_parts = []
        for i in range(3):
            c1i, c2i, c3i = st.columns([2, 1, 2])
            with c1i:
                field = st.selectbox(f"Field {i + 1}", [""] + H.CONDITION_FIELDS,
                                     key=f"field_{i}", help=None)
            with c2i:
                op = st.selectbox("Op", H.SUPPORTED_OPS, key=f"op_{i}")
            with c3i:
                raw_value = st.text_input("Value", key=f"value_{i}",
                                          help=FIELD_HELP.get(field, ""))
            if field and raw_value:
                if op == "in":
                    value = [v.strip() for v in raw_value.split(",")]
                else:
                    try:
                        value = float(raw_value)
                        if value == int(value):
                            value = int(value)
                    except ValueError:
                        value = raw_value
                conditions.append({"field": field, "op": op, "value": value})
                preview_parts.append(f"**{field}** {op} **{value}**")

        if preview_parts:
            st.caption("Will match plays where " + " AND ".join(preview_parts) + ".")

        submitted = st.form_submit_button("Save profile", width="stretch")
        if submitted:
            if not name:
                st.error("Give the profile a name first.")
            elif not conditions:
                st.error("Add at least one real condition — a profile with none would match "
                         "everything on the board, which isn't a real highlight.")
            elif scope.startswith("Personal") and not my_name:
                st.error("Type your name in the sidebar first to save a personal profile.")
            else:
                owner = my_name if scope.startswith("Personal") else None
                H.add_profile(name, "MLB", conditions, emoji=emoji, owner=owner)
                st.success(f"Saved {emoji} {name}.")
                st.rerun()

# --- today's highlights --------------------------------------------------------
st.divider()
C.section_header("📋", "Today's Highlights")

MAX_ROWS_SHOWN = 15


def _matches_dataframe(matches: list) -> pd.DataFrame:
    """Real, sortable table -- same theme_gradient/colored-grade pattern already established on
    Command Center's Top Leans and Graded Picks, not a new one-off style. Sorted by real
    ModelProb descending so the strongest match in THIS profile leads, same "most likely first"
    convention used everywhere else real plays get ranked on this platform."""
    rows = []
    for m in matches:
        grade = H._play_value(m, "Grade") or "—"
        line_val = m.get("Line")
        line_str = f"{line_val:g}" if isinstance(line_val, (int, float)) else "—"
        price_marker = "📊 " if m.get("PriceSource") == "book" else ""
        rows.append({
            "Grade": grade,
            "Model %": m.get("ModelProb", 0.0),
            "Player": m.get("Player", ""),
            "Team": m.get("Team", ""),
            "Market": m.get("Market", ""),
            "Side": m.get("Side", ""),
            "Line": f"{price_marker}{line_str}",
            "Game": m.get("Game", ""),
        })
    return pd.DataFrame(rows).sort_values("Model %", ascending=False, kind="stable")


# The one real, market-specific number that actually drove each market's probability --
# mirrors the same per-market signal already used in _hitter_reasons' own "Why" text this
# session, just picked out individually here instead of joined into a sentence. Directly fixes
# the real reported bug: showing generic player/game-level context (AVG, ParkHR, Platoon) for
# EVERY market made every row look identical, since none of those fields are market-specific.
def _market_stat(play: dict) -> str:
    market = play.get("Market", "")
    if market == "Batter HR":
        due = play.get("Due")
        return f"Due +{due * 100:.1f}pp" if due is not None else "—"
    if market == "Batter Total Bases":
        slg = play.get("SLG")
        return f"SLG {slg:.3f}" if slg is not None else "—"
    if market in ("Batter Total Hits", "Batter Hits+Runs+RBIs"):
        avg = play.get("AVG")
        return f"AVG {avg:.3f}" if avg is not None else "—"
    if market == "Batter Strikeouts":
        k = play.get("_season_k_rate")
        return f"{k:.0%} K rate" if k is not None else "—"
    if market == "Batter Walks":
        bb = play.get("_season_bb_rate")
        return f"{bb:.0%} BB rate" if bb is not None else "—"
    if market == "Batter Stolen Bases":
        sb, pa = play.get("_season_sb"), play.get("_season_pa_for_sb")
        return f"{sb:.0f} SB/{pa:.0f} PA" if sb is not None and pa else "—"
    if market == "Batter Runs":
        runs, pa = play.get("_season_runs"), play.get("_season_pa")
        return f"{runs:.0f} R/{pa:.0f} PA" if runs is not None and pa else "—"
    if market == "Batter RBIs":
        rbi, pa = play.get("_season_rbi"), play.get("_season_pa")
        return f"{rbi:.0f} RBI/{pa:.0f} PA" if rbi is not None and pa else "—"
    if market == "Batter Doubles":
        d, pa = play.get("_season_doubles"), play.get("_season_pa")
        return f"{d:.0f} 2B/{pa:.0f} PA" if d is not None and pa else "—"
    if market == "Batter Triples":
        t, pa = play.get("_season_triples"), play.get("_season_pa")
        return f"{t:.0f} 3B/{pa:.0f} PA" if t is not None and pa else "—"
    if market == "Batter Singles":
        s, pa = play.get("_season_singles"), play.get("_season_pa")
        return f"{s:.0f} 1B/{pa:.0f} PA" if s is not None and pa else "—"
    if market == "Pitcher Strikeouts":
        pk = play.get("ProjK")
        return f"Proj. {pk:.1f} K" if pk is not None else "—"
    if market == "Pitcher Walks":
        pbb = play.get("ProjBB")
        return f"Proj. {pbb:.1f} BB" if pbb is not None else "—"
    if market == "Pitcher Outs":
        po = play.get("ProjOuts")
        return f"Proj. {po:.1f} outs" if po is not None else "—"
    return "—"


def _player_markets_dataframe(matches: list) -> pd.DataFrame:
    """One row per market this player matched on, each with its own real, market-specific
    driving stat -- built to gradient-color like Dinger Engine's own tables (many rows, real
    column-wise comparison), not a single stacked list where a color gradient would be
    meaningless (comparing an AVG against a PA on the same color scale means nothing)."""
    rows = []
    for m in matches:
        grade = H._play_value(m, "Grade") or "—"
        line_val = m.get("Line")
        line_str = f"{line_val:g}" if isinstance(line_val, (int, float)) else "—"
        rows.append({
            "Market": m.get("Market", ""), "Side": m.get("Side", ""), "Line": line_str,
            "Model %": m.get("ModelProb", 0.0), "Grade": grade,
            "Real driving stat": _market_stat(m),
        })
    return pd.DataFrame(rows).sort_values("Model %", ascending=False, kind="stable")


if not plays:
    st.info("No games on the board right now, or every game has already started.")
elif not profiles:
    st.info("No profiles yet — build one above.")
else:
    for r in result:
        owner_badge = (f"<span style='background:#374151;color:white;padding:1px 8px;"
                       f"border-radius:10px;font-size:0.78em;'>personal · {r['owner']}</span>"
                       if r.get("owner") else
                       "<span style='background:#1f6feb;color:white;padding:1px 8px;"
                       "border-radius:10px;font-size:0.78em;'>shared</span>")
        n = len(r["matches"])
        count_color = "#16783c" if n > 0 else "#6b7280"
        count_badge = (f"<span style='background:{count_color};color:white;padding:1px 10px;"
                      f"border-radius:10px;font-size:0.85em;font-weight:600;'>{n} match{'es' if n != 1 else ''}</span>")

        with st.container(border=True):
            h1, h2 = st.columns([5, 2])
            with h1:
                st.markdown(f"### {r['emoji']} {r['name']}")
                st.markdown(owner_badge, unsafe_allow_html=True)
            with h2:
                st.markdown(f"<div style='text-align:right;padding-top:14px'>{count_badge}</div>",
                          unsafe_allow_html=True)

            if not r["matches"]:
                st.caption("No plays on tonight's board match this profile.")
            else:
                df = _matches_dataframe(r["matches"])
                shown = df if n <= MAX_ROWS_SHOWN else df.head(MAX_ROWS_SHOWN)
                st.dataframe(
                    shown.style
                        .format({"Model %": "{:.0%}"})
                        .map(lambda g: f"color:{GRADE_COLOR.get(g, '#6b7280')};font-weight:700;",
                             subset=["Grade"])
                        .theme_gradient(cmap="RdYlGn", subset=["Model %"]),
                    hide_index=True, width="stretch",
                    height=min(38 * (len(shown) + 1) + 3, 460))
                if n > MAX_ROWS_SHOWN:
                    with st.expander(f"Show all {n} matches"):
                        st.dataframe(
                            df.style
                                .format({"Model %": "{:.0%}"})
                                .map(lambda g: f"color:{GRADE_COLOR.get(g, '#6b7280')};font-weight:700;",
                                     subset=["Grade"])
                                .theme_gradient(cmap="RdYlGn", subset=["Model %"]),
                            hide_index=True, width="stretch", height=460)

                # Per-player drill-down, added directly on request -- same "type to search"
                # pattern Matchup Lab already uses for its own hitter/pitcher lookups, applied
                # here to whichever players actually matched THIS profile (deduped, since the
                # same player can match on more than one market within a profile). Shows every
                # matched market as its own gradient-colored row with its own real, market-
                # specific driving stat -- the actual fix for a real reported bug: showing one
                # generic player-level stat panel per player made every market look identical,
                # since AVG/ParkHR/Platoon don't vary by market for the same player/game.
                by_player = {}
                for m in r["matches"]:
                    by_player.setdefault(m["Player"], []).append(m)
                player_pick = st.selectbox(
                    "🔍 Look up a player from these matches", [""] + sorted(by_player.keys()),
                    key=f"lookup_{r['id']}",
                    help="Every market this player matched on, each with its own real, "
                        "market-specific driving stat -- not the same generic context repeated "
                        "for every row.")
                if player_pick:
                    pdf = _player_markets_dataframe(by_player[player_pick])
                    st.dataframe(
                        pdf.style
                            .format({"Model %": "{:.0%}"})
                            .map(lambda g: f"color:{GRADE_COLOR.get(g, '#6b7280')};font-weight:700;",
                                 subset=["Grade"])
                            .theme_gradient(cmap="RdYlGn", subset=["Model %"]),
                        hide_index=True, width="stretch",
                        height=min(38 * (len(pdf) + 1) + 3, 320))

            if st.button("🗑️ Delete profile", key=f"del_{r['id']}"):
                H.delete_profile(r["id"])
                st.rerun()
