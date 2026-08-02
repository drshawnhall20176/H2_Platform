"""
Graded Picks — every game on the slate, graded, not a flat top-10.

WHY GAME-BY-GAME, NOT A RANKED LIST: a flat top-N would naturally cluster on whichever 2-3 games
happen to have the juiciest matchups that night, leaving the rest of the slate invisible to
anyone specifically interested in a different game. Games are shown here in full, sorted with the
most interesting first (by each game's own best play), so the whole slate stays visible — nothing
silently dropped, just organized by what's actually worth a look first.

SLATE SUMMARY, ADDED DIRECTLY ON REQUEST -- NOT A CONTRADICTION OF THE ABOVE: a curated "top
picks by grade" section now sits ABOVE the full game-by-game board, specifically so someone
doesn't have to scroll every game to find the strongest picks. The reasoning above for why this
page isn't JUST a flat top-N still holds completely -- the summary is additive, not a
replacement; the full board underneath is complete and totally unaffected by the summary's own
grade-floor/Top N controls. Excludes D by default (a real, visible, adjustable floor, not
hardcoded) -- see grading.top_picks_by_grade's own docstring for the full reasoning on why.

Letter grades and tier labels here are THIS PLATFORM'S OWN wording and thresholds, grounded in
its own already-established Conviction scale — not reverse-engineered from, or copied from, any
other product's scoring or badge text. See projections.conviction_to_grade's own docstring for
the full reasoning.
"""

import streamlit as st
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import components as C
from datetime import datetime
import pytz

import sports
import best_bets_data as BBD
import grading
import quick_log

_active = sports.active()
E, P = _active.engine, _active.projections
game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER   # shared with
                                                                                   # Best Bets and
                                                                                   # every Matchup
                                                                                   # Lab variant

C.base_css()
C.page_header("🏅", "Graded Picks",
             f"Every game on the slate, graded — sorted with the most interesting first, not a "
             f"flat top-10 that hides the rest of the board — {_active.icon} {_active.label}")
# Restored after Graded Picks itself moved to owner-only -- both this page and Suggested Parlays
# now share the same owner-only audience, so this pointer no longer risks a broken public link
# the way it did when Graded Picks was still public and Suggested Parlays was already gated.
st.page_link("views/3_Suggested_Parlays.py", label="Want it pre-combined into a parlay? See Suggested Parlays →",
            icon="🎫")

if not sports.require_live_engine("Graded Picks"):
    st.stop()

eastern = pytz.timezone("US/Eastern")


# --- controls ---------------------------------------------------------------
if _active.key == "MLB":
    c1, c2 = st.columns([2, 1])
    with c1: target = st.date_input("Slate date", datetime.now())
    date_str = target.strftime("%Y-%m-%d")
    with c2: preferred_book = BBD.render_book_selector(key_prefix="graded_picks", date_str=date_str)
    venue_split, time_split = BBD.render_split_selector(key_prefix="graded_picks")
    with st.spinner("Grading the slate..."):
        plays, meta, rows, available_books = BBD.load_mlb_graded_picks_board(
            date_str, E.FIP_CONSTANT_DEFAULT, preferred_book, venue_split, time_split)
    BBD.ensure_mlb_offers_session_state(date_str, BBD.get_odds_api_key(), preferred_book)
    plays = BBD.filter_by_split_situation(plays, venue_split, time_split)
    ss_key = f"_available_books_{date_str}"
    if st.session_state.get(ss_key) != available_books:
        st.session_state[ss_key] = available_books
        st.rerun()
