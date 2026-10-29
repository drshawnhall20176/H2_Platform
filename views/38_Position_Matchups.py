"""
Position Matchups — each team's depth chart, position by position, against the OPPOSING defense, plus
the two teams' head-to-head history. NFL, NCAAF, NBA and NCAAMB -- and the NHL (Player props + head-to-head only).

PLAYER PROPS + SCORECARD (every sport): the projection model lives in props_engine.py (shared core),
player_props.py (basketball), football_props.py and hockey_props.py; the Scorecard tab replays loaded games
walk-forward (props_backtest.py); props_odds.py loads one game's lines from the books.

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
import player_props as PPR
import form_policy as FPol
import quick_log
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


class _NoGames(Exception):
    """Raised (never returned) for an empty schedule, so st.cache_data doesn't keep it."""


@st.cache_data(ttl=600, show_spinner=False)
def load_games(sport_key: str, date_str: str):
    # An empty list is NOT cached. A schedule feed that hiccups for one request used to come back as [],
    # get cached for 10 minutes, and make a real slate (e.g. yesterday's NBA games) read "No games found"
    # until someone pressed Refresh. Exceptions aren't cached, so the next run simply asks again.
    games = PD.list_games(sport_key, date_str)
    if not games:
        raise _NoGames()
    return games


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
    load_failed = False
    try:
        games = load_games(SPORT_KEY, date_str)
    except _NoGames:
        games = []
    except Exception:                                              # noqa: BLE001
        games, load_failed = [], True
if not games:
    if load_failed:
        st.warning(f"Couldn't load the {_active.label} schedule for {date_str} — the schedule feed didn't answer. "
                   "Press **Refresh** or try again in a moment.", icon="📡")
    else:
        st.info(f"No {_active.label} games found for {date_str}. Try another date — football slates are weekly, "
                "basketball is that day's games. If you know there were games, press **Refresh**: the schedule "
                "feed occasionally comes back empty, and this page now asks again on every load.", icon="🕐")
    st.stop()

scope = C.slate_scope(SPORT_KEY, key="pm_scope")
week_games = games
games = C.scope_items(SPORT_KEY, scope, games, lambda g: g.get("game_date"), date_str)
if not games:
    C.no_games_in_scope(_active.label, date_str, len(week_games))
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

HAS_PROPS = bool(bundle.get("props"))
tab_pos = tab_props = tab_score = None
if FAMILY == "hockey":
    tab_props, tab_h2h, tab_score = st.tabs(["🎯 Player props", "⚔️ Head-to-head", "📊 Scorecard"])
elif HAS_PROPS:
    tab_props, tab_pos, tab_h2h, tab_score = st.tabs(["🎯 Player props", "🧭 Depth vs defense", "⚔️ Head-to-head",
                                                      "📊 Scorecard"])
else:
    tab_pos, tab_h2h = st.tabs(["🧭 Depth vs defense", "⚔️ Head-to-head"])


def _model_factors(defense) -> dict:
    """Basketball: {slot: the Player props tab's matchup factor for PRA} -- the raw 4-game numbers adjusted for
    the small sample and blended with last season, so this tab and the props tab show the same matchup."""
    props = bundle.get("props") or {}
    if FAMILY != "basketball" or not props.get("cur_pgames"):
        return {}
    cur_t = PPR.defense_allowed(PM.allowed_by_slot(props["cur_pgames"], SPORT_KEY), "PRA")
    pri_t = (PPR.defense_allowed(PM.allowed_by_slot(props["prior_pgames"], SPORT_KEY), "PRA")
             if props.get("prior_pgames") else None)
    out = {}
    for slot in PM.SLOTS_BY_SPORT[SPORT_KEY]:
        cur = PPR.raw_factor(cur_t, defense, slot)
        pri = PPR.raw_factor(pri_t, defense, slot) if pri_t else None
        if cur is not None or pri is not None:
            out[slot] = PPR.blended_factor(cur, pri, "blend" if SPORT_KEY == "NBA" else "season")["factor"]
    return out


def render_side(side, off_name, def_name):
    st.markdown(f"#### {off_name} offense  vs  {def_name} defense")
    mf = _model_factors(side["defense"])
    for r in side["rows"]:
        r["model_factor"] = mf.get(r["slot"])
    if not side["ranked"]:
        st.caption("Not enough defenses with a full sample to rank yet, so the table shows what this defense has "
                   "allowed per game without a league rank." if FAMILY == "basketball" and SPORT_KEY == "NCAAMB" else
                   "Not enough games yet to rank the defenses at these slots — try the other season option.")
    co = PM.callouts(side, off_name, def_name, family=FAMILY, limit=4 if FAMILY == "basketball" else 3)
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
    df = pd.DataFrame(PM.display_rows_by_player(side["rows"]) if FAMILY == "basketball" else PM.display_rows(side["rows"]))
    st.dataframe(df, hide_index=True, width="stretch")
    moved = [r for r in side["rows"] if r.get("role_change") and r["players"]]
    if moved:
        st.caption("⚠️ **Role changes:** " + "; ".join(
            f"{r['players'][0]['name']} fills {r['slot']} ({PM.role_change_text(r['role_change'])})" for r in moved)
            + ". Players ruled out are skipped and the next man up is graded against the slot he's actually "
              "filling (**↑** in the table). His *Last 4* comes from a smaller role (**⚠️**), so treat these reads "
              "as lower confidence. Targets and Fades skip anyone with under 2 recent games or barely any "
              "production, and rank by how much of the slot a player will actually see.")


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


