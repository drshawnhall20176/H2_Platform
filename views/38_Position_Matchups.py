"""
Position Matchups — each team's depth chart, position by position, against the OPPOSING defense, plus
the two teams' head-to-head history. NFL, NCAAF, NBA and NCAAMB.

For every game: what each defense has allowed to each position slot (QB / RB1-2 / WR1-3 / TE1 in
football, Guards / Forwards / Centers in basketball), ranked across the league (1 = softest), lined up
against the offense's starter at that slot with his recent form and his history against this defense.
The pure maths is in position_matchups.py, the loading in position_data.py — see their docstrings for
exactly how a "slot" is defined and the limits of each sport's data.
"""

from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

import components as C
import best_bets_data as BBD
import odds_api as O
import position_data as PD
import position_lines as PL
import position_logview as PV
import position_matchups as PM
import sports
import styling  # noqa: F401  (installs the theme-proof styles)
from streamlit_page_cache import invalidate_page

_active = sports.active()
eastern = pytz.timezone("US/Eastern")
game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER

C.base_css()
C.page_header("🧭", f"Position Matchups  ·  {_active.icon} {_active.label}",
              "Each team's depth chart, position by position, against the opposing defense — who the defense is "
              "soft or tough against — plus the two teams' head-to-head history.")

if not sports.require_sport(list(PM.SUPPORTED_SPORTS), "Position Matchups"):
    st.stop()

SPORT_KEY = _active.key
FAMILY = PM.FAMILY_BY_SPORT[SPORT_KEY]


@st.cache_data(ttl=600, show_spinner=False)
def load_games(sport_key: str, date_str: str):
    return PD.list_games(sport_key, date_str)


@st.cache_data(ttl=900, show_spinner=False)
def load_bundle(sport_key: str, date_str: str, game_json: str, previous: bool):
    import json
    return PD.load_bundle(sport_key, date_str, json.loads(game_json), previous)


c1, c2, c3 = st.columns([2, 2, 1])
with c1:
    default_day = datetime.now(eastern).date()
    target_date = st.date_input("Slate date", default_day, key="pm_date")
with c2:
    previous = False
    if FAMILY == "football":
        choice = st.selectbox(
            "Defense data", ["This season so far", "Last season (full)"], key="pm_season",
            help="Early in a season a defense has only a few games, and ranks wobble. Last season's full "
                 "record is steadier but is last year's team.")
        previous = choice.startswith("Last")
with c3:
    st.write("")
    if st.button("🔄 Refresh", key="pm_refresh"):
        invalidate_page("position_matchups")
        st.cache_data.clear()
        st.rerun()
date_str = target_date.strftime("%Y-%m-%d")
C.season_notice(_active.key, date_str)

with st.spinner(f"Loading the {_active.label} schedule..."):
    try:
        games = load_games(SPORT_KEY, date_str)
    except Exception:
        games = []
if not games:
    st.info(f"No {_active.label} games found for {date_str}. Try another date — football slates are weekly, "
            "basketball is that day's games.", icon="🕐")
    st.stop()

for g in games:
    dt = game_dt(g.get("game_date"))
    g["_slot"] = slot_of(dt)
    g["_when"] = dt.strftime("%a %-I:%M %p ET") if dt else "time TBD"

slots_present = sorted({g["_slot"] for g in games}, key=lambda s: SLOT_ORDER.get(s, 9))
f1, f2 = st.columns([1, 3])
with f1:
    slot_pick = st.selectbox("Time slot", ["All slate"] + slots_present, key="pm_slot")
in_slot = games if slot_pick == "All slate" else [g for g in games if g["_slot"] == slot_pick]
with f2:
    query = ""
    if len(in_slot) > 25:
        query = st.text_input("Find a team", key="pm_find", placeholder="type part of a team name")
    options = {f"{g['_when']} — {g['label']}": g for g in in_slot if query.lower() in g["label"].lower()}
    if not options:
        st.info("No games match — widen the time slot or clear the search.", icon="🔎")
        st.stop()
    game_label = st.selectbox("Game", list(options), key="pm_game")
game = options[game_label]

import json
with st.spinner("Building the position matchups (first load of a game can take a moment)..."):
    try:
        bundle = load_bundle(SPORT_KEY, date_str, json.dumps({k: v for k, v in game.items() if not k.startswith("_")},
                                                             default=str), previous)
    except Exception as exc:                                       # noqa: BLE001
        st.warning(f"Couldn't build this matchup ({type(exc).__name__}). Try Refresh, another game, or another date.")
        st.stop()

