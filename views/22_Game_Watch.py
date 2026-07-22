"""
Game Watch — tonight's whole slate, six real signals per game plus injury context, honestly
combined.

WHAT THIS IS, PRECISELY: for each game, compares starter quality (FIP), bullpen freshness,
bullpen quality (aggregate ERA), overall team form (last-15-games record and run differential),
each team's form specifically in tonight's role (home vs road), and each team's form specifically
in tonight's day/night slot -- then reports how many of those signals favor each team. Also shows
each team's real injury/roster-restriction report as CONTEXT, deliberately not tallied (see the
per-game injury section's own note for why). That's it. NOT a win probability. NOT a betting
recommendation. NOT a prediction of the final score. A transparent count of how many
independently-computed factors happen to point the same way -- see projections.matchup_signal_
tally's own docstring for why a count, not a fabricated weighted score: there's no real
backtested validation yet that would justify weighting one signal over another, so an honest
count is the most this data can currently support.

WHY THIS EXISTS: a real, repeated pattern from trader discussion -- moneyline decisions were
being made by manually comparing starter quality, bullpen state, and recent team form every
night, entirely outside this platform ("winning the last 15 games and the run differential is
big... they have a less taxed bullpen also" -- the exact same three things this page checks,
in the exact same real trader's own words, confirmed as a standing part of their process on two
separate, independent days, not a one-off comment). This is a first step at that, deliberately
scoped to signals that were already built or nearly free to add, not a full game-simulation
model -- that's a genuinely bigger, different undertaking, worth its own separate build if this
proves useful. Bullpen Watch already covers freshness alone, cheaply, for anyone who just wants
that quick read; this page is the fuller (and more expensive) picture for anyone who wants more.

NOT EVERYTHING FROM THAT SAME REAL PROCESS IS HERE YET -- see the disclaimer at the bottom of
the page for the three pieces deliberately left out (pitcher-side xERA, team-level platoon
performance, head-to-head starter history) and why each is a real, separate undertaking rather
than a quick addition, not an oversight.

REAL COST, OPT-IN BY DESIGN: the starter-FIP comparison is FREE (already inside the same
build_pitching_slate fetch Bullpen Watch also uses). Every other signal is a genuinely NEW real
fetch per team on top -- bullpen freshness and quality each cost what they already cost
elsewhere on this platform; each team-form variant (overall, road/home, day/night) is its own
schedule-range fetch; the injury report is one more roster fetch per team. Nothing beyond the
lightweight starter list loads until you press the button below -- a real, larger number of API
calls than earlier versions of this page, worth being upfront about.
"""

import streamlit as st
from datetime import datetime

import mlb_engine as E
import projections as P
import sports

game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER

# Real, stated judgment calls, not buried magic numbers -- see lower_is_better_edge's own
# docstring for why these aren't just left at the exact-tie default. FIP epsilon: roughly a
# fifth of an earned run per 9, a commonly-used "materially different" gap for a single season's
# FIP. Bullpen ERA epsilon is wider (a bullpen's aggregate line mixes several arms of very
# different quality across a whole season, genuinely noisier than one starter's own FIP).
FIP_EPSILON = 0.20
BULLPEN_ERA_EPSILON = 0.30
# Run differential is a per-game AVERAGE (not a total), so this needs to be a small number --
# roughly "three quarters of a run per game, sustained over the last 15 games" as the real,
# stated floor for "this is a meaningfully hotter/colder team," not noise from a couple of
# lopsided games inside an otherwise ordinary stretch.
RUN_DIFF_EPSILON = 0.75
GAMES_BACK = 15   # matches the real number from trader discussion directly ("last 15 games"),
                  # not a round number picked independently

st.title("📡 Game Watch")
st.caption("Six real signals per game, plus injury context — starter quality, bullpen freshness, "
          "bullpen quality, overall team form, tonight's-role form, tonight's-slot form — "
          "combined into an honest count, not a predicted winner. See the disclaimer at the "
          "bottom before reading too much into any single game.")