# =========================================================================== 🎯 Player props (every sport) + 📊 Scorecard
import football_props as FP
import hockey_props as HP
import props_backtest as BT
import props_engine as PE
import props_odds as PO

PROPS = bundle.get("props") or {}
PFAM = PROPS.get("family") or FAMILY
EDITABLE = ("Line", "Over odds", "Under odds")


def _editor_values(key: str, rows_order) -> dict:
    """{column: {row key: value}} typed into a props table so far (Line / Over odds / Under odds), read from the
    editor's own saved edits."""
    saved = st.session_state.setdefault("pm_typed", {})
    live = (st.session_state.get(key) or {}).get("edited_rows")
    if live is not None:                       # the editor is on screen: remember its edits for the read-only view
        saved[key] = live
    edits = live if live is not None else (saved.get(key) or {})
    out = {c: {} for c in EDITABLE}
    for idx, change in edits.items():
        try:
            rk = rows_order[int(idx)]
        except (ValueError, IndexError):
            continue
        for col in EDITABLE:
            if col in change:
                out[col][rk] = change[col]
    return out


def _props_lines(key: str, rows_order) -> dict:
    """The lines typed into a props table so far ({pid: line})."""
    return _editor_values(key, rows_order)["Line"]


def _market_menu():
    if PFAM == "football":
        return FP.MARKETS, FP.DEFAULT_MARKET, FP.MARKET_HELP
    if PFAM == "hockey":
        return HP.MARKETS, HP.DEFAULT_MARKET, HP.MARKET_HELP
    return PPR.MARKETS, PPR.DEFAULT_MARKET, PPR.MARKET_HELP


def _odds_key(market: str):
    if PFAM == "football":
        return FP.MARKETS[market]["odds"]
    if PFAM == "hockey":
        return HP.MARKETS[market]["odds"]
    return PPR.ODDS_MARKETS.get(market)


def _rest_days(team):
    return ((PROPS.get("rest") or {}).get(team) or {}).get("rest_days")


def _rest_text(name, days) -> str:
    txt = FPol.rest_text(days)                       # the one wording every page uses
    return f"{name}: **back-to-back** (played yesterday)" if txt == "back-to-back" else f"{name}: {txt}"


@st.cache_data(ttl=600, show_spinner=False)
def _auto_book_lines(sport_odds_key: str, date_s: str, home: str, away: str, keys):
    """The books' lines for one game + market, fetched automatically and kept 10 minutes (so switching markets
    and coming back doesn't spend credits again)."""
    api_key = BBD.get_odds_api_key()
    if not api_key:
        return {"error": None, "offers": [], "lines": {}, "no_key": True}
    return PO.fetch_game(api_key, sport_odds_key, home, away, list(keys or ()))