names = bundle["names"]
home_name, away_name = names[bundle["home"]], names[bundle["away"]]
st.caption(f"**{away_name} @ {home_name}** · {game['_when']} · slots are measured in **{bundle['metric']}**"
           + (f" · defenses sampled: {bundle['games_sampled'][1]} games for {away_name}, "
              f"{bundle['games_sampled'][0]} for {home_name}" if bundle.get("games_sampled") else ""))
for note in bundle["notes"]:
    st.caption(f"ℹ️ {note}")

tab_pos, tab_h2h = st.tabs(["🧭 Depth vs defense", "⚔️ Head-to-head"])


def render_side(side, off_name, def_name):
    st.markdown(f"#### {off_name} offense  vs  {def_name} defense")
    if not side["ranked"]:
        st.caption("Not enough defenses with a full sample to rank yet, so the table shows what this defense has "
                   "allowed per game without a league rank." if FAMILY == "basketball" and SPORT_KEY == "NCAAMB" else
                   "Not enough games yet to rank the defenses at these slots — try the other season option.")
    co = PM.callouts(side, off_name, def_name)
    if co["targets"] or co["fades"]:
        left, right = st.columns(2)
        with left:
            st.markdown("**🟢 Targets**")
            for t in co["targets"] or ["Nothing clearly soft."]:
                st.markdown(f"- {t}")
        with right:
            st.markdown("**🔴 Fades**")
            for t in co["fades"] or ["Nothing clearly tough."]:
                st.markdown(f"- {t}")
    df = pd.DataFrame(PM.display_rows(side["rows"]))
    st.dataframe(df, hide_index=True, width="stretch")


@st.cache_data(ttl=900, show_spinner=False)
def load_nfl_log(date_str: str):
    return PD.load_nfl_log(date_str)


def _game_log_source():
    """What the game log reads: the stacked two-season NFL data (loaded once per date), or the game's own bundle."""
    if SPORT_KEY == "NFL":
        with st.spinner("Loading last season + this season's play-by-play for the game log (first load only)..."):
            try:
                d = load_nfl_log(date_str)
            except Exception as exc:                                    # noqa: BLE001
                return None, f"Couldn't load the NFL game-log data ({type(exc).__name__}). Try Refresh."
        return d, None
    return {"allowed": bundle.get("allowed") or {}, "meta": bundle.get("meta") or {},
            "all_names": bundle.get("all_names") or names, "logos": {}, "headshots": {}, "absences": {}, "regulars": {},
            "notes": [], "has_pbp": False}, None


def _opposing_starters(defense, slot):
    """Names of the opposing offense's players at `slot` (starter first) when `defense` is one of this game's two teams."""
    if defense == bundle["home"]:
        side = bundle["away_off"]
    elif defense == bundle["away"]:
        side = bundle["home_off"]
    else:
        return None, []
    row = next((r for r in side["rows"] if r["slot"] == slot), None)
    return side["offense"], [p["name"] for p in (row or {}).get("players", []) if p.get("name")]