lc1, lc2 = st.columns(2)
with lc1:
    st.page_link("views/1_#L01f3af_Pitching_Lab.py",
                 label="Full pitcher-by-pitcher detail → Pitching Lab", icon="🎯")
with lc2:
    st.page_link("views/21_Bullpen_Watch.py",
                 label="Just want the quick, cheap freshness read? → Bullpen Watch", icon="🛡️")

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

if not st.button(f"🔄 Load matchup signals for {len(games)} game(s)",
                 help="Real cost, bigger than earlier versions of this page: bullpen freshness, "
                     "bullpen quality, three separate team-form variants (overall, road/home, "
                     "day/night), and an injury report each require their own real fetch per "
                     "team, for both teams in every game below (starter FIP is free, already "
                     "loaded above). Cached for 10-15 minutes."):
    st.info("Press the button above to load tonight's matchup signals. Nothing beyond the "
           "starter list above is fetched until you do.")
    st.stop()


@st.cache_data(ttl=600, show_spinner=False)
def load_bullpen_freshness(team_id, exclude_pid, date_str_inner):
    if not team_id:
        return None
    fatigue = E.get_team_bullpen_fatigue(team_id, date_str_inner)
    return P.bullpen_fatigued_fraction(fatigue, exclude_pid=exclude_pid)


@st.cache_data(ttl=900, show_spinner=False)
def load_bullpen_quality(team_id, exclude_pid):
    if not team_id:
        return None
    agg = E.get_bullpen_aggregate_stat(team_id, exclude_pid=exclude_pid)
    return agg.get("era") if agg else None


@st.cache_data(ttl=900, show_spinner=False)
def load_team_form(team_id, date_str_inner):
    if not team_id:
        return None
    return E.get_team_recent_form(team_id, date_str_inner, games_back=GAMES_BACK)


@st.cache_data(ttl=900, show_spinner=False)
def load_team_form_filtered(team_id, date_str_inner, venue=None, time_of_day=None):
    if not team_id:
        return None
    return E.get_team_recent_form(team_id, date_str_inner, games_back=GAMES_BACK,
                                  venue=venue, time_of_day=time_of_day)


@st.cache_data(ttl=900, show_spinner=False)
def load_injuries(team_id):
    if not team_id:
        return []
    return E.get_team_injuries(team_id)


def _diff(edge_val):
    """None-safe extraction of avg_run_diff from a get_team_recent_form result (or None)."""
    return edge_val["avg_run_diff"] if edge_val else None