def render_game_context(market: str) -> dict:
    """Spread / total (loaded from the books or typed), both teams' rest, and the market-blend settings."""
    store = st.session_state.setdefault("pm_mkt", {})
    okey = _odds_key(market)
    # A points combo also loads the Points lines: a flagged Points line flags PA / PR / PRA / PB for that player.
    fetch_keys = tuple(k for k in ([okey] + (["player_points"] if PFAM == "basketball"
                                              and market in PPR.POINTS_COMBOS else [])) if k)
    gkey = (SPORT_KEY, date_str, str(bundle["home"]), str(bundle["away"]))
    skey = gkey + fetch_keys
    if skey not in store and st.session_state.get("pm_props_auto", True):
        try:
            with st.spinner(f"Getting tonight's {market} lines from the books..."):
                auto = _auto_book_lines(_active.odds_sport_key, date_str, home_name, away_name, fetch_keys)
        except Exception as exc:                                   # noqa: BLE001
            auto = {"error": f"Couldn't reach the books ({type(exc).__name__})."}
        if not auto.get("no_key"):
            store[skey] = auto
            if auto.get("lines"):
                store[gkey] = auto["lines"]
    with st.expander("🎲 Game lines, rest & the market", expanded=not (store.get(skey) or {}).get("offers")):
        c1, c2 = st.columns([2, 3])
        with c1:
            cost = len(PO.GAME_MARKETS) + len(fetch_keys)
            st.toggle("Load book lines automatically", value=True, key="pm_props_auto",
                      help=f"Fetches this game's lines when you open it or switch markets (~{cost} Odds API credits, "
                           "reused for 10 minutes).")
            if st.button(f"🔄 Refresh book lines  (~{cost} credits)", key="pm_props_load",
                         help="One request: this game's spread, total and moneyline plus every posted line for the "
                              "market above at the major books. Fills the Line and odds columns, shows the best price "
                              "and blends the books' no-vig price into the probability."):
                api_key = BBD.get_odds_api_key()
                if not api_key:
                    store[skey] = {"error": "No Odds API key is configured on this deployment."}
                else:
                    with st.spinner("Asking the books..."):
                        store[skey] = PO.fetch_game(api_key, _active.odds_sport_key, home_name, away_name,
                                                    list(fetch_keys))
                if (store[skey] or {}).get("lines"):
                    store[gkey] = store[skey]["lines"]
        got = store.get(skey) or {}
        gl = store.get(gkey) or {}
        with c2:
            if got.get("error"):
                st.warning(got["error"])
            elif got:
                st.caption(f"Loaded {len(got.get('offers') or [])} posted {market} lines"
                           + (f" · {got['remaining']} Odds API credits left" if got.get("remaining") else "")
                           + ". Use ✏️ **Enter my own lines & prices** below to use your book's numbers instead.")
            else:
                st.caption("No book lines loaded — load them, or use ✏️ **Enter my own lines & prices** below to "
                           "type the numbers from your book.")
        sp_default = gl.get("spread_home")
        if PFAM == "hockey":
            sp_default = PO.hockey_spread_from_ml(gl.get("p_home"))
        tot_default = gl.get("total")
        s1, s2, s3 = st.columns([1, 1, 2])
        with s1:
            spread = st.number_input(
                f"{home_name} {'goal margin' if PFAM == 'hockey' else 'spread'}", value=sp_default, step=0.5,
                format="%.1f", key=f"pm_spread_{game_label}_{sp_default}",
                help="Negative = the home team is favored (−6.5). Leave blank if unknown."
                     + (" Hockey: worked out from the moneyline (the ±1.5 puck line says little)." if PFAM == "hockey" else ""))
        with s2:
            total = st.number_input("Game total", value=tot_default, step=0.5, format="%.1f",
                                    key=f"pm_total_{game_label}_{tot_default}",
                                    help="The over/under. With the spread it gives each team's implied total.")
        with s3:
            if PFAM != "football":
                st.markdown(_rest_text(away_name, _rest_days(bundle["away"])) + "  \n"
                            + _rest_text(home_name, _rest_days(bundle["home"])))
            else:
                st.caption("Football is weekly — rest isn't a factor; the spread drives run/pass game script.")
        _books = [b for b in O.books_in_offers(got.get("offers") or []) if b in O.US_BOOKS]
        _book_opts = ["best"] + _books
        _pref = st.session_state.get("pm_price_book", O.DEFAULT_BOOK)
        price_book = st.selectbox(
            "Price at", _book_opts, key="pm_price_book",
            index=_book_opts.index(_pref) if _pref in _book_opts else (_book_opts.index(O.DEFAULT_BOOK)
                                                                      if O.DEFAULT_BOOK in _book_opts else 0),
            format_func=lambda b: "Best available (any book)" if b == "best" else O.book_label(b),
            help="Whose line and prices to use. Your book (DraftKings by default) shows the number you can actually "
                 "bet; the probability still leans on every book's consensus.")
        k1, k2 = st.columns(2)
        fitted = (st.session_state.get("pm_slope") or {}).get((SPORT_KEY, market))
        with k1:
            use_cal = st.checkbox("Apply Scorecard calibration" + (f" (slope {fitted:.2f})" if fitted else ""),
                                  key="pm_use_cal", disabled=fitted is None,
                                  help="Run the 📊 Scorecard tab for this market first. Shrinks over-confident "
                                       "probabilities by the amount the replay measured.")
        with k2:
            w = st.select_slider("Model's share of the vote when there's a price", key="pm_model_w",
                                 options=[0.2, 0.3, 0.4, 0.5, 0.6, 0.8], value=PE.MODEL_WEIGHT,
                                 format_func=lambda x: f"{x:.0%}",
                                 help="The books are usually right, so the model gets 40% of the probability and "
                                      "the no-vig market price the rest. A lean then needs +3% value at your price.")
    implied = PE.implied_team_totals(total, spread)
    if implied:
        st.caption(f"Implied team totals: **{away_name} {implied[1]:.1f}**, **{home_name} {implied[0]:.1f}**"
                   + (" — favored side runs more, underdog throws more." if PFAM == "football" else "."))
    return {"spread_home": spread, "total": total, "implied": implied, "offers": got.get("offers"),
            "slope": fitted if (use_cal and fitted) else 1.0, "model_weight": w,
            "book": None if price_book == "best" else price_book}


