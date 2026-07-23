"""
Pitching Lab — ERA-vs-FIP regression PLUS matchup-aware starter projections.

The FIP table flags positive/negative regression candidates. The projections table shows
each starter's expected IP/K/BB/outs computed against the OPPOSING LINEUP (odds-ratio
matchup), so a strikeout arm vs a whiff-prone lineup projects higher than vs a contact team.
"""

import streamlit as st
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import pandas as pd
from datetime import datetime
import pytz

import mlb_engine as E
import projections as P
import statcast_data as SC

st.title("🎯 Pitching Lab")
st.caption("ERA vs FIP regression and matchup-aware strikeout/innings projections")

eastern = pytz.timezone("US/Eastern")


def game_time_et(iso_utc):
    """ISO-UTC start -> '7:10 PM ET', or 'TBD' if missing."""
    if not iso_utc:
        return "TBD"
    try:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(eastern)
        return dt.strftime("%I:%M %p").lstrip("0") + " ET"
    except (ValueError, TypeError):
        return "TBD"


@st.cache_data(ttl=3600, show_spinner=False)
def load_statcast():
    return SC.load()  # (lookup_by_player_id, calibration_k); ({}, None) if no cache file


def _build_lineup_probs(rows, opp_starter_stat, opp_bullpen_stat, park, statcast_lookup, statcast_k):
    """For a real 9-batter lineup (build_game_lineups' own row shape), build the two per-batter
    probability-array lists the game simulation needs -- one for facing the OPPOSING starter,
    one for facing the OPPOSING bullpen -- reusing batter_pa_probs/pitcher_allowed_rates exactly
    as they're already used elsewhere on this platform for individual player props, not a new
    parallel calculation.

    NO LIVE WEATHER ADJUSTMENT (weather_hr fixed at 1.0, neutral) -- a real, stated
    simplification for this v1 wiring, not an oversight; batter_pa_probs itself supports a real
    weather multiplier, it's just not fetched and threaded through here yet.

    Returns (probs_vs_starter_list, probs_vs_bullpen_list), each exactly 9 arrays in the same
    batting-order order as `rows`, or None if either the starter's or bullpen's own rates can't
    be computed, or if ANY single batter in the lineup can't be projected -- a simulation missing
    even one real batter isn't a real 9-man lineup."""
    opp_sp_rates = P.pitcher_allowed_rates(opp_starter_stat)
    opp_pen_rates = P.pitcher_allowed_rates(opp_bullpen_stat)
    if opp_sp_rates is None or opp_pen_rates is None:
        return None
    vs_starter, vs_bullpen = [], []
    for row in rows:
        xhr = P.xhr_from_statcast(row["_pid"], statcast_lookup, statcast_k)
        probs_sp = P.batter_pa_probs(row["_stat"], park, opp_sp_rates, row["_split_stat"], xhr, weather_hr=1.0)
        probs_pen = P.batter_pa_probs(row["_stat"], park, opp_pen_rates, row["_split_stat"], xhr, weather_hr=1.0)
        if probs_sp is None or probs_pen is None:
            return None
        vs_starter.append(probs_sp)
        vs_bullpen.append(probs_pen)
    return vs_starter, vs_bullpen


@st.cache_data(ttl=600, show_spinner=False)
def load(date_str: str, fip_constant: float):
    rows, meta = E.build_slate(date_str, fip_constant)
    projections = P.build_pitcher_projection_rows(rows, meta, seed=11)
    # FIP regression table, rebuilt from the probable starters in meta.
    fip_rows = []
    for m in meta:
        for pm, team, opp, team_id in ((m["home_pm"], m["home_name"], m["away_name"], m.get("home_id")),
                                       (m["away_pm"], m["away_name"], m["home_name"], m.get("away_id"))):
            if pm.id is None or pm.era == 0:
                continue
            fip_rows.append({
                "Pitcher": pm.name, "Team": team, "Opponent": opp, "Hand": pm.hand,
                "ERA": round(pm.era, 2), "FIP": pm.fip, "Delta": round(pm.era - pm.fip, 2),
                "K/9": round(pm.k9, 1), "WHIP": round(pm.whip, 2), "HR/9": round(pm.hr9, 2), "OBA": pm.oba,
                "_game_date": m.get("game_date"), "_team_id": team_id,
            })
    return fip_rows, projections, meta


