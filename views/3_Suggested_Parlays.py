"""
Suggested Parlays — ready-made parlay options for people who don't want to comb through the
graded board themselves, built directly from the model's own top graded plays.

Five tiers by risk (Safer/Steady/Balanced/Bold/Longshot, 2 through 6 legs), each with its OWN
real objective, not just a different slice of the same ranking — Safer/Steady rank by real
probability of hitting, Balanced uses the original Conviction metric, and Bold/Longshot rank by
real payout size among plays that still cleared the actual grading floor. No leg, and no player,
ever appears in more than one tier. Two earlier versions of this feature (cumulative tiers, then
non-overlapping slices of one ranking) both got real feedback that led here — see
grading.build_suggested_parlays' own docstring for the full history and reasoning.

THE CORE SAFEGUARD, NOT AN AFTERTHOUGHT: a parlay's combined probability is only honestly the
product of each leg's own probability if the legs are independent. Two legs on the same player
almost never are (a home run leg and a total-bases leg on the same hitter are so tightly coupled
that treating them as independent would badly overstate how safe the combination looks). Every
parlay here draws from grading.build_parlay_leg_pool, which never puts two legs on the same
player into one parlay, and caps how many legs come from one game or one market — see that
function's own docstring for the full reasoning. This matters MORE here, not less: this page
exists specifically for people who don't want to dig into why a number is what it is, so the
number itself has to be honest on its own.

Works across every sport on this platform from day one — grading.py's parlay logic is genuinely
sport-agnostic, the same as the rest of grading.py.
"""

import streamlit as st
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
from datetime import datetime
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

st.title("🎫 Suggested Parlays")
st.caption(f"A few ready-made parlay options built from tonight's graded board — no digging "
          f"required — {_active.icon} {_active.label}")
st.page_link("views/4_Speculative_Basket.py", label="Prefer independent positions over a chained parlay? See Speculative Basket →",
            icon="🧺")

if not sports.require_live_engine("Suggested Parlays"):
    st.stop()

eastern = pytz.timezone("US/Eastern")


# --- controls ---------------------------------------------------------------
if _active.key == "MLB":
    target = st.date_input("Slate date", datetime.now())
    date_str = target.strftime("%Y-%m-%d")
    preferred_book = BBD.render_book_selector(key_prefix="suggested_parlays", date_str=date_str)
    with st.spinner("Building parlay options..."):
        plays, meta, rows, available_books = BBD.load_mlb_graded_picks_board(
            date_str, E.FIP_CONSTANT_DEFAULT, preferred_book)
else:
    target = st.date_input("Slate date", datetime.now(eastern))
    date_str = target.strftime("%Y-%m-%d")
    with st.spinner("Building parlay options..."):
        plays, meta = BBD.load_generic_best_bets_board(_active.key, date_str)

if not plays:
    st.info("No games on the board right now. Parlay suggestions appear here on an active slate.")
    st.stop()

# --- time slot + game filter --------------------------------------------------
# The same shared helpers (game_dt/slot_of/SLOT_ORDER) Best Bets, every Matchup Lab variant, and
# Graded Picks already use -- added directly on request, to match Matchup Lab's own filtering
# here too. A REAL, DELIBERATE REVERSAL of an earlier decision, not an oversight: an earlier
# version of this page deliberately omitted this filter, reasoned that narrowing to one game
# would usually make it impossible to fill the bigger tiers. That's still true and still honest
# -- build_suggested_parlays already skips a tier it can't fill rather than padding it, so a
# narrow slot/game selection will naturally produce fewer or smaller tiers, not broken ones.
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
# A REAL, DELIBERATE PRODUCT DECISION, not just a nice-to-have filter: an early version of this
# page auto-selected legs purely by conviction, and on a real slate three different real base
# stealers' Stolen Bases legs alone filled the Safer tier before any other market appeared —
# mathematically defensible (Stolen Bases genuinely is a more skewed market than Home Runs, so an
# elite burner's conviction ratio can legitimately run higher than an elite slugger's for a
# similar raw probability), but it read as far less realistic than what a person would actually
# build themselves. Rather than Claude unilaterally re-tuning the model's own reference
# probabilities to "fix" a skew that isn't actually wrong, the honest fix is letting a person
# choose what they want to see — the same principle behind grading.build_parlay_leg_pool's own
# max_per_market default (also tightened from 3 to 2 for the same real reason).
markets_present = sorted({pl.get("Market") for pl in plays if pl.get("Market")})
selected_markets = st.multiselect("Markets to include", options=markets_present,
                                  default=markets_present)
