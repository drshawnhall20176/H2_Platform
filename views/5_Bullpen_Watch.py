"""
Bullpen Watch — tonight's whole slate, one question: which side has the fresher bullpen?

WHY THIS EXISTS, NOT A HYPOTHETICAL: a real, repeated pattern from trader discussion --
moneyline losses cluster specifically at the point the bullpen takes over, and "who got the
fresher/less-taxed pen" is something traders were already checking by hand, every night, before
placing a moneyline. That data already lives on this platform -- mlb_engine.get_team_bullpen_
fatigue and projections.bullpen_fatigued_fraction are the exact same functions Pitching Lab's own
per-game bullpen table already uses -- it just wasn't available anywhere as a quick, slate-wide
read. This page doesn't compute anything new; it reuses that same, already-proven data and boils
it down to one comparison per game instead of a deep per-pitcher table you have to build game by
game.

SCOPED TO FRESHNESS ONLY, NOT BULLPEN QUALITY -- a deliberate choice, not an oversight. Pitching
Lab already shows each reliever's own ERA/FIP/K9 alongside their workload for one selected game at
a time; duplicating that here, for every game on the slate, would roughly double the real API cost
of this page for a dimension that already has a good home. This page answers "who's fresher,"
Pitching Lab answers "and how good are they" -- see the page link below to go deeper on one game.

REAL COST, OPT-IN BY DESIGN, same posture as Pitching Lab's own bullpen section: a full team read
costs several real API calls (a schedule window plus one boxscore per recent game), and a busy
MLB night can have 15 games -- 30 teams. This page fetches the lightweight probable-starters slate
up front (build_pitching_slate, no hitters/boxscores), but the bullpen reads themselves only run
when you press the button below, not automatically on page load.
"""

import streamlit as st
from datetime import datetime

import mlb_engine as E
import projections as P
import sports

game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER   # shared with
                                                                                   # every other
                                                                                   # slate-wide page

st.title("🛡️ Bullpen Watch")
st.caption("Tonight's whole slate, one question per game: which side has the fresher bullpen?")
st.page_link("views/7_#L01f3af_Pitching_Lab.py",
             label="Want per-pitcher detail and quality (ERA/FIP) too? See Pitching Lab →",
             icon="🎯")

target = st.date_input("Slate date", datetime.now())
date_str = target.strftime("%Y-%m-%d")


@st.cache_data(ttl=600, show_spinner=False)
def load_pitching_slate(date_str_inner: str):
    return E.build_pitching_slate(date_str_inner)


with st.spinner("Loading tonight's probable starters..."):
    pitching_rows = load_pitching_slate(date_str)

if not pitching_rows:
    st.info("No probable starters found for this date yet — check back closer to first pitch.")
    st.stop()

# Reconstruct one entry per GAME from build_pitching_slate's own one-row-per-starter shape --
# shared, tested logic (mlb_engine.pair_pitching_slate_by_game), also reused by Game Watch,
# rather than each page keeping its own inline copy.
games = E.pair_pitching_slate_by_game(pitching_rows)
# Strictly chronological by actual start time -- game_dt returns a TZ-AWARE (Eastern) datetime
# or None, so the sort key separates "has a real date" from "doesn't" as its own leading tuple
# element rather than falling back to a naive datetime.max, which would crash comparing against
# a tz-aware one. Python's tuple comparison short-circuits on the first differing element, so a
# missing-date game's dummy datetime.min entry is never actually compared against a real one.
games.sort(key=lambda g: (game_dt(g["_game_date"]) is None, game_dt(g["_game_date"]) or datetime.min,
                          g["label"]))

if not games:
    st.info("Couldn't pair up both sides for any game on this date — try a different date.")
    st.stop()

# Time slot + Game filters — the same shared helpers (game_dt/slot_of/SLOT_ORDER) Matchup Lab,
# Best Bets, and Graded Picks already use, narrowing a busy night's full slate down to one part
# of it. "Game" defaults to "All games in this slot" (nothing hidden unless actively narrowed).
for g in games:
    g["_slot"] = slot_of(game_dt(g["_game_date"]))
slots_present = sorted({g["_slot"] for g in games}, key=lambda s: SLOT_ORDER.get(s, 9))

c_slot, c_game = st.columns(2)
with c_slot:
    slot_pick = st.selectbox("Time slot", ["All slate"] + slots_present)
slot_games = games if slot_pick == "All slate" else [g for g in games if g["_slot"] == slot_pick]

if not slot_games:
    st.info(f"No games in the {slot_pick} slot — try a different time slot or \"All slate\".")
    st.stop()

game_date_by_label = {g["label"]: g["_game_date"] for g in slot_games}
games_present = sorted(game_date_by_label, key=lambda lbl: game_date_by_label[lbl] or "~")


def _game_label_fmt(lbl: str) -> str:
    dt = game_dt(game_date_by_label.get(lbl))   # already Eastern-localized by game_dt itself
    return lbl if dt is None else f"{dt.strftime('%-I:%M %p ET')} — {lbl}"


with c_game:
    game_pick = st.selectbox("Game", ["All games in this slot"] + games_present,
                             format_func=lambda lbl: _game_label_fmt(lbl)
                             if lbl != "All games in this slot" else lbl)
games = (slot_games if game_pick == "All games in this slot"
        else [g for g in slot_games if g["label"] == game_pick])

if not games:
    st.info("No games match the current filters — try a different time slot or game.")
    st.stop()

st.caption(f"{len(games)} game(s) shown for {date_str}.")