col_a, col_b = st.columns([2, 1])
with col_a:
    target_date = st.date_input("Analysis Date", datetime.now())
with col_b:
    fip_constant = st.number_input("FIP constant", value=E.FIP_CONSTANT_DEFAULT,
                                   step=0.01, help="Season-specific; ~3.1-3.2.")

date_str = target_date.strftime("%Y-%m-%d")

with st.spinner("Loading starters and opposing lineups..."):
    fip_rows, proj_rows, meta = load(date_str, fip_constant)

if not fip_rows:
    st.info("No probable starters found for this date. Pick a date with scheduled games.")
    st.stop()

df = pd.DataFrame(fip_rows)
df["Time"] = df["_game_date"].apply(game_time_et)

# === Matchup-aware projections =============================================
st.subheader("⚡ Matchup-aware starter projections")
st.caption("Expected line vs the opposing lineup. Proj K already accounts for how much that "
           "specific lineup strikes out — the same odds-ratio matchup used on the hitter side.")
if proj_rows:
    pdf = pd.DataFrame(proj_rows)
    pdf["Time"] = pdf["_game_date"].apply(game_time_et)
    sort_mode = st.radio("Sort", ["Chronological", "Projected K"], horizontal=True, key="proj_sort")
    if sort_mode == "Chronological":
        pdf = pdf.sort_values("_game_date", kind="stable", na_position="last")
    else:
        pdf = pdf.sort_values("Proj K", ascending=False, kind="stable")
    show = pdf.rename(columns={"K over%": "SO o5.5", "K fair": "SO fair"})
    cols = ["Time", "Pitcher", "Team", "Opp", "Hand", "Proj IP", "Proj K", "SO o5.5", "SO fair",
            "Proj BB", "Proj Outs", "Proj TTO", "ERA", "FIP"]
    show = show[[c for c in cols if c in show.columns]]
    st.dataframe(
        show.style.format({"SO o5.5": "{:.1%}", "Proj IP": "{:.1f}", "Proj K": "{:.1f}",
                           "Proj BB": "{:.1f}", "Proj Outs": "{:.1f}", "Proj TTO": "{:.2f}",
                           "ERA": "{:.2f}", "FIP": "{:.2f}"})
        .theme_gradient(cmap="RdYlGn", subset=["Proj K", "SO o5.5"]),
        use_container_width=True, hide_index=True, height=420)
    st.caption("**Proj TTO** = expected times through the order (Proj BF ÷ 9). Well-documented "
              "industry research (Baseball Prospectus, SABR) shows pitcher performance meaningfully "
              "degrades each additional trip through the same lineup within a game — roughly an "
              "8-12 point wOBA-against increase per trip, more for fastball-heavy pitchers, based "
              "on league-wide studies, NOT this pitcher specifically (that range varies enough by "
              "repertoire that baking one number into every projection would overclaim precision "
              "the research itself doesn't support at the individual level). A start projecting a "
              "real 3rd trip carries meaningfully more of this exposure than one that doesn't — "
              "read Proj TTO as that context, not a separate line to bet.")
else:
    st.write("No projectable starters (need 3+ starts of data).")

# === FIP regression ========================================================
st.divider()
st.subheader("📉 ERA vs FIP regression")
buys = df[df["Delta"] >= 0.50].sort_values("Delta", ascending=False)
fades = df[df["Delta"] <= -0.50].sort_values("Delta")
m1, m2, m3 = st.columns(3)
m1.metric("Probable starters", len(df))
m2.metric("Positive-regression (buy)", len(buys))
m3.metric("Negative-regression (fade)", len(fades))

fip_cols = ["Time", "Pitcher", "Team", "Opponent", "Hand", "ERA", "FIP", "Delta",
            "K/9", "WHIP", "HR/9", "OBA"]
