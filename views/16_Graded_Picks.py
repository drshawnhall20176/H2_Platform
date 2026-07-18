"""
Graded Picks — every game on the slate, graded, not a flat top-10.

WHY GAME-BY-GAME, NOT A RANKED LIST: a flat top-N would naturally cluster on whichever 2-3 games
happen to have the juiciest matchups that night, leaving the rest of the slate invisible to
anyone specifically interested in a different game. Games are shown here in full, sorted with the
most interesting first (by each game's own best play), so the whole slate stays visible — nothing
silently dropped, just organized by what's actually worth a look first.

Letter grades and tier labels here are THIS PLATFORM'S OWN wording and thresholds, grounded in
its own already-established Conviction scale — not reverse-engineered from, or copied from, any
other product's scoring or badge text. See projections.conviction_to_grade's own docstring for
the full reasoning.
"""

import streamlit as st
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
from datetime import datetime
import pytz

import sports
import best_bets_data as BBD

_active = sports.active()
E, P = _active.engine, _active.projections
game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER   # shared with
                                                                                   # Best Bets and
                                                                                   # every Matchup
                                                                                   # Lab variant

st.title("🏅 Graded Picks")
st.caption(f"Every game on the slate, graded — sorted with the most interesting first, not a "
          f"flat top-10 that hides the rest of the board — {_active.icon} {_active.label}")

if not sports.require_live_engine("Graded Picks"):
    st.stop()

eastern = pytz.timezone("US/Eastern")


# --- controls ---------------------------------------------------------------
if _active.key == "MLB":
    target = st.date_input("Slate date", datetime.now())
    date_str = target.strftime("%Y-%m-%d")
    with st.spinner("Grading the slate..."):
        plays, meta, rows = BBD.load_mlb_graded_picks_board(date_str, E.FIP_CONSTANT_DEFAULT)
else:
    target = st.date_input("Slate date", datetime.now(eastern))
    date_str = target.strftime("%Y-%m-%d")
    with st.spinner("Grading the slate..."):
        plays, meta = BBD.load_generic_best_bets_board(_active.key, date_str)
    rows = None   # the one-sided banner is MLB-specific (compares starting pitchers) — not
                 # available for other sports, and deliberately not faked for them

if not plays:
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

# organize_graded_picks (projections.py) does the grading, grouping, and sorting — kept as a
# separate, testable function rather than embedded here, so this real logic is actually unit
# tested, not just trusted by eye in the browser.
organized = P.organize_graded_picks(plays)

if not organized:
    st.info("Nothing on tonight's slate clears the grading floor yet — check back closer to "
            "first pitch as lineups and matchups firm up.")
    st.stop()

GRADE_COLOR = {"A": "#16783c", "B": "#2e7d32", "C": "#b8860b", "D": "#6b7280"}


def _grade_badge(grade: dict) -> str:
    color = GRADE_COLOR.get(grade["letter"], "#6b7280")
    return (f"<span style='background:{color};color:white;padding:2px 10px;border-radius:6px;"
           f"font-weight:700;font-size:0.95em;'>{grade['letter']}</span> "
           f"<span style='color:{color};font-weight:600;'>{grade['tier']}</span> "
           f"<span style='opacity:0.7;'>({grade['conviction']:.2f}×)</span>")


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
            st.markdown(f"**{player_entry['player']}** ({player_entry['team']})")
            for pl in player_entry["plays"]:
                grade_html = _grade_badge(pl["_grade"])
                fair = pl.get("Fair")
                fair_str = f"{fair:+d}" if fair is not None else "—"
                st.markdown(
                    f"{grade_html} — {pl['Market']} {pl['Side']} {pl['Line']:g} · Fair {fair_str}",
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
