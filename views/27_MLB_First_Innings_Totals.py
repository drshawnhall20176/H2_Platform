"""
First Innings Totals — on-demand "Team Total Runs, First N Innings" projection, one game and one
batting side at a time. Real, tradeable DraftKings markets, both offered side by side: "Team
Total Runs - 1st 3 Innings" and "Team Total Runs - 1st 5 Innings" (confirmed directly from a real
DK bet slip, not a secondary betting-guide source -- an earlier draft of this page dropped First
3 Innings entirely on the mistaken belief it wasn't real; it is, and this page offers both again).

WHAT THIS PROJECTS: mlb_engine/projections already had the real inputs and model for this market
built (get_team_recent_first_innings_runs, get_pitcher_recent_first_innings_allowed,
project_team_first_innings_total, prob_over_first_innings_line) — this page is the missing UI on
top of them. Every number shown comes from those tested functions; this file only picks a game/
side/window, calls them, and renders the result.

METHOD, STATED PLAINLY (see project_team_first_innings_total's own docstring for the full real
reasoning): the projected rate is a simple average of the BATTING TEAM's own recent scoring rate
in innings 1-N and the OPPOSING STARTER's own recent runs-allowed rate in innings 1-N — pitcher-
specific, not a team-wide bullpen blend, since this market is fundamentally about how THIS
starter has pitched early. Runs are then simulated via a Poisson draw at that blended rate.

REAL COST, OPT-IN BY DESIGN, same posture as Bullpen Watch: a full read costs a team-schedule
window plus one linescore fetch per recent game for the batting team, plus one linescore fetch
per recent start for the opposing starter — genuinely more than a free page load, so nothing
past picking the game/side/window runs until the button below is pressed.

NO LIVE ODDS FEED for this market, on either window, and this is a real, confirmed gap in this
platform's specific data source, not a claim that the market itself isn't real (it plainly is,
per the DK slip above): The Odds API's own published period-markets coverage (v1) is first-5-
innings ONLY (h2h_1st_5_innings, spreads_1st_5_innings, totals_1st_5_innings), with no first-3-
innings key at all -- and even its 5-innings totals key is a combined GAME total (both teams'
runs together), not a TEAM-specific total for either window, at any plan tier. So a real price
genuinely can't be pulled for this exact market on this platform right now, for 3 or 5 innings,
even though real books plainly offer it. The line you check probability against is entered by
hand, always labeled as a model read, never presented as a live sportsbook quote -- and CLV
against a real captured price can't be tracked here until/unless a different data source covers it.

BET LOG: logging is wired in (same shared quick_log widget every other actionable page already
uses), and a logged pick here DOES auto-grade for BOTH windows -- bet_settlement.py's own
TEAM_TOTAL_MARKETS entries for "First 3 Innings Total"/"First 5 Innings Total" settle it against
the real linescore for that window once the game goes Final, the same automated pipeline
Moneyline picks already get. Auto-grading doesn't need a live price at all (it only needs the
real final result), so it's real value here even though CLV tracking isn't possible yet.
"""

import streamlit as st
import components as C
from datetime import datetime
import pytz

import sports
import mlb_engine as E
import projections as P
import quick_log

eastern = pytz.timezone("US/Eastern")
game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER   # shared with
                                                                                   # every other
                                                                                   # slate-wide page

# Real DK market names for each window, used verbatim as this page's own Market values -- must
# match bet_settlement.TEAM_TOTAL_MARKETS' own keys exactly, or a logged pick here silently can't
# auto-grade. Keyed by n_innings so the picker below and the settlement lookup share one source.
MARKET_BY_N = {3: "First 3 Innings Total", 5: "First 5 Innings Total"}

C.base_css()
C.page_header("1️⃣", "First Innings Totals",
             "Team Total Runs, First 3 or First 5 Innings — pick a game, pick a side, see the "
             "real blended projection.")

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

# Time slot filter narrows a busy night before picking a game (or all of them, see the "All
# Games" option below) — unlike Bullpen Watch's own slate-wide view, this page still needs a
# side/game context for its single-play flow, so the slot filter stays useful even with "All
# Games" available.
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
    if lbl == "All Games":
        return "All Games"
    dt = game_dt(game_date_by_label.get(lbl))   # already Eastern-localized by game_dt itself
    return lbl if dt is None else f"{dt.strftime('%-I:%M %p ET')} — {lbl}"


with c_game:
    # "All Games" first, added directly on request -- a real, meaningfully bigger read (every
    # game in the current time-slot filter, both sides each), not a free toggle, so it's opt-in
    # the same way the single-game button below already is, not a default.
    game_pick = st.selectbox("Game", ["All Games"] + games_present, format_func=_game_label_fmt)

market_pick = st.radio("Market", ["Team Total Runs - 1st 3 Innings", "Team Total Runs - 1st 5 Innings"],
                       horizontal=True)
n_innings = 3 if market_pick.endswith("3 Innings") else 5
market_name = MARKET_BY_N[n_innings]


@st.cache_data(ttl=600, show_spinner=False)
def load_team_recent(team_id: int, before_date: str, n_innings_inner: int):
    return E.get_team_recent_first_innings_runs(team_id, before_date, n_innings=n_innings_inner)