if not st.button(f"🔄 Load bullpen freshness for {len(games)} game(s)",
                 help="Real cost: a schedule window plus one boxscore per team's recent game, "
                     "for both teams in every game below. Cached for 10 minutes once loaded."):
    st.info("Press the button above to load tonight's bullpen reads. Nothing is fetched until "
           "you do — a full slate is a real number of API calls, not a free page visit.")
    st.stop()


@st.cache_data(ttl=600, show_spinner=False)
def load_team_freshness(team_id, exclude_pid, date_str_inner):
    """One team's bullpen boiled down to a single freshness read for date_str_inner -- the exact
    same get_team_bullpen_fatigue + bullpen_fatigued_fraction pair Pitching Lab's own per-game
    table already uses, just called once per team here instead of once per selected game.

    Returns None only when team_id itself is missing (no real team to look up). A team WITH a
    real ID but no usable recent-appearance data still returns a dict, with "fraction": None --
    an honest "we don't know," not silently treated as "fresh" or skipped from the page."""
    if not team_id:
        return None
    fatigue = E.get_team_bullpen_fatigue(team_id, date_str_inner)
    fraction = P.bullpen_fatigued_fraction(fatigue, exclude_pid=exclude_pid)
    # fatigue is already sorted most-fatigued-first (get_team_bullpen_fatigue's own contract) --
    # its own [0] is genuinely the single most-taxed arm, not an arbitrary pick.
    most_taxed = fatigue[0] if fatigue else None
    return {"fraction": fraction, "most_taxed": most_taxed, "n_pitchers": len(fatigue)}


_TAG_ICON = {"fresh": "🟢", "taxed": "🔴", "unknown": "❔"}


def _display(freshness):
    """(icon, one-line detail) for a single team's freshness read -- the real fresh/taxed/unknown
    CLASSIFICATION comes from projections.bullpen_freshness_tag (tested in test_projections.py);
    this function only formats that classification into display text, the same "real logic lives
    in a tested module, the view just renders it" split every other page here already follows."""
    fraction = freshness["fraction"] if freshness else None
    tag = P.bullpen_freshness_tag(fraction)
    icon = _TAG_ICON[tag]
    if tag == "unknown":
        return icon, "No recent appearance data in the last 5 days"
    detail = f"{fraction:.0%} of {freshness['n_pitchers']} recent arm(s) showing fatigue signs"
    if tag == "taxed":
        mt = freshness["most_taxed"]
        if mt:
            mt_detail = mt["tag"].split(" ", 1)[1] if " " in mt["tag"] else mt["tag"]
            detail += f" — most taxed: {mt['name']} ({mt_detail})"
    return icon, detail


def _edge_line(away_name, away_fresh, home_name, home_fresh):
    """One honest sentence comparing the two sides -- the real comparison comes from
    projections.bullpen_freshness_edge (tested in test_projections.py); this just turns its
    "away"/"home"/"even"/None result into a display sentence."""
    af = away_fresh["fraction"] if away_fresh else None
    hf = home_fresh["fraction"] if home_fresh else None
    edge = P.bullpen_freshness_edge(af, hf)
    if edge is None:
        return "Not enough recent data for one or both bullpens to call this one."
    if edge == "away":
        return f"🟢 **{away_name}**'s bullpen looks fresher tonight."
    if edge == "home":
        return f"🟢 **{home_name}**'s bullpen looks fresher tonight."
    return "Both bullpens look about the same on recent workload — no clear freshness edge."


progress = st.progress(0.0, text="Checking recent bullpen usage for every team...")
for i, g in enumerate(games):
    away_row, home_row = g["away"], g["home"]
    away_fresh = load_team_freshness(away_row["_team_id"], away_row["_pid"], date_str)
    home_fresh = load_team_freshness(home_row["_team_id"], home_row["_pid"], date_str)
    g["_away_fresh"], g["_home_fresh"] = away_fresh, home_fresh
    progress.progress((i + 1) / len(games), text=f"Checked {g['label']} ({i + 1}/{len(games)})")
progress.empty()

for g in games:
    dt = game_dt(g["_game_date"])
    time_str = dt.strftime("%-I:%M %p ET") if dt else "TBD"
    away_row, home_row = g["away"], g["home"]
    with st.container(border=True):
        st.markdown(f"### {g['label']} — {time_str}")
        c1, c2 = st.columns(2)
        for col, team_name, sp_name, freshness in (
            (c1, away_row["Team"], away_row["Pitcher"], g["_away_fresh"]),
            (c2, home_row["Team"], home_row["Pitcher"], g["_home_fresh"]),
        ):
            with col:
                icon, detail = _display(freshness)
                st.markdown(f"**{team_name}** {icon}")
                st.caption(f"Starter: {sp_name}")
                st.caption(detail)
        st.markdown(_edge_line(away_row["Team"], g["_away_fresh"], home_row["Team"], g["_home_fresh"]))

st.caption(f"🟢 Fresh / 🔴 Taxed uses the same {P.BULLPEN_FATIGUE_THRESHOLD:.0%} fatigued-share "
          "threshold as every other bullpen-fatigue read on this platform (Pitching Lab, the "
          "bullpen-blended repricing on Best Bets) — a single tired reliever among several "
          "fresh arms doesn't flip a team to \"taxed.\" Excludes each team's own probable "
          "starter from tonight's game, so a recent spot start by him doesn't count against his "
          "own bullpen. This is workload only, not quality — a fresh bullpen can still be a bad "
          "one; see Pitching Lab for ERA/FIP on the specific arms involved.")