else:
    # UFC and other outcome-based sports have no projections pipeline -- redirect immediately
    # before any loader is called, to avoid AttributeError on sport.projections.
    if not _active.has_projections:
        st.info("🥊 This page doesn't apply to UFC — fights are outcome-based, not "
                "counting-stat-based. Head to **UFC Fight Card** in the sidebar for "
                "tonight's bouts, moneyline odds, method of victory lines, and fight "
                "duration props.")
        st.stop()
    target = st.date_input("Slate date", datetime.now(eastern))
    date_str = target.strftime("%Y-%m-%d")
    with st.spinner("Grading the slate..."):
        try:
            plays, meta, _books = BBD.load_generic_best_bets_board(_active.key, date_str)
        except Exception:
            st.warning(f"No slate data available for {_active.label} on {date_str}. "
                      "Normal during off-season. Try a date when games are scheduled.")
            st.stop()
    rows = None   # the one-sided banner is MLB-specific (compares starting pitchers) — not
                 # available for other sports, and deliberately not faked for them

if not plays:
    if not _active.has_projections:
        st.info("🥊 This page doesn't apply to UFC — head to **UFC Fight Card** in the sidebar.")
    else:
        st.info("No games on the board right now. Graded picks appear here on an active slate.")
    st.stop()

# Time slot + Game filters — the same shared helpers (game_dt/slot_of/SLOT_ORDER) Best Bets and
# every Matchup Lab variant already use, narrowing a busy night's full slate down to one part of
# it. Filters on meta (already generic across every sport in Best Bets' own existing code, not a
# new assumption for this page) rather than pitcher rows, since Graded Picks works from the
# flattened plays/meta shape, not per-pitcher rows the way Matchup Lab does.
for m in meta:
    m["_slot"] = slot_of(game_dt(m.get("game_date")))
slots_present = sorted({m["_slot"] for m in meta}, key=lambda s: SLOT_ORDER.get(s, 9))

c_slot, c_game = st.columns(2)
with c_slot:
    slot_pick = st.selectbox("Time slot", ["All slate"] + slots_present)
slot_meta = meta if slot_pick == "All slate" else [m for m in meta if m["_slot"] == slot_pick]

if not slot_meta:
    st.info(f"No games in the {slot_pick} slot — try a different time slot or \"All slate\".")
    st.stop()

game_date_by_label = {m["label"]: m.get("game_date") for m in slot_meta}
games_present = sorted(game_date_by_label, key=lambda g: game_date_by_label[g] or "~")


def _game_label_fmt(g: str) -> str:
    dt = game_dt(game_date_by_label.get(g))   # already Eastern-localized by game_dt itself
    if dt is None:
        return g
    return f"{dt.strftime('%-I:%M %p ET')} — {g}"


with c_game:
    game_pick = st.selectbox("Game", ["All games in this slot"] + games_present,
                             format_func=lambda g: _game_label_fmt(g) if g != "All games in this slot" else g)

selected_labels = ({m["label"] for m in slot_meta} if game_pick == "All games in this slot"
                   else {game_pick})
plays = [pl for pl in plays if pl.get("Game") in selected_labels]

if not plays:
    st.info("No graded plays match the current filters — try a different time slot or game.")
    st.stop()

# --- market selection --------------------------------------------------------
# Added directly on request, for consistency with Suggested Parlays/Speculative Basket — same
# real reasoning as those pages: letting a person choose what they want exposure to here too,
# rather than this page silently differing in scope from the other two that draw from the exact
# same graded board.
markets_present = sorted({pl.get("Market") for pl in plays if pl.get("Market")})
# Same real, deliberate curation as Suggested Parlays -- see sports.py's own comment for the
# full reasoning. Intersected with markets_present so a curated-in market genuinely absent from
# tonight's board never appears as a phantom default; falls back to every market on the board
# for any sport without a curation yet.
_default_markets = (_active.default_markets or markets_present)
_default_selected = [m for m in _default_markets if m in markets_present] or markets_present
selected_markets = st.multiselect("Markets to include", options=markets_present,
                                  default=_default_selected)
if not selected_markets:
    st.info("Select at least one market above to see graded picks.")
    st.stop()
plays = [pl for pl in plays if pl.get("Market") in selected_markets]

if not plays:
    st.info("No graded plays match the current filters — try including more markets.")
    st.stop()