progress = st.progress(0.0, text="Checking starter quality, bullpen state, team form, and injuries...")
for i, g in enumerate(games):
    away_row, home_row = g["away"], g["home"]
    away_fresh = load_bullpen_freshness(away_row["_team_id"], away_row["_pid"], date_str)
    home_fresh = load_bullpen_freshness(home_row["_team_id"], home_row["_pid"], date_str)
    away_bp_era = load_bullpen_quality(away_row["_team_id"], away_row["_pid"])
    home_bp_era = load_bullpen_quality(home_row["_team_id"], home_row["_pid"])
    away_form = load_team_form(away_row["_team_id"], date_str)
    home_form = load_team_form(home_row["_team_id"], date_str)

    # Home/road form: each team's own form in the ROLE it's actually playing tonight -- the away
    # team's road record, the home team's home record. More targeted than the generic L15 form
    # above, and a genuinely different (complementary, not redundant) real signal.
    away_road_form = load_team_form_filtered(away_row["_team_id"], date_str, venue="away")
    home_home_form = load_team_form_filtered(home_row["_team_id"], date_str, venue="home")

    # Day/night form: both teams' form specifically in TONIGHT's own time-of-day bucket. Only
    # computed when tonight's own start time is actually known -- an unknown start time means
    # there's no real "tonight's bucket" to compare either team against, an honest None rather
    # than guessing.
    tonight_hour_dt = game_dt(g["_game_date"])
    tonight_tod = None
    if tonight_hour_dt is not None:
        tonight_tod = "day" if tonight_hour_dt.hour < 17 else "night"
    away_tod_form = (load_team_form_filtered(away_row["_team_id"], date_str, time_of_day=tonight_tod)
                     if tonight_tod else None)
    home_tod_form = (load_team_form_filtered(home_row["_team_id"], date_str, time_of_day=tonight_tod)
                     if tonight_tod else None)

    away_injuries = load_injuries(away_row["_team_id"])
    home_injuries = load_injuries(home_row["_team_id"])

    starter_edge = P.lower_is_better_edge(away_row.get("FIP"), home_row.get("FIP"), epsilon=FIP_EPSILON)
    freshness_edge = P.bullpen_freshness_edge(away_fresh, home_fresh)
    quality_edge = P.lower_is_better_edge(away_bp_era, home_bp_era, epsilon=BULLPEN_ERA_EPSILON)
    form_edge = P.higher_is_better_edge(_diff(away_form), _diff(home_form), epsilon=RUN_DIFF_EPSILON)
    home_road_edge = P.higher_is_better_edge(_diff(away_road_form), _diff(home_home_form),
                                             epsilon=RUN_DIFF_EPSILON)
    tod_edge = P.higher_is_better_edge(_diff(away_tod_form), _diff(home_tod_form),
                                       epsilon=RUN_DIFF_EPSILON)

    g["_tally"] = P.matchup_signal_tally([starter_edge, freshness_edge, quality_edge, form_edge,
                                          home_road_edge, tod_edge])
    g["_signals"] = {
        "Starter FIP": (away_row.get("FIP"), home_row.get("FIP"), starter_edge),
        "Bullpen freshness": (away_fresh, home_fresh, freshness_edge),
        "Bullpen ERA": (away_bp_era, home_bp_era, quality_edge),
        "Team form (L15)": (away_form, home_form, form_edge),
        "Form in tonight's role (road/home)": (away_road_form, home_home_form, home_road_edge),
        "Form in tonight's day/night slot": (away_tod_form, home_tod_form, tod_edge),
    }
    g["_tonight_tod"] = tonight_tod   # kept separately for display context, not baked into the
                                      # signal's own key name (a per-game-varying dict key would
                                      # break the fixed _SIGNAL_KIND formatting lookup below)
    g["_injuries"] = {"away": away_injuries, "home": home_injuries}
    progress.progress((i + 1) / len(games), text=f"Checked {g['label']} ({i + 1}/{len(games)})")
progress.empty()


def _fmt(value, kind):
    if value is None:
        return "—"
    if kind == "pct":
        return f"{value:.0%}"
    if kind == "form":
        return f"{value['wins']}-{value['losses']} ({value['avg_run_diff']:+.1f})"
    return f"{value:.2f}"


VERDICT_TEXT = {
    "insufficient_data": "Not enough data to compare — nothing to show here.",
    "even": "Signals split or too close to call — no real edge either way.",
}

_SIGNAL_KIND = {"Bullpen freshness": "pct", "Team form (L15)": "form",
                "Form in tonight's role (road/home)": "form", "Form in tonight's day/night slot": "form"}