def render_props_team(team, opp, off_name, def_name, market, mode, tables, g):
    is_home = team == bundle["home"]
    implied = g["implied"]
    team_imp = (implied[0] if is_home else implied[1]) if implied else None
    opp_imp = (implied[1] if is_home else implied[0]) if implied else None
    spread_team = None if g["spread_home"] is None else (g["spread_home"] if is_home else -g["spread_home"])
    base_ctx = {"rest_days": _rest_days(team), "opp_rest_days": _rest_days(opp), "spread": spread_team,
                "offers": g["offers"], "slope": g["slope"], "model_weight": g["model_weight"], "book": g.get("book"),
                "news_checked": bool(st.session_state.get("pm_news_checked"))}
    key = f"pm_props_{SPORT_KEY}_{game_label}_{market}_{team}"
    st.markdown(f"#### {off_name}  vs  {def_name} defense · {market}")
    if PFAM == "football":
        mk = FP.MARKETS[market]
        roster = (PROPS.get("roster") or {}).get(team) or []
        order = [(r.get("pid") if r.get("pid") is not None else r.get("name")) for r in roster if r["slot"] in mk["slots"]]
        if not order:
            st.caption(f"No {off_name} player at the positions this market is offered for.")
            return []
        ed = _editor_values(key, order)
        ctx = dict(base_ctx, implied=team_imp,
                   prices={k: {"over": ed["Over odds"].get(k), "under": ed["Under odds"].get(k)} for k in order})
        rows = FP.player_rows(roster, team, opp, market, PROPS.get("pgames") or [], bundle.get("allowed") or {},
                              lines=ed["Line"], context=ctx, sport=SPORT_KEY)
        disp = FP.display(rows, market, FP.has_targets(PROPS.get("pgames")))
    elif PFAM == "hockey":
        rot = (PROPS.get("rotation") or {}).get(team) or {}
        goalie = HP.MARKETS[market]["role"] == "goalie"
        players = (rot.get("goalies") or [])[:2] if goalie else (rot.get("skaters") or [])
        if not players:
            st.caption("No lineup found for this team in the sample yet.")
            return []
        order = [p["pid"] for p in players]
        ed = _editor_values(key, order)
        pg = PROPS.get("pgames") or []
        ctx = dict(base_ctx, env=PE.env_factor(team_imp, HP.team_goals(pg, team)),
                   opp_env=PE.env_factor(opp_imp, HP.team_goals(pg, opp)),
                   team_games=(PROPS.get("team_games") or {}).get(team),
                   prices={k: {"over": ed["Over odds"].get(k), "under": ed["Under odds"].get(k)} for k in order})
        rows = HP.player_rows(rot, team, opp, market, pg, lines=ed["Line"], context=ctx)
        disp = HP.display(rows, market)
    else:
        rot = (PROPS.get("rotation") or {}).get(team) or []
        if not rot:
            st.caption("No rotation found for this team in the sample yet.")
            return []
        order = [r["pid"] for r in rot]
        ed = _editor_values(key, order)
        base_pg = PROPS.get("cur_pgames") or PROPS.get("pgames") or []
        ctx = dict(PPR.game_context(team, is_home, g["spread_home"], g["total"], base_ctx["rest_days"],
                                    base_ctx["opp_rest_days"], base_pg, offers=g["offers"], book=g.get("book"),
                                    news_checked=base_ctx["news_checked"], slope=g["slope"],
                                    model_weight=g["model_weight"], sport=SPORT_KEY),
                   prices={k: {"over": ed["Over odds"].get(k), "under": ed["Under odds"].get(k)} for k in order})
        rows = PPR.player_rows(rot, opp, market, tables["cur"], tables["prior"], PROPS.get("cur_pgames") or [],
                               PROPS.get("prior_pgames") or [], lines=ed["Line"], mode=mode, context=ctx)
        disp = PPR.display(rows)
    if not st.session_state.get("pm_props_edit"):
        opp_label = list(disp[0])[2] if disp else "Min"
        st.dataframe(pd.DataFrame(PE.display_compact(rows, details=bool(st.session_state.get("pm_props_details")),
                                                     opp_label=opp_label, market=market)),
                     hide_index=True, width="stretch")
        return rows
    df = pd.DataFrame(disp)
    for c in EDITABLE:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    st.data_editor(df, key=key, hide_index=True, width="stretch",
                   disabled=[c for c in df.columns if c not in EDITABLE],
                   column_config={
                       "Line": st.column_config.NumberColumn(
                           "Line ✏️", step=0.5, format="%.1f",
                           help="Your book's number. 39.5 = over 39.5; a whole number like 40 = an alt 40+ line."),
                       "Over odds": st.column_config.NumberColumn(
                           "Over odds ✏️", step=5, format="%+d", help="The over price at your book (−115, +120)."),
                       "Under odds": st.column_config.NumberColumn(
                           "Under odds ✏️", step=5, format="%+d", help="The under price at your book.")})
    return rows


