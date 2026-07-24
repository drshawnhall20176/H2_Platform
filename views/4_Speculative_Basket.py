"""
Speculative Basket — several small, INDEPENDENT high-upside positions, built for a trader's
mindset rather than a bettor's. Explicitly NOT a parlay: a parlay requires every single leg to
hit simultaneously (real, punishing "AND" logic that multiplies several real risks together).
That's not how a trader actually deploys speculative capital in penny stocks or crypto — nobody
buys several speculative names and needs ALL of them to pay off the same day to call it a win.
The real strategy is several small, independent, asymmetric positions, where hitting even ONE
makes the whole basket worthwhile — diversifying across real risk, not multiplying it.

Reuses the EXACT SAME leg-selection mechanism already proven for Suggested Parlays' own Bold/
Longshot tiers (grading.build_speculative_basket, built on the "payout" objective and the same
real grade floor) — same real, validated picks those tiers already surface, just presented as
their own independent things instead of chained together. See that function's own docstring, and
Suggested Parlays' own history, for the full reasoning this design followed from.

Works across every sport on this platform from day one — grading.py's basket logic is genuinely
sport-agnostic, the same as the rest of grading.py.
"""

import streamlit as st
import pandas as pd
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
from datetime import datetime
from typing import Optional
import pytz

import sports
import best_bets_data as BBD
import grading
import quick_log

game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER   # shared with
                                                                                   # Graded Picks
                                                                                   # and every
                                                                                   # Matchup Lab
                                                                                   # variant

_active = sports.active()
E, P = _active.engine, _active.projections

st.title("🧺 Speculative Basket")
st.caption(f"Several small, independent high-upside positions — not a parlay, no \"all must "
          f"hit\" combination — {_active.icon} {_active.label}")
st.page_link("views/3_Suggested_Parlays.py", label="Looking for a chained, all-must-hit parlay instead? See Suggested Parlays →",
            icon="🎫")

if not sports.require_live_engine("Speculative Basket"):
    st.stop()

eastern = pytz.timezone("US/Eastern")


# --- controls ---------------------------------------------------------------
if _active.key == "MLB":
    target = st.date_input("Slate date", datetime.now())
    date_str = target.strftime("%Y-%m-%d")
    preferred_book = BBD.render_book_selector(key_prefix="speculative_basket", date_str=date_str)
    with st.spinner("Building the basket..."):
        plays, meta, rows, available_books = BBD.load_mlb_graded_picks_board(
            date_str, E.FIP_CONSTANT_DEFAULT, preferred_book)
else:
    target = st.date_input("Slate date", datetime.now(eastern))
    date_str = target.strftime("%Y-%m-%d")
    with st.spinner("Building the basket..."):
        plays, meta = BBD.load_generic_best_bets_board(_active.key, date_str)

if not plays:
    st.info("No games on the board right now. Basket positions appear here on an active slate.")
    st.stop()

# --- time slot + game filter --------------------------------------------------
# The same shared helpers (game_dt/slot_of/SLOT_ORDER) Best Bets, every Matchup Lab variant, and
# Graded Picks already use -- added directly on request, to match Matchup Lab's own filtering
# here too. A basket's own positions are already fully independent (unlike a parlay), so
# narrowing to a specific slot or single game is even more natural here -- there's no "not
# enough legs to chain together" concern the way a parlay has, since build_speculative_basket
# already returns however many real, qualifying positions actually exist rather than requiring
# an exact count.
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
    st.info("No graded plays match the current time slot/game filter — try a different selection.")
    st.stop()

# --- market selection --------------------------------------------------------
# Same real, deliberate reasoning as Suggested Parlays' own market filter -- letting a person
# choose what they want exposure to, rather than Claude re-tuning reference probabilities to
# force a "balanced-looking" default across markets that genuinely differ in real skew.
markets_present = sorted({pl.get("Market") for pl in plays if pl.get("Market")})
selected_markets = st.multiselect("Markets to include", options=markets_present,
                                  default=markets_present)
if not selected_markets:
    st.info("Select at least one market above to see basket positions.")
    st.stop()
plays = [pl for pl in plays if pl.get("Market") in selected_markets]

