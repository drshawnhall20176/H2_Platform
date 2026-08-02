"""
First Innings Totals — on-demand "Team Total Runs - First N Innings" projection, one game and
one batting side at a time.

WHAT THIS PROJECTS: mlb_engine/projections already had the real inputs and model for this market
built (get_team_recent_first_innings_runs, get_pitcher_recent_first_innings_allowed,
project_team_first_innings_total, prob_over_first_innings_line) — this page is the missing UI on
top of them. Every number shown comes from those tested functions; this file only picks a game/
side, calls them, and renders the result.

METHOD, STATED PLAINLY (see project_team_first_innings_total's own docstring for the full real
reasoning): the projected rate is a simple average of the BATTING TEAM's own recent scoring rate
in innings 1-N and the OPPOSING STARTER's own recent runs-allowed rate in innings 1-N — pitcher-
specific, not a team-wide bullpen blend, since this market is fundamentally about how THIS
starter has pitched early. Runs are then simulated via a Poisson draw at that blended rate.

REAL COST, OPT-IN BY DESIGN, same posture as Bullpen Watch: a full read costs a team-schedule
window plus one linescore fetch per recent game for the batting team, plus one linescore fetch
per recent start for the opposing starter — genuinely more than a free page load, so nothing
past picking the game/side runs until the button below is pressed.

NO LIVE ODDS FEED for this market yet (no odds_api mapping exists for first-innings team totals
on this platform) — the line you check probability against is entered by hand, always labeled as
a model read, never presented as a live sportsbook quote.
"""

import streamlit as st
import components as C
from datetime import datetime
import pytz

import sports
import mlb_engine as E
import projections as P

eastern = pytz.timezone("US/Eastern")
game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER   # shared with
                                                                                   # every other
                                                                                   # slate-wide page

C.base_css()
C.page_header("1️⃣", "First Innings Totals",
             "Team Total Runs - First N Innings — pick a game, pick a side, see the real "
             "blended projection.")

if not sports.require_sport(["MLB"], "First Innings Totals"):
    st.stop()


@st.cache_data(ttl=300, show_spinner="Loading probable starters…")
def load_pitching_slate(date_str_inner: str):
    return E.build_pitching_slate(date_str_inner)


c_date, c_refresh = st.columns([2, 1])
with c_date:
    date_str = st.date_input("Slate date", datetime.now(eastern)).strftime("%Y-%m-%d")
with c_refresh:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

pitching_rows = load_pitching_slate(date_str)
if not pitching_rows:
    st.info("No probable starters found for this date yet — check back closer to first pitch.")
    st.stop()

# One entry per GAME from build_pitching_slate's own one-row-per-starter shape — shared, tested
# logic (mlb_engine.pair_pitching_slate_by_game), same reuse Bullpen Watch/Game Watch already do
# rather than a page-local reimplementation.
games = E.pair_pitching_slate_by_game(pitching_rows)
games.sort(key=lambda g: (game_dt(g["_game_date"]) is None, game_dt(g["_game_date"]) or datetime.min,
                          g["label"]))

if not games:
    st.info("Couldn't pair up both sides for any game on this date — try a different date.")
    st.stop()

# Time slot filter narrows a busy night before picking ONE specific game — this page projects a
# single side of a single game, so (unlike Bullpen Watch) there's no "all games" option here.
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
    game_pick = st.selectbox("Game", games_present, format_func=_game_label_fmt)

selected_game = next(g for g in slot_games if g["label"] == game_pick)
away_row, home_row = selected_game["away"], selected_game["home"]

side_labels = {f"{away_row['Team']} (away)": "away", f"{home_row['Team']} (home)": "home"}
side_pick = st.radio("Which side's runs?", list(side_labels.keys()), horizontal=True)
batting_row = away_row if side_labels[side_pick] == "away" else home_row
opposing_row = home_row if side_labels[side_pick] == "away" else away_row