def render_game_log():
    """Pick a position and a defense — see that position's line in each of the defense's recent games."""
    st.markdown("#### 📋 Game log — a position against one defense")
    src, err = _game_log_source()
    if err:
        st.warning(err)
        return
    allowed, all_names = src["allowed"], src["all_names"]
    options = PM.defense_options(allowed, bundle["home"], bundle["away"], all_names, SPORT_KEY)
    if not options:
        st.caption("No defense has games in the sample yet, so there is no game log to show.")
        return
    for note in src["notes"]:
        st.caption(f"ℹ️ {note}")
    slots = PM.SLOTS_BY_SPORT[SPORT_KEY]
    nfl = SPORT_KEY == "NFL"
    pair = {bundle["home"], bundle["away"]}
    # (No widget keys on the pickers whose options change with the game / sport / defense: their identity follows
    # their options, so a new list starts at its default instead of a stale choice that isn't on offer.)
    g1, g2, g3, g4 = st.columns([2, 3, 2, 2])
    with g1:
        slot = st.selectbox("Position", slots, format_func=lambda x: f"{x} — {PM.SLOT_LABEL[x]}")
    with g2:
        defense = st.selectbox("Defense", options, index=0,
                               format_func=lambda t: f"{all_names.get(t, t)}" + ("  ★ this game" if t in pair else ""))
    with g3:
        size_label = st.selectbox("Games", [lbl for lbl, _ in PM.LOG_SIZES], index=1, key="pm_log_n")
    with g4:
        venue = st.radio("Where the defense played", list(PM.LOG_VENUES), horizontal=True, key="pm_log_venue")
    period, primetime, setting, role, only_opp, without, ranges = "Full Game", False, "All", "All", None, [], []
    slot_by = "Usage"
    columns = PM.log_columns(SPORT_KEY, slot)
    if nfl:
        f0, f1, f2, f3, f4 = st.columns([2, 2, 2, 2, 2])
        with f0:
            slot_by = st.selectbox("Slot defined by", ["Usage", "Depth chart"], key="pm_log_slotby",
                                   disabled=not src.get("allowed_chart"),
                                   help="Usage: whoever was targeted / carried most in the game. Depth chart: the player listed at that "
                                        "spot on the chart published the day before the game (how Doink picks its WR1).")
        with f1:
            period = st.selectbox("Part of the game", list(PM.GAME_PERIODS), key="pm_log_period",
                                  disabled=not src["has_pbp"],
                                  help="Halves and quarters come from play-by-play. Overtime counts in the 2nd half.")
        with f2:
            setting = st.selectbox("Stadium", list(PM.LOG_SETTINGS), key="pm_log_setting")
        with f3:
            role = st.selectbox("Defense was", list(PM.LOG_ROLES), key="pm_log_role",
                                help="Favorite / underdog by the closing spread.")
        with f4:
            st.write("")
            primetime = st.checkbox("Primetime only", key="pm_log_prime", help="Kickoffs at 7:00 PM Eastern or later.")
        offense_key, _ = _opposing_starters(defense, slot)
        h1, h2 = st.columns([1, 3])
        with h1:
            if offense_key is not None and st.checkbox(f"Only vs {all_names.get(offense_key, offense_key)}", key="pm_log_only_opp"):
                only_opp = offense_key
        with h2:
            pool = [r["name"] for r in src["regulars"].get(defense, [])]
            if pool:
                without = st.multiselect("Without these defenders (games they didn't play)", pool,
                                         help="Regular defenders by snaps. Counted as out when the snap counts show no "
                                              "defensive snaps in a game between two they did play.")
    r1, r2, r3 = st.columns([2, 1, 1])
    stat_labels = {label: key for key, label in columns}
    with r1:
        rng_label = st.selectbox("Filter by a stat", ["(none)"] + list(stat_labels), key=f"pm_rng_stat_{slot}",
                                 help="Keep only games where the position's number falls in a range.")
    if rng_label != "(none)":
        with r2:
            lo = st.number_input("Min", value=None, step=1.0, key=f"pm_rng_lo_{slot}_{rng_label}")
        with r3:
            hi = st.number_input("Max", value=None, step=1.0, key=f"pm_rng_hi_{slot}_{rng_label}")
        ranges = [(stat_labels[rng_label], lo, hi)]
    n = dict(PM.LOG_SIZES)[size_label]
    if nfl and slot_by == "Depth chart" and src.get("allowed_chart"):
        allowed = src["allowed_chart"]
    log = PM.slot_game_log(allowed, defense, slot, SPORT_KEY, src["meta"], n=n, venue=venue, period=period,
                           primetime=primetime, setting=setting, role=role, only_opp=only_opp, ranges=ranges,
                           without=without, absences=src["absences"], columns=columns)
    def_name = all_names.get(defense, defense)
    st.markdown(f"**{slot}s vs {def_name} defense** · {period}" + (" · by depth chart" if nfl and slot_by == "Depth chart"
                                                                   and src.get("allowed_chart") else ""))
    if not log["period_ok"]:
        st.info("Half and quarter splits need play-by-play, which isn't loaded here — showing full games.", icon="ℹ️")
    if not log["rows"]:
        st.info(f"No games for {def_name} match those filters in the sample"
                f"{' (venue unknown for some games)' if venue != 'All' else ''}. Loosen a filter or widen the window.",
                icon="🔎")
        return
    metric_name = PM.METRIC_SHORT[FAMILY]
    best, hits = {}, {}
    if nfl:
        best = _book_lines_panel(defense, slot, columns, all_names)
        if best:
            hits = PM.hit_rates(log["rows"], PL.lines_from(best))
    st.markdown(PV.log_html(log, all_names, metric_name, whole=nfl, logos=src["logos"], headshots=src["headshots"],
                            hits=hits, best=best), unsafe_allow_html=True)

    h1, h2, h3 = st.columns([2, 2, 3])
    avg = log["avg"]
    stat_choices = {lbl: key for key, lbl in log["stat_cols"]}
    stat_choices[metric_name] = "pts"
    with h1:
        hit_label = st.selectbox("Test your own line on", list(stat_choices), key="pm_hit_stat")
    key = stat_choices[hit_label]
    mean = avg["pts"] if key == "pts" else avg["stats"][key]
    with h2:
        line = st.number_input("Line", min_value=0.0, step=0.5, value=round(mean * 2) / 2,
                               key=f"pm_hit_line_{defense}_{slot}_{key}")
    hr = PM.hit_rate(log["rows"], key, line)
    with h3:
        st.metric(f"Over {line:g} {hit_label}", f"{hr['hits']}/{hr['games']}  ({hr['pct']:.0f}%)")
    st.caption("Colours compare each game with that column's average (green = more than average). Every filter is "
               "applied before the window, so \"Home, Last 5\" is five home games. A game where the opponent had nobody "
               "at the slot counts as zero, the same way the league rank treats it. "
               + ("Basketball rows are the whole position group's totals; the Player column lists its top scorers."
                  if FAMILY == "basketball" else
                  ("Player is whoever the depth chart listed there the day before the game (games with no chart on file fall back to usage)."
                   if nfl and slot_by == "Depth chart" and src.get("allowed_chart") else
                   "Player is whoever held the slot that game by usage (carries for backs, targets for receivers).")
                  + (" The log stacks last season with this season, so ten games usually span both." if nfl else "")))