def _ticket_leg(r, side, line, p, market, label):
    """One ticket leg from a props row: the chance of that side, the cushion and anything that makes it risky."""
    c = PE.cushion(r.get("projection"), line, side)
    return {"label": label, "player": r["player"], "game": game_label, "side": side, "market": market,
            "line": line, "p": p, "projection": r.get("projection"), "cushion": c,
            "warnings": PE.leg_warnings(r, side, line)}


def render_ticket(all_rows, market):
    """🎟️ The ticket builder (Oct 29): legs from ANY game on this date -- the book's line or an "N+" milestone --
    each with its chance, cushion and warnings, priced together (same-game legs move together; different games
    don't). Replaces the one-game SGP pricer."""
    tk = f"{SPORT_KEY}|{date_str}"
    legs = st.session_state.setdefault("pm_ticket", {}).setdefault(tk, [])
    n_games = len({l["game"] for l in legs})
    with st.expander(f"🎟️ Ticket builder — {len(legs)} leg{'s' if len(legs) != 1 else ''}"
                     + (f" from {n_games} game{'s' if n_games != 1 else ''}" if legs else "")):
        safe = st.toggle(f"Only suggest legs with a {PE.CUSHION_MIN:.0%}+ cushion and no warnings", value=True,
                         key="pm_tk_safe",
                         help="Cushion = how far the projection sits past the number. On Oct 28, legs with a big "
                              "cushion hit; legs within ~10% of the number were coin flips.")
        cands = {}
        for r in all_rows:
            if r.get("out") or r.get("projection") is None:
                continue
            if r.get("line") is not None and r.get("p_final") is not None:
                side = r["lean"] if r.get("lean") in ("Over", "Under") else (r.get("side") or "Over")
                p = r["p_final"] if side == "Over" else 1 - r["p_final"]
                lab = f"{r['player']} {side} {r['line']:g} {market} ({p:.0%})"
                cands[lab] = _ticket_leg(r, side, r["line"], p, market, f"{r['player']} {side} {r['line']:g} {market}")
            for n, p in PE.ladder(r, market):
                lab = f"{r['player']} {n:g}+ {market} — milestone ({p:.0%})"
                cands[lab] = _ticket_leg(r, "Over", float(n), p, market, f"{r['player']} {n:g}+ {market}")
        if safe:
            cands = {k: v for k, v in cands.items() if not v["warnings"]}
        a1, a2 = st.columns([4, 1])
        with a1:
            pick = st.multiselect("Add legs (switch markets or games and keep adding — the ticket stays)", list(cands),
                                  key=f"pm_tk_pick_{game_label}_{market}")
        with a2:
            st.write("")
            if st.button("➕ Add", key="pm_tk_add") and pick:
                have = {l["label"] for l in legs}
                legs.extend(cands[k] for k in pick if cands[k]["label"] not in have)
                st.rerun()
        if not legs:
            st.caption("Milestone legs (**N+**) are priced by the model alone — the books' milestone prices aren't "
                       "loaded. Two legs from the same game move together (two overs in a fast game hit together "
                       "more often than multiplying says); legs from different games don't.")
            return
        st.dataframe(pd.DataFrame([{
            "Leg": l["label"], "Game": l["game"], "Chance": f"{l['p']:.0%}",
            "Projection": "—" if l.get("projection") is None else f"{l['projection']:.1f}",
            "Cushion": PE.cushion_text(l.get("cushion")),
            "Warnings": " · ".join(l.get("warnings") or []) or "—"} for l in legs]), hide_index=True, width="stretch")
        risky = [l for l in legs if l.get("warnings")]
        if risky:
            st.warning(f"{len(risky)} of {len(legs)} legs carry a warning: "
                       + "; ".join(f"{l['label']} ({', '.join(l['warnings'])})" for l in risky))
        p1, p2 = st.columns([1, 3])
        with p1:
            price = st.number_input("Book's price for the ticket", value=None, step=5.0, format="%+.0f",
                                    key="pm_tk_price", help="The American odds your book offers (+1784).")
        if len(legs) == 1:
            with p2:
                st.metric("Hit chance", f"{legs[0]['p']:.1%}")
            res = None
        else:
            res = PE.sgp(legs, price)
            with p2:
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Hit chance", f"{res['p_joint']:.1%}", help="Legs from the same game move together.")
                m2.metric("If independent", f"{res['p_independent']:.1%}")
                m3.metric("Fair price", f"{res['fair']:+d}" if res["fair"] is not None else "—")
                m4.metric("EV at your price", "—" if res["ev"] is None else f"{res['ev']:+.0%}")
        if res and res["ev"] is not None:
            (st.success if res["ev"] > 0 else st.warning)(
                "Positive expected value at that price." if res["ev"] > 0 else
                "Negative expected value at that price — the book pays less than the ticket's fair price.")
        r1, r2 = st.columns([3, 1])
        with r1:
            drop = st.multiselect("Remove legs", [l["label"] for l in legs], key="pm_tk_drop")
        with r2:
            st.write("")
            if st.button("Remove", key="pm_tk_remove") and drop:
                legs[:] = [l for l in legs if l["label"] not in drop]
                st.rerun()
        if st.button("🗑️ Clear the ticket", key="pm_tk_clear"):
            legs.clear()
            st.rerun()