# --- min probability floor ----------------------------------------------------
# A separate, ABSOLUTE floor from this page's own letter grades -- grade thresholds are set
# relative to each market's own typical reference rate, so an absolute "only show me plays at
# least X% likely" question isn't something a grade letter alone answers. Added directly on
# request, same shared helper Best Bets/Suggested Parlays/Speculative Basket all use. Defaults
# to 0 (no floor) so nobody's existing view changes unless they actively set one.
min_prob_pct = st.slider("Min probability %", 0, 100, 0, 5,
                         help="Raw ModelProb floor, independent of letter grade -- 0 means no "
                             "floor. Applied on top of the grading floor every play here "
                             "already has to clear.")
plays = grading.filter_min_probability(plays, min_prob_pct / 100.0)

if not plays:
    st.info("No graded plays clear the current min probability floor — try lowering it.")
    st.stop()

# grading.py's organize_graded_picks does the grading, grouping, and sorting — a shared,
# sport-agnostic module (a real fix, not a style choice: this used to be MLB-only, and calling it
# via P.organize_graded_picks would crash immediately for every non-MLB sport, confirmed directly
# during a later cross-sport audit) — kept separate from any Streamlit rendering code so this
# real logic is actually unit tested, not just trusted by eye in the browser.
organized = grading.organize_graded_picks(plays)

if not organized:
    st.info("Nothing on tonight's slate clears the grading floor yet — check back closer to "
            "first pitch as lineups and matchups firm up.")
    st.stop()

# Ranking, added directly on request -- but ONLY once a specific game is selected, not across
# "All games in this slot". A real, deliberate scoping choice: this page's own reason for being
# organized game-by-game (see the module docstring) is that a flat, slate-wide rank would bury
# most of the board behind whichever 2-3 games happen to have the juiciest plays that night --
# exactly what game-by-game organization exists to avoid. Ranking WITHIN one already-selected
# game doesn't have that problem, since a person has already chosen to focus there. Uses
# rank_value (not raw Conviction, not ModelProb) specifically because this page's entire identity
# is its letter grades -- a rank that disagreed with them would reintroduce the same cross-market
# inversion just fixed in organize_graded_picks and Command Center.
show_ranking = game_pick != "All games in this slot"
if show_ranking:
    all_plays_in_game = [play for entry in organized for player_entry in entry["players"]
                         for play in player_entry["plays"]]
    grading.rank_flat_plays(all_plays_in_game, key="rank_value")   # mutates each play's own dict
                                                                   # with "_rank" in place, so the
                                                                   # existing nested game/player
                                                                   # loop below picks it up
                                                                   # automatically, no restructuring

GRADE_COLOR = {"A": "#16783c", "B": "#2e7d32", "C": "#b8860b", "D": "#6b7280"}


def _grade_badge(grade: dict) -> str:
    color = GRADE_COLOR.get(grade["letter"], "#6b7280")
    return (f"<span style='background:{color};color:white;padding:2px 10px;border-radius:6px;"
           f"font-weight:700;font-size:0.95em;'>{grade['letter']}</span> "
           f"<span style='color:{color};font-weight:600;'>{grade['tier']}</span> "
           f"<span style='opacity:0.7;'>({grade['conviction']:.2f}×)</span>")


# --- Slate summary ------------------------------------------------------------
# Added directly on request: a curated "look here first" view sitting ABOVE the full game-by-game
# board below, not instead of it -- the board underneath is completely unchanged, every game and
# every grade still fully visible exactly as it always has been. This section exists specifically
# so someone doesn't have to scroll through every game to find the strongest picks, without
# undoing the whole reason this page is organized game-by-game in the first place (see the module
# docstring at the top of this file).
C.section_header("⭐", "Slate summary — top picks by grade")

