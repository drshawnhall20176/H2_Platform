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

st.title("🧺 Speculative Basket")
st.caption(f"Several small, independent high-upside positions — not a parlay, no \"all must "
          f"hit\" combination — {_active.icon} {_active.label}")
st.page_link("views/18_Suggested_Parlays.py", label="Looking for a chained, all-must-hit parlay instead? See Suggested Parlays →",
            icon="🎫")

if not sports.require_live_engine("Speculative Basket"):
    st.stop()

eastern = pytz.timezone("US/Eastern")


# --- controls ---------------------------------------------------------------
if _active.key == "MLB":
    target = st.date_input("Slate date", datetime.now())
    date_str = target.strftime("%Y-%m-%d")
    with st.spinner("Building the basket..."):
        plays, meta, rows = BBD.load_mlb_graded_picks_board(date_str, E.FIP_CONSTANT_DEFAULT)
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

c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Positions in basket", len(basket["legs"]))
with c2:
    st.metric("P(at least one hits)", f"{basket['prob_at_least_one_hits']:.1%}")
with c3:
    st.metric("Expected hits", f"{basket['expected_hits']:.1f}")
st.caption("\"P(at least one hits)\" and \"Expected hits\" assume independence across positions "
          "— the same-player exclusion below removes the single biggest way that assumption "
          "breaks, but positions sharing a game can still carry some real, smaller correlation "
          "this doesn't fully capture.")

GRADE_COLOR = {"A": "#16783c", "B": "#2e7d32", "C": "#b8860b", "D": "#6b7280"}


def _grade_badge(grade: dict) -> str:
    color = GRADE_COLOR.get(grade["letter"], "#6b7280")
    return (f"<span style='background:{color};color:white;padding:1px 8px;border-radius:6px;"
           f"font-weight:700;font-size:0.85em;'>{grade['letter']}</span>")


with st.container(border=True):
    for leg in basket["legs"]:
        grade_html = _grade_badge(leg["_grade"])
        leg_fair = leg.get("Fair")
        leg_fair_str = f"{leg_fair:+d}" if leg_fair is not None else "—"
        st.markdown(
            f"{grade_html} **{leg['Player']}** ({leg['Team']}) — {leg['Market']} "
            f"{leg['Side']} {leg['Line']:g} · Fair odds {leg_fair_str}",
            unsafe_allow_html=True,
        )
        st.caption(f"{leg.get('Game', '')} · {leg.get('Why', '')}")
        st.markdown("")