# --- min probability floor ----------------------------------------------------
# A separate, ABSOLUTE floor from either mode's own grading below -- added directly on request,
# same shared helper Best Bets/Graded Picks/Suggested Parlays all use. Applies to the eligible
# pool before EITHER mode builds from it. Worth noting for Speculative mode specifically: that
# mode's whole point is chasing the longest real odds (lowest ModelProb) among plays that still
# clear a real grade floor, so setting a high probability floor here works directly against it
# -- an honest tension, not a bug, and the same kind of floor/objective interaction that mode's
# own "Minimum grade" control already has. Defaults to 0 (no floor) so nobody's existing basket
# changes unless they actively set one.
min_prob_pct = st.slider("Min probability %", 0, 100, 0, 5,
                         help="Raw ModelProb floor on which legs are even eligible for the "
                             "basket -- 0 means no floor. In Speculative mode specifically, a "
                             "high floor here works against that mode's own payout-chasing "
                             "objective -- set it deliberately, not as a default habit.")
plays = grading.filter_min_probability(plays, min_prob_pct / 100.0)

if not plays:
    st.info("No plays clear the current min probability floor — try lowering it.")
    st.stop()

# --- basket mode: Speculative (chase payout) vs Game Coverage (safest pick per game) ---------
# Added directly on request, after a real, reported gap: a real strategy (one safe hit pick per
# game, confirmed against actual placed bets) mostly didn't clear the edge floor the Speculative
# mode below requires -- Total Hits' own reference (0.65) is already high, so a real, good 65-77%
# pick barely beats "typical," even though it's a perfectly sound pick for a DIFFERENT question:
# not "what has the best edge," but "given I'm making one pick per game regardless, who's the
# safest option." Game Coverage answers that question directly, with no edge floor at all.
mode = st.radio("Basket mode", ["Speculative (chase payout)", "Game Coverage (one safest pick per game)"],
                horizontal=True,
                help="Speculative: the original mode, chases the biggest payout among plays that "
                    "already clear a real edge floor. Game Coverage: for each game in your "
                    "current filter, shows the single highest-probability pick for a chosen "
                    "market/side -- no edge floor, since the point is coverage across every "
                    "game, not finding the biggest edge.")

if mode == "Game Coverage (one safest pick per game)":
    c_mkt, c_side = st.columns(2)
    sorted_markets = sorted(markets_present)
    default_idx = sorted_markets.index("Batter Total Hits") if "Batter Total Hits" in sorted_markets else 0
    with c_mkt:
        coverage_market = st.selectbox("Market", options=sorted_markets, index=default_idx)
    with c_side:
        coverage_side = st.selectbox("Side", options=["Over", "Under"])
    coverage_picks = grading.build_game_coverage_picks(plays, market=coverage_market, side=coverage_side)
    basket = {
        "legs": coverage_picks,
        "prob_at_least_one_wins": grading.basket_prob_at_least_one_wins(coverage_picks),
        "expected_winners": round(sum(leg.get("ModelProb", 0.0) for leg in coverage_picks), 2),
    }
    if not basket["legs"]:
        st.info(f"No {coverage_market} {coverage_side} play found for any game in the current "
                f"filter — try a different market/side, or check back closer to first pitch.")
        st.stop()
    st.caption(f"One pick per game — the single highest-probability {coverage_market} {coverage_side} "
              f"play in each game currently in view. No edge floor: some of these may show no "
              f"letter grade at all, which is expected and not an error — it means this specific "
              f"pick doesn't carry validated edge over what's typical for this market, even "
              f"though it's still the safest real option available in that game.")