styled = (
    df.sort_values("Delta", ascending=False)[fip_cols]
    .style.format({"ERA": "{:.2f}", "FIP": "{:.2f}", "Delta": "{:+.2f}",
                   "K/9": "{:.1f}", "WHIP": "{:.2f}", "HR/9": "{:.2f}", "OBA": "{:.3f}"})
    .theme_gradient(cmap="RdYlGn", subset=["Delta", "K/9"])
    .theme_gradient(cmap="RdYlGn_r", subset=["ERA", "FIP", "WHIP", "HR/9"])
)
st.dataframe(styled, use_container_width=True, hide_index=True)

# === Bullpen fatigue =========================================================
st.divider()
st.subheader("💪 Bullpen fatigue")
st.caption("Which relievers on each side have real recent workload — pitched on 3+ straight "
          "days is the clearest \"likely unavailable tonight\" signal. Scoped to one game at a "
          "time, not the whole slate — each team's read costs several real API calls (a "
          "schedule window plus one boxscore per recent game), so this narrows first rather "
          "than fetching bullpen data for every team on a busy night up front.")


@st.cache_data(ttl=900, show_spinner=False)
def load_bullpen_fatigue(team_id, date_str_inner, fip_constant_inner):
    if not team_id:
        return []
    fatigue = E.get_team_bullpen_fatigue(team_id, date_str_inner)
    return E.enrich_bullpen_fatigue_with_metrics(fatigue, fip_constant_inner)


