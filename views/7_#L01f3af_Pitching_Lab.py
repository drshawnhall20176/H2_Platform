"""
Pitching Lab — ERA-vs-FIP regression PLUS matchup-aware starter projections.

The FIP table flags positive/negative regression candidates. The projections table shows
each starter's expected IP/K/BB/outs computed against the OPPOSING LINEUP (odds-ratio
matchup), so a strikeout arm vs a whiff-prone lineup projects higher than vs a contact team.
"""

import streamlit as st
import components as C
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import pandas as pd
from datetime import datetime
import pytz

import mlb_engine as E
import odds_api as O
import projections as P
import statcast_data as SC
import weather as WX

try:
    from streamlit_autorefresh import st_autorefresh
    _HAS_AUTOREFRESH = True
except ImportError:
    # Real, stated graceful degradation, same posture as Statcast being optional elsewhere on
    # this platform: the manual "refresh" button for live pitch count must keep working even if
    # this small, real third-party component (github.com/kmcgrady/streamlit-autorefresh) isn't
    # installed in a given deploy -- only the auto-refresh checkbox itself is hidden, not the
    # whole feature.
    _HAS_AUTOREFRESH = False

C.base_css()
C.page_header("🎯", "Pitching Lab",
             "ERA vs FIP regression and matchup-aware strikeout/innings projections")

eastern = pytz.timezone("US/Eastern")

CONSISTENCY_LOOKBACK_STARTS = 8   # a real, stated judgment call for the Pitcher Consistency
                                 # section below -- roughly a starter's last ~6 weeks of starts
                                 # (5-day rotation), long enough to be a real sample, short
                                 # enough to still reflect his current form. Not empirically
                                 # tuned against this platform's own data.


def game_time_et(iso_utc):
    """ISO-UTC start -> '7:10 PM ET', or 'TBD' if missing."""
    if not iso_utc:
        return "TBD"
    try:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(eastern)
        return dt.strftime("%I:%M %p").lstrip("0") + " ET"
    except (ValueError, TypeError):
        return "TBD"


# load_statcast (a local @st.cache_data wrapper around SC.load()) consolidated into
# statcast_data.load_cached — this exact wrapper used to be independently redefined in 6 places
# platform-wide, each its own separate, unshared cache entry despite doing identical real work.
# See that function's own docstring for the full real, confirmed finding.