GRADE_FLOOR_OPTIONS = {
    "A only": ("A",),
    "B or better": ("A", "B"),
    "C or better": ("A", "B", "C"),
    "D or better (all grades)": ("A", "B", "C", "D"),
}
sc1, sc2 = st.columns([2, 1])
with sc1:
    # Defaults to "C or better" -- a real, visible, adjustable control, not a hardcoded rule. D
    # is this platform's own explicit "still worth a look, proceed with real caution" floor, the
    # lowest grade that clears any real threshold at all -- a curated summary featuring D picks
    # with the same visual weight as A's and B's would undercut the entire reason the letter
    # grade exists. Change this if you specifically want to check whether tonight's D's are
    # running hot.
    grade_floor_pick = st.selectbox("Grade floor for this summary", list(GRADE_FLOOR_OPTIONS.keys()),
                                    index=2,
                                    help="Grades are now measured against the real, live no-vig "
                                        "market probability for a play whenever one exists (📊 "
                                        "on the grade badge below), not always this platform's "
                                        "own hand-typed guess at what's typical for the market. "
                                        "A genuinely harder bar to clear — fewer A's/B's than "
                                        "you might remember isn't a bug, it's real market data "
                                        "replacing a guess.")
with sc2:
    top_n = st.number_input("Top N per grade", min_value=1, max_value=20, value=5, step=1)

summary = grading.top_picks_by_grade(organized, letters=GRADE_FLOOR_OPTIONS[grade_floor_pick],
                                     top_n=int(top_n))
if not summary:
    st.caption(f"Nothing clears {grade_floor_pick.lower()} on the current filters — try a "
              "lower grade floor, or loosen the filters above.")
else:
    for entry in summary:
        color = GRADE_COLOR.get(entry["letter"], "#6b7280")
        st.markdown(f"<span style='color:{color};font-weight:700;'>{entry['letter']} grade</span>",
                   unsafe_allow_html=True)
        for pl in entry["picks"]:
            fair_str = (f"📊 {pl['RealPrice']:+.0f}" if pl.get("PriceSource") == "book"
                                                       and pl.get("RealPrice") is not None
                       else f"{pl['Fair']:+.0f}" if pl.get("Fair") is not None else "—")
            # Baseline: the real reference rate this pick's Conviction (and therefore its grade)
            # is actually measured against -- derived directly from ModelProb/Conviction, already
            # on the play. Added directly on request: Model % and Grade sit right next to each
            # other here, and without this, a later-listed A-grade pick showing a LOWER Model %
            # than an earlier C-grade pick from a different market/line looks like a bug even
            # when it's correct math -- the baseline makes the actual comparison verifiable.
            conv, mp = pl.get("Conviction"), pl.get("ModelProb")
            baseline_str = ""
            if conv and mp is not None and conv > 0:
                marker = "📊" if pl.get("ConvictionSource") == "book" else ""
                baseline_str = f" (vs {marker}{mp / conv:.0%} typical)"
            st.markdown(
                f"{pl['ModelProb']:.0%} · {_grade_badge(pl['_grade'])}{baseline_str} — "
                f"**{pl['Player']}** {pl['Market']} {pl['Side']} {pl['Line']:g} · Fair {fair_str} · {pl['Game']}",
                unsafe_allow_html=True,
            )
    summary_plays = [pl for entry in summary for pl in entry["picks"]]
    _real_offers = st.session_state.get(f"_real_offers_{_active.key}_{date_str}") or []
    quick_log.render_quick_log(summary_plays, date_str, _active.key, key_prefix="graded_summary",
                               offers=_real_offers)
    st.caption("Sorted by real ModelProb within each grade — probability of actually hitting, "
              "not raw Conviction (which is relative to each market's own typical reference "
              "rate, not an absolute likelihood). The full game-by-game board below is complete "
              "and unaffected by the grade floor/Top N controls above — nothing there is hidden "
              "or filtered by this summary.")

st.divider()

if show_ranking:
    st.caption("🔢 Ranked #1 (strongest) to weakest within this game, by the same real grading "
              "this page already uses — not raw Conviction, so the ranking always agrees with "
              "the letter grades shown.")