else:
    # --- basket size + risk floor ------------------------------------------------
    c_size, c_grade = st.columns(2)
    with c_size:
        basket_size = st.number_input("Number of positions", min_value=2, max_value=15, value=8, step=1)
    with c_grade:
        grade_choice = st.selectbox(
            "Minimum grade", options=["C (recommended)", "B (tighter)", "A (strictest)", "No extra floor"],
            help="A real, reported issue on Suggested Parlays: without a real quality floor, "
                "chasing the longest odds alone can pick the WORST, barely-qualifying plays purely "
                "because they have long odds, not because they have any real edge. This floor "
                "requires real, validated picks before a position is even eligible.",
        )
        min_grade_letter = {"C (recommended)": "C", "B (tighter)": "B", "A (strictest)": "A",
                            "No extra floor": None}[grade_choice]

    basket = grading.build_speculative_basket(plays, size=int(basket_size), min_grade_letter=min_grade_letter)

    if not basket["legs"]:
        st.info("Not enough real, graded plays match the selected markets and minimum grade to "
                "build a basket — try including more markets, loosening the grade floor, or check "
                "back closer to first pitch.")
        st.stop()

st.info(
    "💼 **This is a basket of INDEPENDENT positions, not a parlay.** Each play below is its "
    "own separate bet — place them individually at your book, not as one combined ticket. "
    "Hitting even one is a genuine win, unlike a parlay where every single leg has to hit "
    "together. The math below reflects that: \"at least one hits\" instead of \"everything "
    "hits.\"\n\n"
    "📊 **What \"Fair\" means**: Fair odds are what a bet would need to pay to be break-even, "
    "given the model's own probability — not what a sportsbook is actually offering. Compare "
    "it to what your book actually offers to see if there's real value."
)

# Rank once here (not down in the display loop) so the trim control below and the metrics/
# distribution above the leg list all operate on the same real ModelProb ranking.
grading.rank_flat_plays(basket["legs"], key="ModelProb")
all_legs = basket["legs"]
n_positions = len(all_legs)

if n_positions > 1:
    trim_to = st.slider(
        "Trim to top N positions (ranked by real ModelProb)", min_value=1, max_value=n_positions,
        value=n_positions,
        help="Positions are already ranked strongest-to-weakest by their own real ModelProb "
            "above. Trimming here keeps the top N and drops the rest, live-updating every "
            "number below — including the full win-count distribution, not just the mean. "
            "Because this trims by strength, it can only ever keep the highest-probability "
            "legs: it structurally can't isolate one specific weaker pick while dropping a "
            "stronger one ranked above it.",
    )
else:
    trim_to = n_positions
trimmed_legs = all_legs[:trim_to]

trimmed_at_least_one = grading.basket_prob_at_least_one_wins(trimmed_legs)
trimmed_expected = sum(leg.get("ModelProb", 0.0) for leg in trimmed_legs)
distribution = grading.basket_win_count_distribution(trimmed_legs)

c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Positions in basket", len(trimmed_legs))
with c2:
    st.metric("P(at least one wins)", f"{trimmed_at_least_one:.1%}")
with c3:
    st.metric("Expected winners", f"{trimmed_expected:.1f}")
st.caption("\"P(at least one wins)\" and \"Expected winners\" assume independence across positions "
          "— the same-player exclusion below removes the single biggest way that assumption "
          "breaks, but positions sharing a game can still carry some real, smaller correlation "
          "this doesn't fully capture. Neither number is a baseball statistic — both describe "
          "how many of these BETS are expected to settle correctly, not actual hits/runs/RBIs.")

# Full win-count distribution -- "Expected winners" is just this distribution's own mean, with
# the per-outcome detail already thrown away. Showing the whole shape gives the real band to
# expect (e.g. "2 or 3 winners together" is a materially richer, more honest answer than a
# single "expect about 2.2" point estimate) instead of just one summary number.
with st.expander(f"📊 Full win-count distribution ({len(trimmed_legs)} positions)", expanded=True):
    dist_df = pd.DataFrame({"Probability": distribution},
                           index=[f"{k} win{'s' if k != 1 else ''}" for k in range(len(distribution))])
    st.bar_chart(dist_df, y="Probability")

    mode_k = max(range(len(distribution)), key=lambda k: distribution[k])
    # The real "band to expect" -- the mode plus whichever neighbor carries more mass, not a
    # fixed +/-1 window, since the distribution isn't always symmetric around the mode.
    left_mass = distribution[mode_k - 1] if mode_k > 0 else -1.0
    right_mass = distribution[mode_k + 1] if mode_k + 1 < len(distribution) else -1.0
    if right_mass >= left_mass and right_mass >= 0:
        band_k, band_mass = (mode_k, mode_k + 1), distribution[mode_k] + right_mass
    elif left_mass >= 0:
        band_k, band_mass = (mode_k - 1, mode_k), distribution[mode_k] + left_mass
    else:
        band_k, band_mass = (mode_k,), distribution[mode_k]
    band_label = " or ".join(str(k) for k in band_k)
    st.caption(f"Most likely single outcome: **{mode_k} winner{'s' if mode_k != 1 else ''}** "
              f"({distribution[mode_k]:.1%}). **{band_label} winner{'s' if band_k[-1] != 1 else ''} "
              f"together** covers {band_mass:.1%} of all outcomes — the real range to expect, not "
              f"just the single expected-value point above.")