def _build_lineup_probs(rows, opp_starter_stat, opp_bullpen_stat, park, statcast_lookup, statcast_k,
                        weather_hr=1.0):
    """For a real 9-batter lineup (build_game_lineups' own row shape), build the two per-batter
    probability-array lists the game simulation needs -- one for facing the OPPOSING starter,
    one for facing the OPPOSING bullpen -- reusing batter_pa_probs/pitcher_allowed_rates exactly
    as they're already used elsewhere on this platform for individual player props, not a new
    parallel calculation.

    weather_hr: a real HR-rate multiplier from weather.get_game_weather (the SAME function
    Dinger Engine's own game-by-game weather read already uses), added directly on request after
    this was shipped as a stated v1 simplification (fixed at 1.0, neutral). Defaults to 1.0 for
    any caller that doesn't have a real weather read yet -- an indoor/dome game or a missing
    weather fetch is honestly neutral, not guessed in either direction.

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
        probs_sp = P.batter_pa_probs(row["_stat"], park, opp_sp_rates, row["_split_stat"], xhr, weather_hr=weather_hr)
        probs_pen = P.batter_pa_probs(row["_stat"], park, opp_pen_rates, row["_split_stat"], xhr, weather_hr=weather_hr)
        if probs_sp is None or probs_pen is None:
            return None
        vs_starter.append(probs_sp)
        vs_bullpen.append(probs_pen)
    return vs_starter, vs_bullpen


def _build_lineup_probs_vs_one_pitcher(rows, opp_stat, park, statcast_lookup, statcast_k, weather_hr=1.0):
    """Same real logic as _build_lineup_probs above, but for ONE specific opposing pitcher
    (the closer) rather than a starter+bullpen pair -- avoids the wasted double computation
    _build_lineup_probs would do if called with the same stat dict twice for both its starter
    and bullpen arguments. Returns a list of 9 probability arrays, or None if the pitcher's own
    rates or any single batter's own projection can't be computed."""
    opp_rates = P.pitcher_allowed_rates(opp_stat)
    if opp_rates is None:
        return None
    out = []
    for row in rows:
        xhr = P.xhr_from_statcast(row["_pid"], statcast_lookup, statcast_k)
        probs = P.batter_pa_probs(row["_stat"], park, opp_rates, row["_split_stat"], xhr, weather_hr=weather_hr)
        if probs is None:
            return None
        out.append(probs)
    return out


@st.cache_data(ttl=600, show_spinner=False)
def load(date_str: str, fip_constant: float, venue_split=None, time_split=None):
    import best_bets_data as BBD
    rows, meta = E.build_slate(date_str, fip_constant)
    # Real, confirmed fix for a structural gap: this page never fetched real sportsbook lines at
    # all, even after Best Bets/Graded Picks/Command Center/Model Dashboard/Retrospective were
    # already fixed to use them. Every "K line"/"Proj K"/"K Over%" shown on this page was ALWAYS
    # measured against this platform's own DEFAULT_LINES/BEST_BET_REF placeholders -- including
    # after the K-line column was made visible earlier this session, which exposed whatever
    # value was there without verifying that value was ever real on THIS specific page. Calls
    # the SAME shared fetch_mlb_real_lines function build_mlb_board itself uses (see that
    # function's own docstring) rather than reimplementing the fetch a second time.
    api_key = BBD.get_odds_api_key()
    preferred_book = st.session_state.get("_preferred_book_mlb", O.DEFAULT_BOOK)
    real_lines, real_offers, _books = BBD.fetch_mlb_real_lines(date_str, api_key, preferred_book)
    # Apply pitcher split stats when a split is selected -- same minimum-sample gate (5 starts)
    # as Best Bets. Lets Deezy's "check Drohan's home day splits" workflow happen directly here.
    season = int(date_str[:4])
    split_label_base = None
    if venue_split or time_split:
        parts = [p for p in [venue_split, time_split] if p]
        split_label_base = "/".join(parts)
        for m in meta:
            for pm_attr in ("home_pm", "away_pm"):
                pm = m.get(pm_attr)
                if pm is None or pm.id is None or not pm.stat:
                    continue
                pitcher_team_id = m.get("home_id") if pm_attr == "home_pm" else m.get("away_id")
                split_stat, n = E.get_pitcher_split_stat(
                    pm.id, season, date_str,
                    venue=venue_split, time_of_day=time_split,
                    team_id=pitcher_team_id)
                if split_stat is not None:
                    import dataclasses
                    m[pm_attr] = dataclasses.replace(pm, stat=split_stat)
                    m[f"_{pm_attr}_split_label"] = f"{split_label_base} split ({n} starts)"
                else:
                    m[f"_{pm_attr}_split_label"] = f"full-season (only {n} {split_label_base} starts)"
    projections = P.build_pitcher_projection_rows(rows, meta, seed=11, real_lines=real_lines)
    fip_rows = []
    for m in meta:
        gd = m.get("game_date")
        import projections as _P
        is_day = _P._is_day_game_from_iso(gd)
        for pm, team, opp, team_id, is_home in (
                (m["home_pm"], m["home_name"], m["away_name"], m.get("home_id"), True),
                (m["away_pm"], m["away_name"], m["home_name"], m.get("away_id"), False)):
            if pm.id is None or pm.era == 0:
                continue
            # Last-start regression signal -- added directly on request, closing a real,
            # evidenced gap: reuses pm.era (already computed for the FIP table right below) as
            # season_era so this doesn't redundantly re-aggregate the same real number a second
            # way. See mlb_engine.last_start_regression_signal's own docstring for the full
            # reasoning -- None (not a fabricated trend) when his last start was too short a
            # sample to read, or he has no real starts logged yet.
            last_start = E.last_start_regression_signal(pm.id, int(date_str[:4]), date_str,
                                                         season_era=pm.era)
            fip_rows.append({
                "Pitcher": pm.name, "Team": team, "Opponent": opp, "Hand": pm.hand,
                "ERA": round(pm.era, 2), "FIP": pm.fip, "Delta": round(pm.era - pm.fip, 2),
                "K/9": round(pm.k9, 1), "WHIP": round(pm.whip, 2), "HR/9": round(pm.hr9, 2), "OBA": pm.oba,
                "Last Start": last_start["tag"] if last_start else "— (no recent start on file)",
                "Last ERA": last_start["last_era"] if last_start else None,
                "Last IP": last_start["last_ip"] if last_start else None,
                "_game_date": gd, "_team_id": team_id,
                "_is_home": is_home, "_is_day_game": is_day,
            })
    return fip_rows, projections, meta


import best_bets_data as BBD
col_a, col_b = st.columns([2, 1])
with col_a:
    target_date = st.date_input("Analysis Date", datetime.now())
with col_b:
    fip_constant = st.number_input("FIP constant", value=E.FIP_CONSTANT_DEFAULT,
                                   step=0.01, help="Season-specific; ~3.1-3.2.")

date_str = target_date.strftime("%Y-%m-%d")
venue_split, time_split = BBD.render_split_selector(key_prefix="pitching_lab")

with st.spinner("Loading starters and opposing lineups..."):
    fip_rows, proj_rows, meta = load(date_str, fip_constant, venue_split, time_split)

# Guarantees THIS session's own quick_log real-price side-channel is populated, regardless of
# whether load() above was a cache hit for this session specifically -- see best_bets_data.
# ensure_mlb_offers_session_state's own docstring for the real, confirmed cross-session bug this
# fixes. Called here, in genuinely uncached top-level page code, not inside load() itself (which
# is @st.cache_data-wrapped and would silently reintroduce the identical bug).
BBD.ensure_mlb_offers_session_state(
    date_str, BBD.get_odds_api_key(), st.session_state.get("_preferred_book_mlb", O.DEFAULT_BOOK))

# Situational display filter: when a split is active, only show pitchers who are actually
# in that situation tonight (home starters in home games, etc.)
if venue_split or time_split:
    def _matches(r):
        is_home = r.get("_is_home")
        is_day = r.get("_is_day_game")
        if venue_split == "home" and is_home is False:
            return False
        if venue_split == "away" and is_home is True:
            return False
        if time_split == "day" and is_day is False:
            return False
        if time_split == "night" and is_day is True:
            return False
        return True

    matching = {r["Pitcher"] for r in fip_rows if _matches(r)}
    fip_rows = [r for r in fip_rows if r["Pitcher"] in matching]
    proj_rows = [r for r in proj_rows if r["Pitcher"] in matching]

if not fip_rows:
    st.info("No probable starters found for this date. Pick a date with scheduled games.")
    st.stop()

df = pd.DataFrame(fip_rows)
df["Time"] = df["_game_date"].apply(game_time_et)

# === Matchup-aware projections =============================================
C.section_header("⚡", "Matchup-aware starter projections")
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
    # "SO o5.5" used to be a hardcoded, fixed-number column header -- a real, confirmed bug, not
    # just a cosmetic quirk: K line is actually computed PER PITCHER (a real book line via
    # real_line_or_default when available, this platform's own default otherwise -- see K
    # LineSource just below), and was silently dropped from the display entirely. A person
    # reading "SO o5.5" had no way to know the real probability shown might be evaluated against
    # a genuinely different threshold for that specific pitcher. Now shows the real K line as its
    # own column, and uses generic headers (no baked-in number) for the probability/fair columns.
    show = pdf.rename(columns={"K over%": "K Over%", "K fair": "K Fair"})
    cols = ["Time", "Pitcher", "Team", "Opp", "Hand", "Proj IP", "Proj K", "K line", "K Over%",
            "K Fair", "Proj BB", "Proj Outs", "Proj TTO", "ERA", "FIP"]
    show = show[[c for c in cols if c in show.columns]]
    st.dataframe(
        show.style.format({"K Over%": "{:.1%}", "K line": "{:.1f}", "Proj IP": "{:.1f}",
                           "Proj K": "{:.1f}", "Proj BB": "{:.1f}", "Proj Outs": "{:.1f}",
                           "Proj TTO": "{:.2f}", "ERA": "{:.2f}", "FIP": "{:.2f}"})
        .theme_gradient(cmap="RdYlGn", subset=["Proj K", "K Over%"]),
        width="stretch", hide_index=True, height=420)
    st.caption("**K line** is the real threshold each pitcher's own K Over% is actually evaluated "
              "against — a real sportsbook line when one's available, this platform's own "
              "default otherwise (see the Edge Board / Best Bets tables for a per-pitcher "
              "book-vs-default breakdown). It varies by pitcher — reading K Over% without it "
              "would leave the real number this table is answering invisible.")
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
C.section_header("📉", "ERA vs FIP regression")
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
st.dataframe(styled, width="stretch", hide_index=True)

# === Last-start regression signal ==========================================
st.divider()
C.section_header("🔁", "Last start trend")
st.caption("A genuinely different, SHORTER-horizon read than the ERA vs FIP table above -- that "
          "one compares a pitcher's whole SEASON to his own peripherals (a season-long luck-vs-"
          "skill question). This compares his single MOST RECENT start to his own season ERA: "
          "was his last outing unusually good or bad relative to his real level, and might the "
          "next one regress back toward it. Closing a real, evidenced gap -- this exact pattern "
          "was being tracked by hand, with screenshots, before this existed. ERA from one start "
          "is a small sample on purpose treated as directional, not a probability -- a last "
          "start under 3 IP is left off entirely rather than shown with a noisy, misleading "
          "number (see the — rows below).")
trend_cols = ["Time", "Pitcher", "Team", "Opponent", "Hand", "Last Start", "Last ERA", "Last IP", "ERA"]
trend_df = df.sort_values("Delta", ascending=False)[[c for c in trend_cols if c in df.columns]]
st.dataframe(
    trend_df.style.format({"Last ERA": "{:.2f}", "Last IP": "{:.1f}", "ERA": "{:.2f}"}, na_rep="—"),
    width="stretch", hide_index=True)

# === Bullpen fatigue =========================================================
st.divider()
C.section_header("💪", "Bullpen fatigue")
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
                hide_index=True, width="stretch")
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

    # === Live pitch count ======================================================================
    # Added directly on request, after a real, repeated pattern: real traders manually tracking a
    # starter's live pitch count mid-game to gauge how much longer he'll last and whether he's
    # cruising or getting hit hard ("He's at 68 pitches but best part he has just 1 hit no runs").
    # RAW NUMBERS ONLY, deliberately not a prediction -- see mlb_engine.get_live_pitching_line's
    # own docstring for why "innings left" or "pull probability" isn't attempted here; that's a
    # claim about a live, in-progress managerial decision, a different and harder thing than
    # showing the same real facts a trader would already read by eye.
    st.markdown("**📟 Live pitch count**")
    st.caption("Pitch count and today's real line for whoever's actually pitching right now — "
              "only meaningful once the game has started. Manual refresh always works; "
              "auto-refresh below is a real, ongoing cost while enabled (a fresh live fetch "
              "every ~10 seconds for both sides), so it's opt-in, not the default.")
    if picked.get("gamePk"):
        live_auto = False
        if _HAS_AUTOREFRESH:
            live_auto = st.checkbox(
                "🔴 Auto-refresh every ~10s while this game is live", value=False,
                key=f"live_auto_{picked['gamePk']}",
                help="Turn this off (or navigate away) once you're done watching this specific "
                    "game — it keeps re-fetching both teams' live boxscore in the background "
                    "the whole time it's checked. The refresh interval is a rough estimate, not "
                    "an exact timer (a real, stated limitation of the underlying component).")
            if live_auto:
                st_autorefresh(interval=10_000, key=f"live_autorefresh_{picked['gamePk']}")
        else:
            st.caption("⚪ Auto-refresh isn't available in this deploy (the optional "
                      "`streamlit-autorefresh` package isn't installed) — manual refresh below "
                      "still works normally.")

        lc1, lc2 = st.columns(2)
        for col, label, side in ((lc1, picked["home_name"], "home"),
                                 (lc2, picked["away_name"], "away")):
            with col:
                st.markdown(f"**{label}**")
                state_key = f"live_line_{side}_{picked['gamePk']}"
                manual_clicked = st.button("🔄 Refresh live line",
                                           key=f"live_refresh_{side}_{picked['gamePk']}")
                if manual_clicked:
                    with st.spinner("Checking live boxscore..."):
                        st.session_state[state_key] = E.get_live_pitching_line(picked["gamePk"], side)
                elif live_auto:
                    st.session_state[state_key] = E.get_live_pitching_line(picked["gamePk"], side)

                line = st.session_state.get(state_key)
                if line is None:
                    st.caption("⏳ Not started yet, or hasn't been checked — press refresh, or "
                              "enable auto-refresh above.")
                else:
                    lm1, lm2, lm3 = st.columns(3)
                    lm1.metric("Pitches", line["pitches"])
                    lm2.metric("IP", line["innings_pitched"])
                    lm3.metric("H / ER", f"{line['hits']} / {line['earned_runs']}")
                    st.caption(f"{line['name']} — {line['strikeouts']} K, {line['walks']} BB "
                              "today. Raw numbers only — no pull prediction.")

                    # Unearned-run flag — added directly on request, after a real, live piece of
                    # community confusion (checked against the actual chat log): a fielding error
                    # meant runs that clearly scored didn't count as earned, and it took several
                    # messages of manual ESPN cross-checking before anyone understood why. runs
                    # and earned_runs are both already in `line` above — this is the same data,
                    # just surfaced directly instead of requiring a person to notice the mismatch.
                    if line["unearned_runs"] > 0:
                        st.warning(f"⚠️ {line['unearned_runs']} of {line['name']}'s {line['runs']} "
                                  f"run(s) today are **unearned** (a fielding error factored in) — "
                                  f"his earned-run total ({line['earned_runs']}) won't match the "
                                  f"raw runs you're watching score. This is why an earned-run prop "
                                  f"can stay Under even after a run visibly crosses the plate.")

                    # Hook-risk flag — same real scenario this platform's own community hit: a
                    # strikeout prop riding on "one more" late, with no visibility into whether
                    # this pitcher's own season workload pattern makes that likely. Compares
                    # against HIS OWN real season average/max, not a league-wide number.
                    if line.get("player_id"):
                        team_id_for_side = picked["home_id"] if side == "home" else picked["away_id"]
                        season_pitch_stats = E.pitcher_season_pitch_stats(
                            line["player_id"], int(date_str[:4]), before_date=date_str,
                            team_id=team_id_for_side)
                        risk = E.hook_risk_flag(line["pitches"], season_pitch_stats)
                        if risk:
                            st.caption(risk)
    else:
        st.caption("No game id available for this matchup — live pitch count isn't available here.")

    # === EXPERIMENTAL: full Monte Carlo game simulation (Option A, Method 1) -------------------
    # Added directly on request, after building and testing the underlying simulation engine
    # (projections.simulate_game_win_probability) separately with synthetic data. This is the
    # REAL DATA WIRING step: fetches both teams' actual 9-man lineups (mlb_engine.
    # build_game_lineups) and runs them through that engine. UNBACKTESTED -- same honest
    # limitation as the lighter Pythagorean/Log5 estimate on Game Watch, doubled: this is a
    # bigger, more complex model with more places a real calibration error could hide, and
    # there's been zero opportunity to check it against actual outcomes from this sandbox.
    #
    # REAL, STATED SIMPLIFICATIONS STILL IN THE WIRING (on top of the engine's own, see
    # projections.py's module comment above simulate_one_game): a starter's own rest/matchup-
    # lineup adjustments used elsewhere on this platform (rest_adjustment_multipliers, opponent-
    # lineup K/BB odds-ratio) are NOT applied here -- each starter/bullpen is projected from his
    # own season rates alone. Real weather (via weather.get_game_weather, same function Dinger
    # Engine's own game-by-game read uses) IS applied now -- added directly on request, no
    # longer a stated gap.
    #
    # REAL COST, substantial: up to 18 hitter fetches, 2 starter fetches, 1 boxscore fetch, 2
    # bullpen-aggregate fetches, 1 weather fetch, PLUS the simulation itself (n_trials full
    # 9-inning games) -- the most expensive single feature on this platform. On-demand only.
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
    apc1, apc2 = st.columns([1, 2])
    with apc1:
        adaptive_pull = st.checkbox("Adaptive starter pull", value=True,
                                    help="Pull a starter early in a given trial if he's allowed "
                                        "too many runs, instead of always pitching his full "
                                        "expected outs regardless of how the trial is going.")
    with apc2:
        early_pull_runs = st.number_input(
            "Pull after this many runs allowed", min_value=1, max_value=10, value=5, step=1,
            disabled=not adaptive_pull,
            help="A real, stated 'quick hook' rule, not a claim to model actual manager "
                "decisions precisely — there's no single agreed formula for real in-game pull "
                "decisions (checked directly: genuinely hard to project even for people who "
                "track bullpen usage full-time). See projections.simulate_one_game's own "
                "docstring for the full reasoning.")
    multi_reliever = st.checkbox(
        "Multi-reliever bullpen sequencing (identify each team's own closer by real saves data)",
        value=True,
        help="Instead of one blended bullpen rate for every relief inning, identifies each "
            "team's own likely closer (most real saves on the active staff) and uses his own "
            "individual rates for the 9th inning specifically, once the starter is out — the "
            "rest of the bullpen still uses the blended aggregate for any earlier relief "
            "innings. A real, stated proxy (saves), not a guaranteed-correct role read — a "
            "genuine closer-committee team will still return whoever has the most saves. Real "
            "additional cost: one full staff of pitcher fetches per team.")
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
                statcast_lookup, statcast_k = SC.load_cached()
                park = P.PARK_FACTORS.get(picked.get("venue_id"), P.NEUTRAL_PARK)
                home_pm, away_pm = lineups["home_pm"], lineups["away_pm"]

                # Real weather -- the SAME get_game_weather Dinger Engine's own game-by-game
                # weather read already uses, added directly on request after this was shipped as
                # a stated v1 simplification (weather_hr fixed at 1.0). An indoor/dome game or a
                # failed fetch falls back to weather_hr=1.0 (neutral) -- honest, not guessed.
                weather_hr = 1.0
                try:
                    wx = WX.get_game_weather(picked.get("venue_id"), picked.get("game_date"), picked.get("venue"))
                    if wx and not wx.get("dome"):
                        weather_hr = wx.get("hr_factor", 1.0)
                except Exception:
                    pass   # weather_hr stays neutral -- an honest fallback, not a blocked simulation

                away_bullpen_stat = E.get_bullpen_aggregate_stat(picked["away_id"], exclude_pid=away_pm.id)
                home_bullpen_stat = E.get_bullpen_aggregate_stat(picked["home_id"], exclude_pid=home_pm.id)
                away_starter_proj = P.project_pitcher(away_pm.stat)
                home_starter_proj = P.project_pitcher(home_pm.stat)

                # Multi-reliever sequencing: each side's own closer, identified by real saves
                # data (mlb_engine.get_bullpen_closer's own docstring has the full reasoning and
                # stated limitations). None when the toggle is off, or when no clear closer is
                # found (get_bullpen_closer's own honest "no fabricated pick" contract) -- either
                # way, simulate_game_win_probability's own closer params default to None-safe.
                away_closer = home_closer = None
                if multi_reliever:
                    away_closer = E.get_bullpen_closer(picked["away_id"], exclude_pid=away_pm.id)
                    home_closer = E.get_bullpen_closer(picked["home_id"], exclude_pid=home_pm.id)

                sim_result = None
                if not (away_bullpen_stat and home_bullpen_stat and away_starter_proj and home_starter_proj):
                    st.warning("One or both starters/bullpens don't have enough real season data "
                              "to project (a very early-season sample, or a true bullpen-game "
                              "opener) — the simulation needs a real projection for both sides.")
                else:
                    home_probs = _build_lineup_probs(lineups["home_rows"], away_pm.stat, away_bullpen_stat,
                                                     park, statcast_lookup, statcast_k, weather_hr=weather_hr)
                    away_probs = _build_lineup_probs(lineups["away_rows"], home_pm.stat, home_bullpen_stat,
                                                     park, statcast_lookup, statcast_k, weather_hr=weather_hr)
                    if home_probs is None or away_probs is None:
                        st.warning("Couldn't build real matchup probabilities for every batter in "
                                  "one or both lineups (thin individual sample) — the simulation "
                                  "needs a real projection for all 18 real batters.")
                    else:
                        # away_probs_vs_closer = AWAY lineup's own read facing HOME's closer
                        # (mirrors away_probs the same way away_probs itself mirrors "away
                        # lineup facing home's starter/bullpen" -- see simulate_one_game's own
                        # docstring for why this exact naming convention matters).
                        away_probs_vs_closer = (
                            _build_lineup_probs_vs_one_pitcher(lineups["away_rows"], home_closer.stat,
                                                               park, statcast_lookup, statcast_k,
                                                               weather_hr=weather_hr)
                            if home_closer else None)
                        home_probs_vs_closer = (
                            _build_lineup_probs_vs_one_pitcher(lineups["home_rows"], away_closer.stat,
                                                               park, statcast_lookup, statcast_k,
                                                               weather_hr=weather_hr)
                            if away_closer else None)
                        sim_result = P.simulate_game_win_probability(
                            away_probs[0], away_probs[1], home_starter_proj["exp_outs"],
                            home_probs[0], home_probs[1], away_starter_proj["exp_outs"],
                            n_trials=n_trials,
                            early_pull_runs=int(early_pull_runs) if adaptive_pull else None,
                            away_probs_vs_closer=away_probs_vs_closer,
                            home_probs_vs_closer=home_probs_vs_closer)

            if sim_result:
                mc1, mc2, mc3 = st.columns(3)
                mc1.metric(f"{picked['away_name']} (away)", f"{sim_result['away_win_prob']:.0%}")
                mc2.metric(f"{picked['home_name']} (home)", f"{sim_result['home_win_prob']:.0%}")
                mc3.metric("Tied after 9 (extras not simulated)", f"{sim_result['tie_prob']:.0%}")
                st.caption(f"Average simulated score: {picked['away_name']} "
                          f"{sim_result['avg_away_runs']:.1f} — {picked['home_name']} "
                          f"{sim_result['avg_home_runs']:.1f}, across {sim_result['n_trials']} trials.")
                if multi_reliever:
                    away_closer_name = away_closer.name if away_closer else "no clear closer identified"
                    home_closer_name = home_closer.name if home_closer else "no clear closer identified"
                    st.caption(f"🔒 Closers used for the 9th inning: {picked['away_name']} — "
                              f"{away_closer_name}; {picked['home_name']} — {home_closer_name}. "
                              "Identified by real saves data — see the checkbox's own help text "
                              "for the stated limitation on closer-committee bullpens.")
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

    # === Pitcher consistency: is this guy steady or streaky start to start? -------------------
    # Added directly on request, after a real, specific conversation: someone manually eyeballing
    # a screenshot of a starter's last several games looking for a pattern ("he can either go out
    # there giving it up or go out there and have a shit outta game"), and a real, sharp pushback
    # from someone else in the same conversation: "next team he faces still has to meet the
    # criteria... probably a random occurrence [not a real pattern]." This gives a real number
    # for that question instead of eyeballing a screenshot.
    st.markdown("**📈 Pitcher consistency (steady vs. streaky, start to start)**")
    st.caption("How much does this starter's own performance actually swing game to game, using "
              "his real last "
              f"{CONSISTENCY_LOOKBACK_STARTS} starts? Coefficient of variation (CV) per stat — "
              "lower means steadier, higher means more boom-or-bust.\n\n"
              "⚠️ **NOT opponent-adjusted, read this before trusting it.** This measures raw "
              "swings only — it does NOT separate genuine streakiness from just having faced a "
              "tough lineup in a bad start and a weak one in a good start, which is exactly the "
              "real distinction that prompted building this. A true opponent-adjusted version "
              "would need a real boxscore fetch per start plus a real opponent-quality metric to "
              "compare against — a genuinely bigger build, not included here. Costs a real "
              "fetch per start scanned, so it's on-demand, not automatic.")
    pc1, pc2 = st.columns(2)
    for col, label, sp in ((pc1, picked["home_name"], picked["home_pm"]),
                           (pc2, picked["away_name"], picked["away_pm"])):
        with col:
            st.markdown(f"**{label}** — {sp.name}")
            if st.button("Check consistency", key=f"consistency_{sp.id}"):
                with st.spinner(f"Pulling {sp.name}'s real starts this season..."):
                    season = int(date_str[:4])
                    starts = E.get_pitcher_starts_this_season(sp.id, season, before_date=date_str)
                    starts_sorted = sorted(starts, key=lambda s: s.get("game_date") or "")
                    recent = starts_sorted[-CONSISTENCY_LOOKBACK_STARTS:]
                    result = P.pitcher_consistency_index(recent, min_starts=5)
                if not result:
                    st.caption(f"Not enough real starts yet this season (fewer than 5 with "
                              "usable innings) for a real consistency read.")
                else:
                    for key, tab_label in (("hits", "Hits/9"), ("strikeOuts", "K/9"),
                                          ("earnedRuns", "ERA, that start")):
                        stat_result = result.get(key)
                        if not stat_result:
                            continue
                        cv = stat_result["cv"]
                        tag = ("—" if cv is None else
                              "🟢 Consistent" if cv < 0.30 else
                              "🟡 Moderate" if cv < 0.60 else
                              "🔴 Streaky")
                        sc1, sc2, sc3 = st.columns(3)
                        sc1.metric(f"{tab_label} avg", f"{stat_result['mean']:.2f}")
                        sc2.metric("CV", f"{cv:.2f}" if cv is not None else "—")
                        sc3.markdown(f"**{tag}**")
                        with st.expander(f"{tab_label} — last {result['n_starts']} starts"):
                            st.line_chart(stat_result["per_start"])
                    st.caption(f"Based on his real last {result['n_starts']} starts with usable "
                              "innings — a real, stated judgment call on window size (last "
                              f"{CONSISTENCY_LOOKBACK_STARTS}), not empirically tuned. 🟢/🟡/🔴 "
                              "thresholds (CV < 0.30 / 0.30–0.60 / ≥ 0.60) are also a real, "
                              "stated judgment call, not derived from this platform's own data.")
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
C.section_header("🤳", "Discussion hooks (auto-generated)")
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