game_options = {m["label"]: m for m in meta if m.get("home_id") and m.get("away_id")}
if game_options:
    game_pick = st.selectbox("Game", sorted(game_options.keys()))
    picked = game_options[game_pick]

    with st.spinner("Checking recent bullpen usage and quality for both teams..."):
        home_fatigue = load_bullpen_fatigue(picked["home_id"], date_str, fip_constant)
        away_fatigue = load_bullpen_fatigue(picked["away_id"], date_str, fip_constant)

    bc1, bc2 = st.columns(2)
    for col, label, fatigue in ((bc1, picked["home_name"], home_fatigue),
                                (bc2, picked["away_name"], away_fatigue)):
        with col:
            st.markdown(f"**{label}**")
            if not fatigue:
                st.caption("No pitchers with recent appearances found in the last 5 days.")
                continue
            bdf = pd.DataFrame(fatigue)[["name", "days_since_last_appearance", "consecutive_days",
                                        "total_outs_in_window", "ERA", "FIP", "K9", "tag"]]
            bdf = bdf.rename(columns={"name": "Pitcher", "days_since_last_appearance": "Days Since",
                                      "consecutive_days": "Streak", "total_outs_in_window": "Outs (window)",
                                      "K9": "K/9"})
            st.dataframe(
                bdf.style.format({"ERA": "{:.2f}", "FIP": "{:.2f}", "K/9": "{:.1f}"}, na_rep="—")
                .theme_gradient(cmap="RdYlGn", subset=["K/9"])
                .theme_gradient(cmap="RdYlGn_r", subset=["ERA", "FIP"]),
                hide_index=True, use_container_width=True)
    st.caption("Every pitcher who recorded an out in either team's last 5 games, not just "
              "confirmed relievers — cross-reference against the probable starter above to "
              "read the rest as bullpen arms. \"Outs (window)\" is total workload across the "
              "whole 5-day window, not per game. ERA/FIP/K9 are each pitcher's own SEASON line — "
              "\"available AND good\" vs. \"available but mediocre\" in one table, not two "
              "separate lookups.")

    # === Starter rest, same selected game, no second picker ------------------
    st.markdown("**😴 Starter rest**")
    st.caption("Short rest (4 days or fewer) is genuinely unusual and the well-established "
              "effectiveness concern; extra rest has more mixed evidence, shown as context, "
              "not asserted as a clean positive.")

    @st.cache_data(ttl=1800, show_spinner=False)
    def load_starter_rest(pitcher_id, team_id, date_str_inner):
        if not pitcher_id or not team_id:
            return {"days_rest": None, "last_start_date": None, "rest_tag": "Unknown"}
        return E.get_starter_rest_info(pitcher_id, team_id, date_str_inner)

    rc1, rc2 = st.columns(2)
    for col, label, sp, team_id in ((rc1, picked["home_name"], picked["home_pm"], picked["home_id"]),
                                    (rc2, picked["away_name"], picked["away_pm"], picked["away_id"])):
        with col:
            rest = load_starter_rest(sp.id, team_id, date_str)
            st.markdown(f"**{label}** — {sp.name}")
            st.caption(rest["rest_tag"] if rest["last_start_date"] is None else
                      f"{rest['rest_tag']} · last started {rest['last_start_date']}")

    # === Starter check: did the probable starter actually take the mound? ---------------------
    # Added directly on request, after a real, reported pattern: a probable starter posted
    # earlier in the day doesn't always match who actually starts (a late scratch, or a bullpen
    # game with no true starter at all) -- noticed mid-game, not before, since nothing in MLB's
    # own schedule data marks a probable pitcher "confirmed" the way a posted batting order marks
    # a lineup confirmed. HONEST SCOPE: this can only catch a mismatch ONCE the game has actually
    # started and posted real pitching stats -- it cannot warn before first pitch, unlike the
    # lineup Projected/Confirmed badge elsewhere on this platform. On-demand (one live boxscore
    # fetch per side), not automatic -- most useful once a game is actually underway.
    st.markdown("**🔁 Starter check**")
    st.caption("Confirms whether the probable starter shown above is the same real person who "
              "actually has the ball — only meaningful once the game has started; before that, "
              "this correctly reports \"not started yet,\" not a guess either way.")
    if picked.get("gamePk"):
        sc1, sc2 = st.columns(2)
        for col, label, sp, side in ((sc1, picked["home_name"], picked["home_pm"], "home"),
                                     (sc2, picked["away_name"], picked["away_pm"], "away")):
            with col:
                st.markdown(f"**{label}** — probable: {sp.name}")
                if st.button("Check actual starter", key=f"starter_check_{side}_{picked['gamePk']}"):
                    with st.spinner("Checking tonight's live boxscore..."):
                        actual = E.get_actual_starter(picked["gamePk"], side)
                    mismatch = E.starter_mismatch(sp.id, actual)
                    if mismatch is None:
                        st.caption("⏳ Not started yet (or no pitching stats posted) — nothing "
                                  "to confirm against yet.")
                    elif mismatch:
                        st.error(f"⚠️ Mismatch — **{actual['name']}** actually has the ball, not "
                                "the probable starter shown above.")
                    else:
                        st.success(f"✅ Confirmed — {actual['name']} matches the probable starter.")
    else:
        st.caption("No game id available for this matchup — starter check isn't available here.")

    # === EXPERIMENTAL: full Monte Carlo game simulation (Option A, Method 1) -------------------
    # Added directly on request, after building and testing the underlying simulation engine
    # (projections.simulate_game_win_probability) separately with synthetic data. This is the
    # REAL DATA WIRING step: fetches both teams' actual 9-man lineups (mlb_engine.
    # build_game_lineups) and runs them through that engine. UNBACKTESTED -- same honest
    # limitation as the lighter Pythagorean/Log5 estimate on Game Watch, doubled: this is a
    # bigger, more complex model with more places a real calibration error could hide, and
    # there's been zero opportunity to check it against actual outcomes from this sandbox.
    #
    # REAL, STATED SIMPLIFICATIONS IN THE WIRING ITSELF (on top of the engine's own, see
    # projections.py's module comment above simulate_one_game): no live weather adjustment
    # (weather_hr fixed at 1.0 neutral -- batter_pa_probs supports a real weather multiplier,
    # just not wired in here yet); a starter's own rest/matchup-lineup adjustments used
    # elsewhere on this platform (rest_adjustment_multipliers, opponent-lineup K/BB odds-ratio)
    # are NOT applied here -- each starter/bullpen is projected from his own season rates alone.
    #
    # REAL COST, substantial: up to 18 hitter fetches, 2 starter fetches, 1 boxscore fetch, 2
    # bullpen-aggregate fetches, PLUS the simulation itself (n_trials full 9-inning games) --
    # the most expensive single feature on this platform. On-demand only.
    st.markdown("**🎲 EXPERIMENTAL — full Monte Carlo game simulation**")
    st.caption("Simulates the actual game, inning by inning, using both teams' real lineups — "
              "the full version of a win-probability model, not the lighter Pythagorean/Log5 "
              "shortcut on Game Watch. Real, substantial cost (roughly 20+ fetches plus the "
              "simulation itself) — nothing runs until you press the button below.")
    n_trials = st.slider("Number of simulated games", min_value=200, max_value=3000, value=800,
                         step=200,
                         help="More trials narrow the estimate but take longer to run in this "
                             "plain-Python (not vectorized) engine — see projections.py's own "
                             "docstring for the exact tradeoff.")
    if st.button("🎲 Run full game simulation", key=f"sim_run_{picked.get('gamePk')}"):
        with st.spinner("Fetching both real lineups..."):
            lineups = E.build_game_lineups(
                picked["gamePk"], picked["home_id"], picked["away_id"],
                picked["home_pm"].id, picked["away_pm"].id, picked.get("venue_id"), fip_constant)
        if lineups is None:
            st.warning("Couldn't assemble a full real 9-batter lineup for one or both teams "
                      "(lineup not posted yet, or thin data) — try again closer to first pitch.")
        else:
            with st.spinner(f"Building matchup-aware probabilities and running {n_trials} simulated games..."):
                statcast_lookup, statcast_k = load_statcast()
                park = P.PARK_FACTORS.get(picked.get("venue_id"), P.NEUTRAL_PARK)
                home_pm, away_pm = lineups["home_pm"], lineups["away_pm"]

                away_bullpen_stat = E.get_bullpen_aggregate_stat(picked["away_id"], exclude_pid=away_pm.id)
                home_bullpen_stat = E.get_bullpen_aggregate_stat(picked["home_id"], exclude_pid=home_pm.id)
                away_starter_proj = P.project_pitcher(away_pm.stat)
                home_starter_proj = P.project_pitcher(home_pm.stat)

                sim_result = None
                if not (away_bullpen_stat and home_bullpen_stat and away_starter_proj and home_starter_proj):
                    st.warning("One or both starters/bullpens don't have enough real season data "
                              "to project (a very early-season sample, or a true bullpen-game "
                              "opener) — the simulation needs a real projection for both sides.")
                else:
                    home_probs = _build_lineup_probs(lineups["home_rows"], away_pm.stat, away_bullpen_stat,
                                                     park, statcast_lookup, statcast_k)
                    away_probs = _build_lineup_probs(lineups["away_rows"], home_pm.stat, home_bullpen_stat,
                                                     park, statcast_lookup, statcast_k)
                    if home_probs is None or away_probs is None:
                        st.warning("Couldn't build real matchup probabilities for every batter in "
                                  "one or both lineups (thin individual sample) — the simulation "
                                  "needs a real projection for all 18 real batters.")
                    else:
                        sim_result = P.simulate_game_win_probability(
                            away_probs[0], away_probs[1], home_starter_proj["exp_outs"],
                            home_probs[0], home_probs[1], away_starter_proj["exp_outs"],
                            n_trials=n_trials)

            if sim_result:
                mc1, mc2, mc3 = st.columns(3)
                mc1.metric(f"{picked['away_name']} (away)", f"{sim_result['away_win_prob']:.0%}")
                mc2.metric(f"{picked['home_name']} (home)", f"{sim_result['home_win_prob']:.0%}")
                mc3.metric("Tied after 9 (extras not simulated)", f"{sim_result['tie_prob']:.0%}")
                st.caption(f"Average simulated score: {picked['away_name']} "
                          f"{sim_result['avg_away_runs']:.1f} — {picked['home_name']} "
                          f"{sim_result['avg_home_runs']:.1f}, across {sim_result['n_trials']} trials.")
                st.caption("⚠️ **Not backtested.** A real inning-by-inning simulation using real "
                          "lineups, but deterministic base-running (see projections.py's own "
                          "module comment for the exact list of simplifications) tends to "
                          "inflate scoring somewhat above real MLB rates — trust the direction "
                          "of this result more than its exact number until it's been checked "
                          "against real outcomes.")

    # === Mid-season catcher change: does this starter's own BB/K rate actually shift? ---------
    st.markdown("**🧤 Catcher change check**")
    st.caption("A pitcher's season-long BB/K rates already happened WITH his real catcher(s) "
              "behind him — a good framer's contribution is usually already baked in, "
              "indistinguishable from \"the pitcher got better.\" The place a season average "
              "genuinely misleads is a MID-SEASON catcher change specifically — the full-season "
              "rate is a blend of before and after, quietly wrong for projecting him going "
              "forward. This checks for a real, clean transition (not routine catcher rotation) "
              "and shows this pitcher's own actual BB%/K% split before vs. after, using his real "
              "results, not a projected adjustment. Costs a real fetch per start scanned, so it's "
              "on-demand, not automatic.")
    cc1, cc2 = st.columns(2)
    for col, label, sp, team_id in ((cc1, picked["home_name"], picked["home_pm"], picked["home_id"]),
                                    (cc2, picked["away_name"], picked["away_pm"], picked["away_id"])):
        with col:
            st.markdown(f"**{label}** — {sp.name}")
            if st.button("Check for a catcher change", key=f"catcher_change_{sp.id}"):
                with st.spinner(f"Scanning {sp.name}'s starts for a catcher change..."):
                    season = int(date_str[:4])
                    cc = E.get_pitcher_catcher_change_split(sp.id, team_id, season, before_date=date_str)
                if not cc:
                    st.caption("No clean mid-season catcher change detected — either the same "
                              "catcher has caught him all year, usage has rotated without one "
                              "clear transition, or there isn't a big enough sample on both "
                              "sides yet.")
                else:
                    st.markdown(f"**{cc['old_catcher']['name']}** → **{cc['new_catcher']['name']}**, "
                               f"{cc['change_date']}")
                    bc1, bc2 = st.columns(2)
                    with bc1:
                        st.metric(f"BB% ({cc['old_catcher']['name']}, {cc['before']['starts']} starts)",
                                 f"{cc['before']['bb_pct']:.1%}")
                        st.metric(f"K% ({cc['old_catcher']['name']}, {cc['before']['starts']} starts)",
                                 f"{cc['before']['k_pct']:.1%}")
                    with bc2:
                        bb_delta = cc['after']['bb_pct'] - cc['before']['bb_pct']
                        k_delta = cc['after']['k_pct'] - cc['before']['k_pct']
                        st.metric(f"BB% ({cc['new_catcher']['name']}, {cc['after']['starts']} starts)",
                                 f"{cc['after']['bb_pct']:.1%}", delta=f"{bb_delta:+.1%}",
                                 delta_color="inverse")
                        st.metric(f"K% ({cc['new_catcher']['name']}, {cc['after']['starts']} starts)",
                                 f"{cc['after']['k_pct']:.1%}", delta=f"{k_delta:+.1%}")
                    st.caption("Real, summed outcomes across each block of starts, not a "
                              "projected adjustment. A small sample on either side — read with "
                              "the same caution any small-sample split deserves.")