if tab_props is not None:
    with tab_props:
        menu, default_m, mhelp = _market_menu()
        if PFAM == "hockey":
            st.info(HP.PRIMER, icon="🏒")
        st.caption("Every player, for the market you pick. **Projection** = his recent rate × his expected "
                   + {"basketball": "minutes", "football": "volume (targets / carries / attempts)",
                      "hockey": "ice time"}.get(PFAM, "volume")
                   + " × the matchup × the game environment. Teammates ruled out hand their volume to the next men up "
                     "(**↑**). Type or load a **Line** and odds for a hit rate, a probability blended with the "
                     "books' and a lean that needs real value at your price.")
        pc1, pc2 = st.columns([1, 2])
        with pc1:
            mkey = "pm_props_market" if PFAM == "basketball" else f"pm_props_market_{PFAM}"
            market = st.selectbox("Market", list(menu), index=list(menu).index(default_m), key=mkey,
                                  format_func=lambda m: f"{m} — {mhelp[m]}" if m in mhelp else m)
        mode = "season"
        with pc2:
            if SPORT_KEY == "NBA":
                _modes = {"Blend this season + last (recommended)": "blend", "This season only": "season",
                          "Last season only": "prior"}
                mode = _modes[st.radio(
                    "Defense data", list(_modes), horizontal=True, key="pm_props_mode",
                    help="Early in the season a defense has 2–3 games. Blend starts from last season's numbers and "
                         "moves toward this season's as games pile up (10 games ≈ half weight).")]
            elif SPORT_KEY == "NCAAMB":
                st.caption("College basketball: only these two teams' games are loaded, so there's no league average "
                           "for the matchup factor — projections are form, minutes, rest and the game lines.")
        # Everything below the market picker lives in ONE slot that is emptied the moment the script gets here, so
        # switching markets never leaves the previous market's tables on screen while the new lines load.
        _body = st.empty()
        _body.empty()
        with _body.container():
            g = render_game_context(market)
            tables = {}
            if PFAM == "basketball":
                tables = PPR.market_tables(PROPS.get("cur_pgames") or [], PROPS.get("prior_pgames"), market, SPORT_KEY)
                if not g["implied"]:
                    pace = PPR.pace_flag(PROPS.get("cur_pgames") or PROPS.get("pgames"), bundle["home"], bundle["away"])
                    if pace:
                        msg = (f"{pace['label']}: these two teams project to about **{pace['projected_total']:.0f}** total "
                               f"points vs a {pace['league_total']:.0f} average ({pace['pct']:+.0f}%).")
                        (st.warning if pace["label"] != "Normal pace" else st.caption)(
                            msg + (" Load or type the game total to fold this into every projection."
                                   if abs(pace["pct"]) >= PPR.PACE_FLAG_PCT else ""))
            v1, v2 = st.columns(2)
            with v1:
                st.toggle("✏️ Enter my own lines & prices", key="pm_props_edit",
                          help="Switches the tables to edit mode: type your book's line and odds for any player. What you "
                               "type is kept when you switch back.")
            with v2:
                st.toggle("Show the model's working", key="pm_props_details",
                          help="Adds minutes / volume, recent form, the matchup and the game-environment adjustment.")
            st.toggle("📰 I've checked the news for the ⚠️ market-disagreement plays", key="pm_news_checked",
                      help="When the books' line is far from the model's projection (20%+ and more than his usual "
                           "game-to-game swing), the market usually knows something — a minutes limit, a role change, "
                           "an injury. Those plays get no lean until you've checked. Even then the model only gets "
                           "20% of the vote on them.")
            top = st.container()
            away_rows = render_props_team(bundle["away"], bundle["home"], away_name, home_name, market, mode, tables, g)
            st.divider()
            home_rows = render_props_team(bundle["home"], bundle["away"], home_name, away_name, market, mode, tables, g)
            all_rows = away_rows + home_rows
            with top:
                team_of = {r["pid"]: away_name for r in away_rows}
                team_of.update({r["pid"]: home_name for r in home_rows})
                reads = PE.best_reads(all_rows, team_of)
                st.markdown(f"#### 🔥 Best {market} reads in this game")
                if reads:
                    st.dataframe(pd.DataFrame(reads), hide_index=True, width="stretch")
                gaps = PE.market_gaps(all_rows, team_of)
                if gaps:
                    st.markdown("#### ⚠️ Model vs the books — check before betting")
                    st.dataframe(pd.DataFrame(gaps), hide_index=True, width="stretch")
                    st.caption("These lines sit far from the model's projection. Usually the books know something "
                               "the box scores don't (a minutes limit, a returning starter, an injury). Check the "
                               "injury report and lineup news; if nothing explains it, the 📰 toggle above shows "
                               "leans — with the market getting 80% of the vote. Bets logged on these are tagged "
                               "**market-gap**, and the Scorecard tracks who turns out right.")
                if not reads and not any(r.get("line") is not None for r in all_rows):
                    st.info("No lines posted for this market yet — books usually post player props the afternoon of the "
                            "game. The projections below are ready; picks appear once lines are up (or type your own).",
                            icon="🕐")
                elif not reads and not gaps:
                    st.caption("No side clears the bar for value in this market right now — try another market.")
            st.caption("**Pick** = the side the model favors; **Chance** = how likely it is; **Lean** = 🟢/🔴 only when "
                       "that side has **+3% value at the price shown** (no price: the projection 5%+ past the line and "
                       "55%+ to hit). **Cushion** = how far the projection sits past the line (⚠️ under 15%: close to a coin "
                       "flip — keep those out of parlays). **Milestones** = the model's chance of each **N+** rung "
                       "around his projection. Low counts (rebounds, assists, blocks, steals, "
                       "receptions, shots, goals) use count odds, not a bell curve. **Notes** flag back-to-backs, blowout "
                       "risk, game script and next-man-up bumps. Overtime isn't modelled.")
            render_ticket(all_rows, market)
            log_fn = {"football": FP.plays_for_log, "hockey": HP.plays_for_log}.get(PFAM, PPR.plays_for_log)
            plays = log_fn(all_rows, market, f"{away_name} @ {home_name}")
            if plays:
                quick_log.render_quick_log(plays, date_str, SPORT_KEY, key_prefix=f"pm_props_{game_label}_{market}")