def _book_lines_panel(defense, slot, columns, all_names):
    """The Best lines / hit-rate machinery: a button (it costs Odds API credits) that loads the books' lines for the
    opposing starter, then the best line per column. Returns {column key: best line} or {} when not loaded."""
    offense_key, starters = _opposing_starters(defense, slot)
    if offense_key is None:
        st.caption("Book lines are available for the two teams in this game (pick one of the ★ defenses).")
        return {}
    if not starters:
        st.caption(f"No {all_names.get(offense_key, offense_key)} player found at {slot} to look up book lines for.")
        return {}
    markets = PL.markets_for(columns)
    c1, c2 = st.columns([2, 3])
    with c1:
        player = st.selectbox(f"Book lines for ({all_names.get(offense_key, offense_key)} {slot})", starters)
    store = st.session_state.setdefault("pm_lines", {})
    skey = (bundle["home"], bundle["away"], date_str, tuple(markets))
    with c2:
        st.write("")
        if st.button(f"📈 Load book lines  (~{len(markets)} Odds API credits)", key="pm_load_lines",
                     help="One request for this game's props at the major books. Cached for this session."):
            api_key = BBD.get_odds_api_key()
            if not api_key:
                store[skey] = {"error": "No Odds API key is configured on this deployment."}
            else:
                try:
                    ev = PL.match_event(O.fetch_events_all(api_key, sport=_active.odds_sport_key),
                                        all_names.get(bundle["home"]), all_names.get(bundle["away"]))
                except Exception as exc:                              # noqa: BLE001
                    ev, store[skey] = None, {"error": f"Couldn't list the games at the books ({type(exc).__name__})."}
                if ev is None and skey not in store:
                    store[skey] = {"error": "The books haven't listed this game yet."}
                elif ev is not None:
                    offers, e = PL.fetch_offers(api_key, ev, markets, _active.odds_sport_key)
                    store[skey] = {"error": e, "offers": offers}
    got = store.get(skey)
    if not got:
        return {}
    if got.get("error"):
        st.warning(got["error"])
        return {}
    best = PL.best_lines(got.get("offers") or [], player, columns)
    if not best:
        st.caption(f"No posted lines for {player} yet — books usually post props a few days before kickoff.")
    return best


with tab_pos:
    st.caption("1 = the defense that allows the MOST to that slot (softest). Soft = top third, Tough = bottom third. "
               + ("A slot is the player used most there that game (running backs by carries, receivers by targets), "
                  "so WR1 is usage, not just the depth-chart label." if FAMILY == "football" else
                  "Guards / Forwards / Centers use each player's ESPN position; the numbers are the whole group's totals."))
    render_side(bundle["away_off"], away_name, home_name)
    st.divider()
    render_side(bundle["home_off"], home_name, away_name)
    st.divider()
    render_game_log()

with tab_h2h:
    h = bundle["h2h"]
    st.markdown(f"**{h['sentence']}**")
    s = h["summary"]
    if s["games"]:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Meetings", s["games"])
        m2.metric(f"{home_name} wins", s["a_wins"])
        m3.metric(f"{away_name} wins", s["b_wins"])
        m4.metric("Avg total", f"{s['avg_total']:.1f}")
        rows = [{"Date": m["date"], "Game": f"{m['away']} @ {m['home']}",
                 "Score": f"{home_name} {m['a_score']:.0f} – {m['b_score']:.0f} {away_name}",
                 "Winner": m["winner"], f"Margin ({home_name})": f"{m['margin']:+.0f}", "Total": f"{m['total']:.0f}"}
                for m in h["meetings"]]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Football looks back three seasons; basketball looks back about a year (exhibitions left out). "
               "Individual players' history against this defense is the \"vs this D\" column on the other tab; "
               "the Matchup Lab has the full per-player breakdown.")