if not selected_markets:
    st.info("Select at least one market above to see parlay suggestions.")
    st.stop()
plays = [pl for pl in plays if pl.get("Market") in selected_markets]

# --- min probability floor ----------------------------------------------------
# A separate, ABSOLUTE floor from every tier's own grading floor below -- added directly on
# request, same shared helper Best Bets/Graded Picks/Speculative Basket all use. Applied to the
# ELIGIBLE POOL here, before either parlay mode builds from it, so it narrows what every tier
# (and Game Coverage) can even draw from, not just what's displayed after the fact. Defaults to
# 0 (no floor) so nobody's existing parlays change unless they actively set one.
min_prob_pct = st.slider("Min probability %", 0, 100, 0, 5,
                         help="Raw ModelProb floor on which legs are even eligible for a parlay "
                             "-- 0 means no floor. Independent of each tier's own real grading "
                             "floor (Bold/Longshot's \"C\" minimum, etc.).")
plays = grading.filter_min_probability(plays, min_prob_pct / 100.0)

if not plays:
    st.info("No plays clear the current min probability floor — try lowering it.")
    st.stop()

# --- parlay mode: Suggested tiers vs Game Coverage parlay ---------------------------------
# Added directly on request, after the same real gap Speculative Basket's own Game Coverage
# mode was built to answer: even Suggested Parlays' own "safety"-objective tiers (Safer/Steady)
# still require clearing conviction_to_grade's real edge floor, and a real, reported strategy
# (one safe pick per game) mostly doesn't clear it -- Total Hits' own reference (0.65) is already
# high, so a real, good 65-77% pick barely beats "typical." Chained here (unlike Speculative
# Basket's independent positions) since this page's whole point is a single, combined, all-must-
# hit ticket -- and it's SAFE to chain this way: build_game_coverage_picks already guarantees at
# most one leg per game, so every leg comes from a genuinely different game, the same level of
# independence every other tier on this page already accepts.
mode = st.radio("Parlay mode", ["Suggested tiers (5 objectives)", "Game Coverage parlay (one safest pick per game)"],
                horizontal=True,
                help="Suggested tiers: the original 5-tier behavior (Safer/Steady/Balanced/Bold/"
                    "Longshot), each with its own objective, among plays that already clear a "
                    "real edge floor. Game Coverage parlay: one safest pick per game, chained "
                    "into a single ticket -- no edge floor, since the point is covering every "
                    "game, not finding the biggest edge.")

if mode == "Game Coverage parlay (one safest pick per game)":
    c_mkt, c_side = st.columns(2)
    sorted_markets = sorted(selected_markets)
    default_idx = sorted_markets.index("Batter Total Hits") if "Batter Total Hits" in sorted_markets else 0
    with c_mkt:
        coverage_market = st.selectbox("Market", options=sorted_markets, index=default_idx)
    with c_side:
        coverage_side = st.selectbox("Side", options=["Over", "Under"])
    parlays = [grading.build_game_coverage_parlay(plays, market=coverage_market, side=coverage_side)]
    if not parlays[0]["legs"]:
        st.info(f"No {coverage_market} {coverage_side} play found for any game in the current "
                f"filter — try a different market/side, or check back closer to first pitch.")
        st.stop()
    st.caption(f"One pick per game, chained into a single parlay — the highest-probability "
              f"{coverage_market} {coverage_side} play in each game currently in view. No edge "
              f"floor: some legs may show \"No edge floor\" instead of a letter grade, which is "
              f"expected — it means that specific leg doesn't carry validated edge over what's "
              f"typical for this market, even though it's still the safest real option in that "
              f"game.")
else:
    parlays = grading.build_suggested_parlays(plays)

    if not parlays:
        st.info("Not enough diverse graded plays match the selected markets to safely build a "
                "parlay — try including more markets, or check back closer to first pitch.")
        st.stop()