n_innings_label = st.radio("Market", ["First 3 Innings", "First 5 Innings"], horizontal=True)
n_innings = 3 if n_innings_label == "First 3 Innings" else 5

st.caption(f"Projecting **{batting_row['Team']}** runs scored in the first {n_innings} innings, "
          f"facing **{opposing_row['Pitcher']}** ({opposing_row['Team']}).")

if not st.button(f"🔄 Load {batting_row['Team']} first-{n_innings}-innings projection",
                 help="Real cost: a schedule window plus one linescore fetch per recent game for "
                     f"{batting_row['Team']}, plus one linescore fetch per recent start for "
                     f"{opposing_row['Pitcher']}. Cached for 10 minutes once loaded."):
    st.info("Press the button above to run this projection. Nothing is fetched until you do.")
    st.stop()


@st.cache_data(ttl=600, show_spinner=False)
def load_team_recent(team_id: int, before_date: str, n_innings_inner: int):
    return E.get_team_recent_first_innings_runs(team_id, before_date, n_innings=n_innings_inner)


@st.cache_data(ttl=600, show_spinner=False)
def load_pitcher_allowed(pitcher_id: int, season: int, before_date: str, n_innings_inner: int):
    return E.get_pitcher_recent_first_innings_allowed(pitcher_id, season, before_date,
                                                       n_innings=n_innings_inner)


season = int(date_str[:4])
with st.spinner(f"Pulling {batting_row['Team']}'s recent first-{n_innings}-innings scoring..."):
    team_recent = load_team_recent(batting_row["_team_id"], date_str, n_innings)
with st.spinner(f"Pulling {opposing_row['Pitcher']}'s recent first-{n_innings}-innings runs "
                f"allowed..."):
    pitcher_allowed = load_pitcher_allowed(opposing_row["_pid"], season, date_str, n_innings)

if not team_recent or not pitcher_allowed:
    missing = []
    if not team_recent:
        missing.append(f"{batting_row['Team']}'s own recent first-{n_innings}-innings scoring")
    if not pitcher_allowed:
        missing.append(f"{opposing_row['Pitcher']}'s own recent first-{n_innings}-innings runs "
                       "allowed")
    st.warning("Not enough real recent data to project this yet — missing: "
              f"{'; '.join(missing)}.")
    st.stop()

proj = P.project_team_first_innings_total(team_recent, pitcher_allowed, sims=P.DEFAULT_SIMS,
                                          seed=7)
if not proj:
    st.warning("Couldn't build a projection from the data pulled — try a different game or side.")
    st.stop()

m1, m2, m3 = st.columns(3)
m1.metric(f"{batting_row['Team']} own rate", f"{proj['team_rate']:.2f} runs/G")
m2.metric(f"{opposing_row['Pitcher']} allowed rate", f"{proj['pitcher_allowed_rate']:.2f} runs/G")
m3.metric("Projected runs (blended)", f"{proj['projected_runs']:.2f}")

st.caption(f"Blend is a simple average of {batting_row['Team']}'s own real scoring rate over its "
          f"last {team_recent['games']} game(s) and {opposing_row['Pitcher']}'s own real "
          f"runs-allowed rate over his last {pitcher_allowed['games']} start(s), both in innings "
          f"1-{n_innings}.")

line = st.number_input(
    f"Line to check ({batting_row['Team']}, first {n_innings} innings runs, over/under)",
    min_value=0.0, value=1.5, step=0.5)
probs = P.prob_over_first_innings_line(proj["sim"], line)

p1, p2 = st.columns(2)
p1.metric(f"P(Over {line:g})", f"{probs['prob_over']:.0%}")
p2.metric(f"P(Under {line:g})", f"{probs['prob_under']:.0%}")

st.caption("Model-only line — no live sportsbook feed exists yet for this market on this "
          "platform, so check this against whatever number your book is actually posting before "
          f"betting it. Simulated via a Poisson draw at the blended rate above, "
          f"{P.DEFAULT_SIMS:,} trials, reproducible with the same inputs.")
