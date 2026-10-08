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
import position_data as PD
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


with tab_pos:
    st.caption("1 = the defense that allows the MOST to that slot (softest). Soft = top third, Tough = bottom third. "
               + ("A slot is the player used most there that game (running backs by carries, receivers by targets), "
                  "so WR1 is usage, not just the depth-chart label." if FAMILY == "football" else
                  "Guards / Forwards / Centers use each player's ESPN position; the numbers are the whole group's totals."))
    render_side(bundle["away_off"], away_name, home_name)
    st.divider()
    render_side(bundle["home_off"], home_name, away_name)

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