st.info(
    "⚠️ **Parlays are high-variance, even when every leg looks good.** A 60% chance on each of "
    "6 legs is still only about a 5% chance of hitting all six — the odds below reflect that "
    "real math, not a guarantee. Combined odds assume each leg is independent; legs here never "
    "share a player (the single biggest way that assumption breaks), but two legs from the same "
    "game can still carry some real, smaller correlation the math below doesn't fully capture.\n\n"
    "📊 **What \"Fair\" means**: Fair odds are what a bet would need to pay to be break-even, "
    "given the model's own probability — not what a sportsbook is actually offering. A big "
    "negative number (like -480) means the model thinks this is VERY likely to happen, which is "
    "exactly why it can still earn a high grade — it's not a bad price, it's the model saying "
    "it's confident. Compare it to what your book actually offers to see if there's real value."
)

GRADE_COLOR = {"A": "#16783c", "B": "#2e7d32", "C": "#b8860b", "D": "#6b7280"}
TIER_ICON = {"Safer": "🟢", "Steady": "🔵", "Balanced": "🟡", "Bold": "🟠", "Longshot": "🔴",
            "Game Coverage": "🗺️"}


def _grade_badge(grade) -> str:
    # Handles None honestly, not by hiding it -- a Game Coverage pick with no real edge over
    # typical still gets shown (it's still the safest option in that game), just labeled as
    # such rather than crashing. Same fix already applied to Speculative Basket.
    if grade is None:
        return ("<span style='background:#374151;color:#d1d5db;padding:1px 8px;border-radius:6px;"
               "font-weight:700;font-size:0.85em;'>No edge floor</span>")
    color = GRADE_COLOR.get(grade["letter"], "#6b7280")
    return (f"<span style='background:{color};color:white;padding:1px 8px;border-radius:6px;"
           f"font-weight:700;font-size:0.85em;'>{grade['letter']}</span>")


for parlay in parlays:
    icon = TIER_ICON.get(parlay["tier"], "🎫")
    with st.container(border=True):
        c1, c2 = st.columns([3, 1])
        with c1:
            st.markdown(f"### {icon} {parlay['tier']} — {parlay['size']}-leg parlay")
        with c2:
            fair = parlay["combined_fair_american"]
            fair_str = f"{fair:+d}" if fair is not None else "—"
            st.metric("Combined Fair Odds", fair_str)
        st.caption(f"Model's combined win probability: {parlay['combined_prob']:.1%} "
                  f"(assuming independent legs — see the note above)")

        # Ranking, added directly on request: multiple legs can share the same letter grade
        # while still having meaningfully different real probabilities behind them. Ranked by
        # ModelProb (real probability of hitting), not rank_value/letter grade -- this page is
        # explicitly framed around "which of these is more likely to actually hit," a different
        # question than "which has the better edge relative to typical," so the ranking follows
        # the question this page actually answers, not Graded Picks' own letter-grade framing.
        grading.rank_flat_plays(parlay["legs"], key="ModelProb")

        for leg in parlay["legs"]:
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
            # The opposing starter's real name/ERA, straight from the same play dict, added
            # directly on request -- so the actual matchup being faced is visible right here,
            # without needing to separately cross-reference Pitching Lab to check whether the
            # model's read on that pitcher matches who's actually expected to start.
            opp_name, opp_era = leg.get("Opp"), leg.get("OppERA")
            opp_str = f" · vs {opp_name} ({opp_era:.2f} ERA)" if opp_name and opp_era is not None else ""
            st.caption(f"{leg.get('Game', '')}{opp_str} · {leg.get('Why', '')}")
            if lineup == "Projected":
                # A REAL, confirmed reason this matters, not a routine caveat: this platform's
                # own lineup source falls back to a team's full active roster when the actual
                # posted batting order for THIS specific game isn't available yet -- a real,
                # confirmed doubleheader case showed a player still appearing here despite
                # reportedly being questionable for that specific game, since he was still on
                # the active roster even though he may not have been in that game's own lineup.
                st.caption("🟡 Lineup not yet confirmed for this game — a player shown here "
                          "could still be scratched before first pitch.")

        # Quick-log widget, added directly on request: during a real, narrow pick-making
        # window, having to separately re-enter a pick into Bet Log is real friction that gets
        # skipped in favor of just making the pick. Owner-only (quick_log itself enforces this),
        # keyed per tier so each tier's own multiselect/button don't collide with another tier's.
        quick_log.render_quick_log(parlay["legs"], date_str, _active.key,
                                   key_prefix=f"parlays_{parlay['tier']}")