else:
    st.caption("No games with both team ids available for this date.")

# === Hitter workload moved ====================================================
# Moved to Dinger Engine directly on request, after a platform audit: this is a fatigue/rest
# concern about HITTERS, not pitchers -- it always said so itself ("the hitter-side sibling" of
# pitcher rest and bullpen fatigue above), it just landed on this pitcher-focused page because it
# followed this page's own per-game pattern when it was first built, not because it's
# conceptually a pitching topic. Dinger Engine is this platform's actual hitter-focused home.
st.divider()
st.page_link("views/8_#L01f4a3_Dinger_Engine.py",
             label="🏃 Looking for Hitter Workload? It's moved to Dinger Engine →", icon="💣")

# === Discussion hooks ======================================================
st.divider()
st.subheader("🤳 Discussion hooks (auto-generated)")
st.caption("Talking points where the underlying metrics diverge from the surface results.")
if buys.empty:
    st.write("No strong positive-regression candidates on this slate.")
for _, r in buys.head(5).iterrows():
    st.code(
        f"{r['Pitcher']} ({r['Team']}) carries a {r['ERA']:.2f} ERA but a {r['FIP']:.2f} FIP "
        f"— a {r['Delta']:+.2f} gap. The peripherals (K/9 {r['K/9']:.1f}, WHIP {r['WHIP']:.2f}) "
        f"suggest he's pitching better than the line shows. #MLB",
        language=None,
    )

st.caption("Trends, not guarantees. FIP normalizes for defense/luck; projections assume the "
           "starter goes his typical length and the opposing lineup is roughly as posted.")