@st.cache_data(ttl=600, show_spinner=False)
def load_pitcher_allowed(pitcher_id: int, season: int, before_date: str, n_innings_inner: int):
    return E.get_pitcher_recent_first_innings_allowed(pitcher_id, season, before_date,
                                                       n_innings=n_innings_inner)


season = int(date_str[:4])

if game_pick == "All Games":
    # A full-slate OVERVIEW table, not the same single-play flow -- deliberately no side picker
    # (both sides shown for every game), no manual line entry (a single typed line can't mean the
    # same thing across teams with very different real scoring rates, so a fixed, honest 1.5
    # reference is used for every row -- the same default value the single-game view itself
    # starts on), and no Bet Log logging here (quick_log logs ONE specific pick; pick a specific
    # game/side below instead to log it). REAL COST, STATED PLAINLY: roughly 4 real fetches per
    # game (both teams' own recent scoring + both opposing starters' own recent runs allowed),
    # not 2 -- genuinely bigger than the single-game button below, so still gated behind its own
    # explicit button, never run automatically just because "All Games" was picked from the list.
    REFERENCE_LINE = 1.5
    st.caption(f"Every game in the **{slot_pick}** slot, both sides, first {n_innings} innings — "
              f"checked against a fixed {REFERENCE_LINE:g}-run reference line for every row "
              "(a single typed line can't mean the same thing across teams with different real "
              "scoring rates). Pick a specific game above to check a custom line or log a pick.")

    if not st.button(f"🔄 Load All Games first-{n_innings}-innings projections "
                     f"({len(slot_games)} game(s), both sides)",
                     help=f"Real cost: roughly 4 real fetches per game — both teams' own recent "
                         f"scoring plus both opposing starters' own recent runs allowed — "
                         f"{len(slot_games)} game(s) means real cost scales with slate size. "
                         "Each fetch is cached for 10 minutes once loaded, and any game already "
                         "checked individually above is already a cache hit here."):
        st.info("Press the button above to run this projection. Nothing is fetched until you do.")
        st.stop()

    rows = []
    progress = st.progress(0.0, text="Loading...")
    for i, g in enumerate(slot_games):
        for side_key, batting_row, opposing_row in (("away", g["away"], g["home"]),
                                                     ("home", g["home"], g["away"])):
            progress.progress((i + (0.5 if side_key == "home" else 0.0)) / len(slot_games),
                              text=f"Loading {batting_row['Team']}...")
            team_recent = load_team_recent(batting_row["_team_id"], date_str, n_innings)
            pitcher_allowed = load_pitcher_allowed(opposing_row["_pid"], season, date_str, n_innings)
            if not team_recent or not pitcher_allowed:
                continue   # honestly skipped, not padded with a guessed row -- same "not enough
                          # real recent data yet" case the single-game view surfaces explicitly
            proj = P.project_team_first_innings_total(team_recent, pitcher_allowed,
                                                       sims=P.DEFAULT_SIMS, seed=7)
            if not proj:
                continue
            probs = P.prob_over_first_innings_line(proj["sim"], REFERENCE_LINE)
            rows.append({
                "Game": g["label"], "Team": batting_row["Team"],
                "Opp Pitcher": opposing_row["Pitcher"],
                "Own Rate": round(proj["team_rate"], 2),
                "Opp Allowed Rate": round(proj["pitcher_allowed_rate"], 2),
                "Projected Runs": round(proj["projected_runs"], 2),
                f"P(Over {REFERENCE_LINE:g})": f"{probs['prob_over']:.0%}",
                f"P(Under {REFERENCE_LINE:g})": f"{probs['prob_under']:.0%}",
            })
    progress.empty()

    if not rows:
        st.warning("Not enough real recent data to project any game in this slot yet.")
        st.stop()

    st.dataframe(rows, hide_index=True, width="stretch")
    st.caption("Model-only — same real gap as the single-game view: this platform's own odds "
              f"provider has no live price for this market. Simulated via a Poisson draw at "
              f"each row's own blended rate, {P.DEFAULT_SIMS:,} trials, reproducible with the "
              "same inputs.")
    st.stop()

selected_game = next(g for g in slot_games if g["label"] == game_pick)
away_row, home_row = selected_game["away"], selected_game["home"]

side_labels = {f"{away_row['Team']} (away)": "away", f"{home_row['Team']} (home)": "home"}
side_pick = st.radio("Which side's runs?", list(side_labels.keys()), horizontal=True)
batting_row = away_row if side_labels[side_pick] == "away" else home_row
opposing_row = home_row if side_labels[side_pick] == "away" else away_row

st.caption(f"Projecting **{batting_row['Team']}** runs scored in the first {n_innings} innings, "
          f"facing **{opposing_row['Pitcher']}** ({opposing_row['Team']}).")