GRADE_COLOR = {"A": "#16783c", "B": "#2e7d32", "C": "#b8860b", "D": "#6b7280"}


def _grade_badge(grade: Optional[dict]) -> str:
    # Handles None honestly, not by hiding it -- a Game Coverage pick with no real edge over
    # typical still gets shown (it's still the safest option in that game), just labeled as
    # such rather than crashing or silently pretending it has a grade it doesn't.
    if grade is None:
        return ("<span style='background:#374151;color:#d1d5db;padding:1px 8px;border-radius:6px;"
               "font-weight:700;font-size:0.85em;'>No edge floor</span>")
    color = GRADE_COLOR.get(grade["letter"], "#6b7280")
    return (f"<span style='background:{color};color:white;padding:1px 8px;border-radius:6px;"
           f"font-weight:700;font-size:0.85em;'>{grade['letter']}</span>")


with st.container(border=True):
    # Ranking already happened once, above the trim slider (multiple positions can share the
    # same letter grade while still having meaningfully different real probabilities behind
    # them -- this page is explicitly framed around "which of these is more likely to actually
    # hit," same reasoning as Suggested Parlays). Lists the TRIMMED set so this list, the metrics
    # above, and the distribution chart above all stay in sync with the slider.
    for leg in trimmed_legs:
        grade_html = _grade_badge(leg["_grade"])
        leg_fair = leg.get("Fair")
        leg_fair_str = f"{leg_fair:+d}" if leg_fair is not None else "—"
        lineup = leg.get("Lineup")
        lineup_icon = "🟡 " if lineup == "Projected" else ("🟢 " if lineup == "Confirmed" else "")
        rank_prefix = f"**#{leg['_rank']}** · " if leg.get("_rank") else ""
        st.markdown(
            f"{rank_prefix}{grade_html} {lineup_icon}**{leg['Player']}** ({leg['Team']}) — {leg['Market']} "
            f"{leg['Side']} {leg['Line']:g} · Fair odds {leg_fair_str}",
            unsafe_allow_html=True,
        )
        # Same real, direct fix as Suggested Parlays -- the opposing starter's real name/ERA,
        # straight from the same play dict, so the actual matchup is visible right here without
        # needing to separately cross-reference Pitching Lab.
        opp_name, opp_era = leg.get("Opp"), leg.get("OppERA")
        opp_str = f" · vs {opp_name} ({opp_era:.2f} ERA)" if opp_name and opp_era is not None else ""
        st.caption(f"{leg.get('Game', '')}{opp_str} · {leg.get('Why', '')}")
        if lineup == "Projected":
            # Same real, confirmed reason this matters as Suggested Parlays -- this platform's
            # own lineup source falls back to a team's full active roster when the actual posted
            # batting order for THIS specific game isn't available yet, so a player shown here
            # could still be scratched before first pitch.
            st.caption("🟡 Lineup not yet confirmed for this game — a player shown here could "
                      "still be scratched before first pitch.")
        st.markdown("")

# Quick-log widget, added directly on request: during a real, narrow pick-making window, having
# to separately re-enter a pick into Bet Log is real friction that gets skipped in favor of just
# making the pick. Owner-only (quick_log itself enforces this). Logs the TRIMMED set -- whatever
# the slider above currently shows is what actually gets offered for logging.
quick_log.render_quick_log(trimmed_legs, date_str, _active.key, key_prefix="basket")