def render_logged_props(markets) -> None:
    """Owner-only: how the props you actually logged have done -- record, calibration and closing-line value."""
    try:
        if st.secrets.get("AUDIENCE", "owner") != "owner":
            return
    except Exception:                                              # noqa: BLE001 — no secrets file: local/dev
        pass
    st.markdown("#### 📒 Your logged props")
    if not st.button("Load my logged props", key="pm_sc_logged"):
        st.caption("Your real bets in these markets from the Bet Log: record, profit, calibration and closing-line "
                   "value (hand-typed prices count).")
        return
    import betlog as B
    try:
        bets = [b for b in B.list_bets(sport=SPORT_KEY) if b.get("market") in set(markets)]
    except Exception as exc:                                       # noqa: BLE001
        st.warning(f"Couldn't read the Bet Log ({type(exc).__name__}).")
        return
    if not bets:
        st.caption("No logged bets in these markets yet.")
        return
    summ, clv = B.summary(bets), B.real_price_clv_summary(bets)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Record", f"{summ.get('wins', 0)}-{summ.get('losses', 0)}")
    m2.metric("Profit", f"${summ.get('profit', 0):,.2f}")
    m3.metric("Avg CLV", "—" if clv.get("avg_clv") is None else f"{clv['avg_clv']:+.1f}%",
              help=f"{clv.get('n_book', 0)} book-captured + {clv.get('n_manual', 0)} hand-typed prices.")
    m4.metric("Beat the close", "—" if clv.get("beat_close_rate") is None else f"{clv['beat_close_rate']:.0f}%")
    gap_bets = [b for b in bets if (b.get("notes") or "") == PE.GAP_TAG]
    if gap_bets:
        rest = [b for b in bets if b not in gap_bets]
        rows_ = []
        for label, grp in (("⚠️ Market-gap plays", gap_bets), ("Everything else", rest)):
            sm, cl = B.summary(grp), B.real_price_clv_summary(grp)
            rows_.append({"Bets": label, "Record": f"{sm.get('wins', 0)}-{sm.get('losses', 0)}",
                          "Profit": f"${sm.get('profit', 0):,.2f}",
                          "ROI": "—" if sm.get("roi") is None else f"{sm['roi']:+.1f}%",
                          "Avg CLV": "—" if cl.get("avg_clv") is None else f"{cl['avg_clv']:+.1f}%"})
        st.markdown("**Who's been right when the model and the books disagree?**")
        st.dataframe(pd.DataFrame(rows_), hide_index=True, width="stretch")
        st.caption("If market-gap plays keep losing (or closing worse than you bet them), the books knew something — "
                   "keep skipping them. If they win and beat the close, the model is spotting real mispricings.")
    cal = B.calibration(bets)
    if cal:
        st.dataframe(pd.DataFrame([{"Model said": f"{c['lo']:.0%}–{c['hi']:.0%}", "Avg model": f"{c['predicted']:.0%}",
                                    "Actually hit": f"{c['actual']:.0%}", "Bets": c["n"]} for c in cal]),
                     hide_index=True, width="stretch")