if any(pl.get("ConvictionSource") == "book" or pl.get("PriceSource") == "book"
      or pl.get("LineSource") == "book"
      for game in organized for pe in game["players"] for pl in pe["plays"]):
    st.caption("📊 appears in up to three places per play, each independently: on the **grade**, "
              "when that play's Conviction (and therefore its grade and rank) is measured "
              "against the real, live no-vig market probability instead of this platform's own "
              "hand-typed guess at what's typical for the market — the more rigorous "
              "comparison. On the **line**, when it's a real sportsbook number. On **Fair**, "
              "when it's a real captured price. A grade with no 📊 isn't wrong, just measured "
              "against this platform's own reasoned-but-unvalidated estimate rather than a live "
              "market.")

for game in organized:
    game_label = game["game"]
    with st.container(border=True):
        st.markdown(f"### {game_label}")

        # --- MLB-only: one-sided banner, a real signal or nothing at all ----
        if rows is not None:
            banner = E.compute_one_sided_banner(rows, game_label)
            if banner:
                st.markdown(
                    f"🔥 **One-sided** — {banner['favored_team']}'s hitters face the weaker "
                    f"starter by a real margin ({banner['favored_opp_hr9']:.2f} vs "
                    f"{banner['other_opp_hr9']:.2f} HR/9 allowed). Worth concentrating HR-market "
                    f"attention on that side specifically."
                )

        for player_entry in game["players"]:
            _team_trend = None
            if player_entry["plays"]:
                _team_trend = player_entry["plays"][0].get("TeamTrend")
            _trend_suffix = f"  ·  Team: {_team_trend}" if _team_trend and _team_trend != "➡️ Steady" else ""
            st.markdown(f"**{player_entry['player']}** ({player_entry['team']}){_trend_suffix}")
            for pl in player_entry["plays"]:
                grade_html = _grade_badge(pl["_grade"])
                # A real, confirmed distinction worth marking right next to the grade itself:
                # whether THIS grade was measured against the real market's own no-vig
                # probability, or this platform's own hand-typed guess at what's typical for the
                # market. Same 📊 convention as the Line/Fair markers, placed on the grade badge
                # specifically since Conviction (what the grade is actually derived from) is a
                # raw number upstream, not a text field that could carry the marker itself.
                if pl.get("ConvictionSource") == "book":
                    grade_html += " 📊"
                fair_str = (f"📊 {pl['RealPrice']:+.0f}" if pl.get("PriceSource") == "book"
                                                           and pl.get("RealPrice") is not None
                           else f"{pl['Fair']:+.0f}" if pl.get("Fair") is not None else "—")
                rank_prefix = f"**#{pl['_rank']}** · " if show_ranking and pl.get("_rank") else ""
                line_val = pl.get("Line")
                line_src = pl.get("LineSource", "default")
                line_str = (f"📊 {line_val:g}" if line_src == "book" and line_val is not None
                           else f"{line_val:g}" if line_val is not None else "—")
                st.markdown(
                    f"{rank_prefix}{grade_html} — {pl['Market']} {pl['Side']} {line_str} · Fair {fair_str}",
                    unsafe_allow_html=True,
                )
                st.caption(pl.get("Why", ""))
                lineup = pl.get("Lineup")
                if lineup == "Projected":
                    st.caption("🟡 Lineup not yet confirmed — this reflects a projected spot, "
                              "not a locked-in one.")
                elif lineup == "Confirmed":
                    st.caption("🟢 Confirmed lineup.")
            st.markdown("")

        # Quick-log widget, added directly on request: during a real, narrow pick-making
        # window, having to separately re-enter a pick into Bet Log is real friction that gets
        # skipped in favor of just making the pick. Per-game (this page's own natural unit),
        # owner-only (quick_log itself enforces this).
        game_plays = [play for player_entry in game["players"] for play in player_entry["plays"]]
        _real_offers = st.session_state.get(f"_real_offers_{_active.key}_{date_str}") or []
        quick_log.render_quick_log(game_plays, date_str, _active.key,
                                   key_prefix=f"graded_{game['game']}", offers=_real_offers)