for g in games:
    dt = game_dt(g["_game_date"])
    time_str = dt.strftime("%-I:%M %p ET") if dt else "TBD"
    away_row, home_row = g["away"], g["home"]
    tally = g["_tally"]
    with st.container(border=True):
        st.markdown(f"### {g['label']} — {time_str}")
        if g["_tonight_tod"] is None:
            st.caption("Tonight's own start time is unknown, so the day/night form signal above "
                      "has no real bucket to compare — shown as \"no data,\" not guessed.")
        else:
            st.caption(f"Tonight is a {g['_tonight_tod']} game — the day/night form row above "
                      f"compares both teams' own {g['_tonight_tod']}-game form specifically.")

        rows = []
        for signal_name, (away_val, home_val, edge) in g["_signals"].items():
            kind = _SIGNAL_KIND.get(signal_name, "num")
            lean = {"home": f"→ {home_row['Team']}", "away": f"→ {away_row['Team']}",
                   "even": "even", None: "no data"}[edge]
            rows.append((signal_name, _fmt(away_val, kind), _fmt(home_val, kind), lean))

        h1, h2, h3, h4 = st.columns([2, 1, 1, 2])
        h1.caption("Signal")
        h2.caption(f"{away_row['Team']} (away)")
        h3.caption(f"{home_row['Team']} (home)")
        h4.caption("Edge")
        for name, av, hv, lean in rows:
            c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
            c1.write(name)
            c2.write(av)
            c3.write(hv)
            c4.write(lean)

        if tally["verdict"] in VERDICT_TEXT:
            st.markdown(f"**{VERDICT_TEXT[tally['verdict']]}**")
        else:
            winner = home_row["Team"] if tally["verdict"] == "home" else away_row["Team"]
            st.markdown(f"**{tally[tally['verdict']]} of {tally['available']} available signals "
                       f"favor {winner}.**")

        # Injury report — CONTEXT, deliberately NOT one of the tallied signals above. A raw
        # injured-player COUNT would be a fabricated precision this page has avoided everywhere
        # else: a team with 5 injured bench players and one with 1 injured star aren't
        # comparable by count alone, and turning "who's hurt" into a fake number would be
        # exactly the kind of overclaiming this page's own disclaimer argues against. Shown as a
        # real, raw list for your own judgment instead.
        inj = g["_injuries"]
        if inj["away"] or inj["home"]:
            with st.expander("🩺 Injury/roster-restriction report (context, not a tallied signal)"):
                ic1, ic2 = st.columns(2)
                for col, team_name, players in ((ic1, away_row["Team"], inj["away"]),
                                                (ic2, home_row["Team"], inj["home"])):
                    with col:
                        st.markdown(f"**{team_name}**")
                        if not players:
                            st.caption("No reported restrictions.")
                        for p in players:
                            st.caption(f"{p['player']} ({p['position']}) — {p['status']}")

st.divider()
st.caption("⚠️ **Read this before reading too much into any game above.** This is six "
          "individually honest comparisons counted up, not a probability and not a validated "
          "model — there's no historical backtest yet showing these six signals actually "
          "predict outcomes, or how much weight each deserves relative to the others. A read "
          "like 4-of-6 is a starting point for your own judgment, not a call to act on by "
          "itself. \"Even\" and \"not enough data\" are both real, honest outcomes — most games "
          "likely won't show a clean sweep, and that itself is useful information, not a "
          "failure of the page. Uses the same \"real gap\" thresholds stated at the top of this "
          f"page (±{FIP_EPSILON:.2f} FIP, ±{BULLPEN_ERA_EPSILON:.2f} bullpen ERA, "
          f"±{RUN_DIFF_EPSILON:.2f} avg run diff — applied to every run-differential-based "
          "signal: overall form, road/home form, and day/night form alike) so a razor-thin "
          "numeric difference isn't shown as a real edge. The injury report is context only, "
          "never tallied — see its own note above for why.\n\n"
          "**Not covered here, and each a real, separate undertaking rather than a quick "
          "addition:** pitcher-side expected ERA (xERA) — this platform has expected-stats data "
          "for BATTERS (xwOBA) but nothing equivalent for pitchers yet, which would need a new "
          "external data source, not just a new aggregation of what's already here. Team-level "
          "platoon performance (vs LHP/RHP) — individual hitter splits already exist and feed "
          "the player-prop models, but a fair TEAM-level rollup needs real playing-time "
          "weighting decisions, not a naive average. Head-to-head starter-vs-opponent history — "
          "deliberately left out of the tally: most specific pitcher/team pairs have only a "
          "handful of career meetings, and turning that into a directional signal would be "
          "exactly the small-sample overclaiming this page exists to avoid.")
