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
st.page_link("views/19_Speculative_Basket.py", label="Prefer independent positions over a chained parlay? See Speculative Basket →",
            icon="🧺")

if not sports.require_live_engine("Suggested Parlays"):
    st.stop()

eastern = pytz.timezone("US/Eastern")


# --- controls ---------------------------------------------------------------
if _active.key == "MLB":
    target = st.date_input("Slate date", datetime.now())
    date_str = target.strftime("%Y-%m-%d")
    with st.spinner("Building parlay options..."):
        plays, meta, rows = BBD.load_mlb_graded_picks_board(date_str, E.FIP_CONSTANT_DEFAULT)
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
TIER_ICON = {"Safer": "🟢", "Steady": "🔵", "Balanced": "🟡", "Bold": "🟠", "Longshot": "🔴"}


def _grade_badge(grade: dict) -> str:
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

        for leg in parlay["legs"]:
            grade_html = _grade_badge(leg["_grade"])
            leg_fair = leg.get("Fair")
            leg_fair_str = f"{leg_fair:+d}" if leg_fair is not None else "—"
            lineup = leg.get("Lineup")
            lineup_icon = "🟡 " if lineup == "Projected" else ("🟢 " if lineup == "Confirmed" else "")
            st.markdown(
                f"{grade_html} {lineup_icon}**{leg['Player']}** ({leg['Team']}) — {leg['Market']} "
                f"{leg['Side']} {leg['Line']:g} · Fair odds {leg_fair_str}",
                unsafe_allow_html=True,
            )
            st.caption(f"{leg.get('Game', '')} · {leg.get('Why', '')}")
            if lineup == "Projected":
                # A REAL, confirmed reason this matters, not a routine caveat: this platform's
                # own lineup source falls back to a team's full active roster when the actual
                # posted batting order for THIS specific game isn't available yet -- a real,
                # confirmed doubleheader case showed a player still appearing here despite
                # reportedly being questionable for that specific game, since he was still on
                # the active roster even though he may not have been in that game's own lineup.
                st.caption("🟡 Lineup not yet confirmed for this game — a player shown here "
                          "could still be scratched before first pitch.")