if not st.button(f"🔄 Load {batting_row['Team']} first-{n_innings}-innings projection",
                 help="Real cost: a schedule window plus one linescore fetch per recent game for "
                     f"{batting_row['Team']}, plus one linescore fetch per recent start for "
                     f"{opposing_row['Pitcher']}. Cached for 10 minutes once loaded."):
    st.info("Press the button above to run this projection. Nothing is fetched until you do.")
    st.stop()


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

# ADDED DIRECTLY ON REQUEST -- a real, numbers-filled-in breakdown of why THIS market's own
# percentages are what they are, not a generic restatement of the caption above it. Uses the
# actual real inputs this specific projection was built from (team_recent/pitcher_allowed/proj),
# not a re-derivation -- if the numbers shown here ever disagreed with the metrics above, that
# would itself be a real bug, so this reads directly off the same values already computed.
with st.expander(f"🔍 How this {n_innings}-inning projection was calculated"):
    team_games = team_recent.get("games", 0)
    pitcher_starts = pitcher_allowed.get("games", 0)
    st.markdown(
        f"**1. {batting_row['Team']}'s own real scoring rate** — "
        f"{proj['team_rate']:.2f} runs/game in innings 1-{n_innings}, over its last "
        f"{team_games} real game(s)."
    )
    if team_games < 8:
        st.caption(f"⚠️ Only {team_games} real game(s) behind this side of the blend — thinner "
                  "than the platform's own usual 15-game window (early season, a recent "
                  "callup/trade, or a short recent stretch of clean linescore data). Real, not "
                  "fabricated, but weight it accordingly.")

    st.markdown(
        f"**2. {opposing_row['Pitcher']}'s own real runs-allowed rate** — "
        f"{proj['pitcher_allowed_rate']:.2f} runs/start allowed in innings 1-{n_innings}, over "
        f"his last {pitcher_starts} real start(s)."
    )
    if pitcher_starts < 5:
        st.caption(f"⚠️ Only {pitcher_starts} real start(s) behind this side of the blend — "
                  "thinner than the platform's own usual 10-start window (early season, a "
                  "recent callup, or an IL stint). Real, not fabricated, but weight it "
                  "accordingly.")

    st.markdown(
        f"**3. The blend** — a plain average of the two, not a multiplicative/log5 combination: "
        f"({proj['team_rate']:.2f} + {proj['pitcher_allowed_rate']:.2f}) / 2 = "
        f"**{proj['projected_runs']:.2f} projected runs**. Deliberately simple: a real "
        "multiplicative blend needs a real, current league-average first-N-innings runs figure "
        "to normalize against, which this platform doesn't have verified yet — averaging two "
        "already-real, already-fetched rates avoids inventing a third, unverified number just "
        "to look more sophisticated than the data underneath actually supports."
    )

    st.markdown(
        f"**4. Why {line:g} lands at {probs['prob_over']:.0%}/{probs['prob_under']:.0%}** — "
        f"{proj['projected_runs']:.2f} is the MEAN of a simulated Poisson distribution "
        f"({P.DEFAULT_SIMS:,} real trials, not a formula shortcut), the same real distribution "
        "every count-based outcome on this platform is simulated from. The percentages are "
        f"simply the real share of those {P.DEFAULT_SIMS:,} trials that landed above/below "
        f"{line:g} — a Poisson distribution is naturally right-skewed at a mean this low, which "
        "is exactly why the Under side usually reads meaningfully higher than the Over side at "
        "a small mean like this, even before any matchup-specific edge is considered."
    )
    st.caption("First 3 vs First 5 use this exact same real method — only the two real inputs "
              "(team's own rate, pitcher's own allowed rate) change, both recomputed for "
              "whichever window is selected above, never scaled or estimated from the other "
              "window's own numbers.")

st.caption("Model-only line — this platform's own odds provider has no live price for this exact "
          "market on either window (see this page's own module docstring for the specifics), so "
          "check this against whatever number your book is actually posting before betting it. "
          f"Simulated via a Poisson draw at the blended rate above, {P.DEFAULT_SIMS:,} trials, "
          "reproducible with the same inputs.")

# Bet Log logging -- same shared quick_log widget Game Watch/Pitching Lab/Dinger Engine already
# use. "Player" carries the TEAM name here (reused field, no dedicated team column in betlog's
# own schema -- see bet_settlement.TEAM_TOTAL_MARKETS' own comment), not a literal player. No
# offers/moneylines passed through (none exist for this market, see module docstring), so every
# logged pick here honestly falls back to the model's own Fair price -- entry_odds_source will
# always read "model_fair", never "book", until/unless a real data source covers this market.
fit_plays = [
    {"Player": batting_row["Team"], "PlayerId": None, "Game": selected_game["label"],
     "Market": market_name, "Side": "Over", "Line": line,
     "Fair": P.prob_to_american(probs["prob_over"]), "ModelProb": probs["prob_over"]},
    {"Player": batting_row["Team"], "PlayerId": None, "Game": selected_game["label"],
     "Market": market_name, "Side": "Under", "Line": line,
     "Fair": P.prob_to_american(probs["prob_under"]), "ModelProb": probs["prob_under"]},
]
quick_log.render_quick_log(fit_plays, date_str, "MLB", key_prefix=f"fit_{selected_game['label']}_{n_innings}")