if tab_score is not None:
    with tab_score:
        menu, default_m, _ = _market_menu()
        st.caption("Replays the games already loaded for this page: every player-game is predicted **using only the "
                   "games before it**, then compared with what happened — against his plain last-5 average and a "
                   "proxy line (his average to that point; historical book lines aren't stored). Closing-line value "
                   "on your real bets is the other half of the proof — see the bottom of this tab.")
        c1, c2 = st.columns([1, 2])
        with c1:
            sc_market = st.selectbox("Market to grade", list(menu), index=list(menu).index(default_m),
                                     key=f"pm_sc_market_{PFAM}")
        samples = {}
        if PFAM == "basketball":
            if PROPS.get("cur_pgames"):
                samples["This season"] = PROPS["cur_pgames"]
            if PROPS.get("prior_pgames"):
                samples["End of last season"] = PROPS["prior_pgames"]
        if not samples:
            samples["Loaded games"] = PROPS.get("pgames") or []
        with c2:
            which = st.radio("Games to replay", list(samples), horizontal=True, key="pm_sc_sample")
        store = st.session_state.setdefault("pm_sc", {})
        skey = f"{SPORT_KEY}|{date_str}|{game_label}|{sc_market}|{which}"
        if st.button("▶️ Run the Scorecard", key="pm_sc_run", type="primary"):
            with st.spinner("Replaying every player-game..."):
                if PFAM == "basketball":
                    store[skey] = BT.backtest_basketball(samples[which], SPORT_KEY, sc_market)
                elif PFAM == "football":
                    store[skey] = BT.backtest_football(samples[which], SPORT_KEY, sc_market)
                else:
                    store[skey] = BT.backtest_hockey(samples[which], sc_market)
        card = store.get(skey)
        if card is None:
            st.caption("Press **Run the Scorecard** — it takes a few seconds.")
        elif not card.get("n"):
            st.info("Not enough games in this sample to grade the model yet (each player needs a few earlier games).")
        else:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Graded player-games", f"{card['n']:,}",
                      help=(f"{card['dates'][0]} → {card['dates'][1]}" if card.get("dates") else None))
            m2.metric("Projection miss (model)", f"{card['mae_model']:.2f}",
                      delta=f"{-card['mae_gain_pct']:.1f}% vs last-5 avg" if card.get("mae_gain_pct") is not None else None,
                      delta_color="inverse")
            m3.metric("Lean hit rate", "—" if card.get("lean_rate") is None else f"{card['lean_rate']:.0%}",
                      help=f"{card['lean_hits']}/{card['lean_n']} leans vs the proxy line. 52.4% breaks even at -110.")
            m4.metric("Calibration slope", "—" if card.get("slope") is None else f"{card['slope']:.2f}",
                      help="1.00 = when it says 60% it hits 60%. Below 1 = over-confident.")
            for v in BT.verdict(card):
                st.markdown(f"- {v}")
            if card.get("buckets"):
                st.dataframe(pd.DataFrame([{"Model said": f"{b['lo']:.0%}–{b['hi']:.0%}",
                                            "Avg model": f"{b['predicted']:.0%}", "Actually hit": f"{b['actual']:.0%}",
                                            "Player-games": b["n"]} for b in card["buckets"]]),
                             hide_index=True, width="stretch")
            if card.get("slope") is not None:
                if st.button(f"Use this calibration (slope {card['slope']:.2f}) on the Player props tab",
                             key="pm_sc_apply"):
                    st.session_state.setdefault("pm_slope", {})[(SPORT_KEY, sc_market)] = card["slope"]
                    st.success("Saved for this session — tick **Apply Scorecard calibration** on the Player props tab.")
        st.divider()
        render_logged_props(list(menu))

if tab_pos is not None:
    with tab_pos:
        st.caption("1 = the defense that allows the MOST to that slot (softest). Soft = top third, Tough = bottom third. "
                   + ("A slot is the player used most there that game (running backs by carries, receivers by targets), "
                      "so WR1 is usage, not just the depth-chart label." if FAMILY == "football" else
                      "Guards / Forwards / Centers use each player's ESPN position; the numbers are the whole group's totals, and "
                      "every rotation player (10+ min) gets his own row against his group. **Model matchup** is the same number "
                      "the Player props tab uses: these raw numbers adjusted for the small sample and blended with last "
                      "season."
                      + (" Every rotation player, with his own projection, is on the **🎯 Player props** tab." if HAS_PROPS else "")))
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
