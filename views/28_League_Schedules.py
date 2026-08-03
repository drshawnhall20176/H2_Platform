"""
League Schedules — a real, standalone season/week (or day-by-day) schedule browser for
whichever sport is currently active. Its own process, on purpose, per direct request: this page
reads real schedule data and displays it, full stop. It never writes anything to session_state
beyond the sport selector (the SAME session_state["sport"] key Home.py's own tabs already use --
switching sport here changes it everywhere else too, by design, not a page-local copy of it) and
its own local widget state. Never touches best_bets_data/build_mlb_board or any sport's own
build_best_bets, never feeds a projection, a conviction, a grade, or the calibration feedback
loop. If this page's own schedule fetch fails or a sport has no schedule source at all, every
other page keeps working exactly as it did before this page existed.

SPORT TABS, REUSING HOME.PY'S OWN REAL PATTERN, NOT A SEPARATE ONE -- added directly on request.
Same st.session_state["sport"] key, same button-row layout, so picking a sport here and picking
one on Home.py (or the sidebar) are the exact same action, never two competing sources of truth
for "which sport is active."

CONFERENCE/DIVISION GROUPING, REUSING schedule_board.py + components.todays_schedule_board --
added directly on request, NOT reimplemented here. Those two already do this correctly (real
per-sport conference/division reference tables, real lineup-confirmation status for MLB, a real
"Other" bucket for any team missing from the reference data rather than silently dropped) for
MLB/NBA/WNBA/NFL/NCAAF (schedule_board.SUPPORTED_SPORTS) -- this page's own earlier, simpler
flat-list rendering is kept ONLY as the honest fallback for a sport outside that scope (NCAAMB:
350+ Division I teams, no reference table sourced yet; UFC: individual bouts, not team matchups,
already served by its own UFC Fight Card page).

TWO GENUINELY DIFFERENT REAL SHAPES, HANDLED EXPLICITLY, NOT PAPERED OVER: NFL/NCAAF's own
get_schedule(season) returns a WHOLE SEASON at once (these sports play once a week, so "browse
by week" is the real, natural unit) -- schedule_board.todays_schedule is scoped to ONE calendar
date, so a selected week's real games (which span several real dates -- Thu/Sun/Mon for NFL) are
fetched one date-call per real date in that week (each already cached at its own 300s TTL) and
merged before rendering, not reimplemented as a new fetch path. MLB/WNBA/NBA's own
get_schedule(date_str) returns ONE DAY at a time, matching schedule_board's own contract exactly,
no merge needed.
"""

import streamlit as st
import components as C
from datetime import datetime
import pytz

import sports
import schedule_board as SB

eastern = pytz.timezone("US/Eastern")
game_dt = sports.game_dt

C.base_css()
C.hero_banner("📅", "League Schedules", "Real season schedules, browsed by whichever league you pick below")

# ----------------------------------------------------------------- sport tabs (Home.py's own pattern)
st.divider()
live = sports.enabled_sports()
keys = [s.key for s in live]
current = st.session_state.get("sport", sports.DEFAULT_SPORT)
if current not in keys:
    current = keys[0]

C.section_header("🏟", "Select League")
cols = st.columns(len(keys) + len([s for s in sports.REGISTRY.values() if not s.enabled]))
for i, s in enumerate(live):
    with cols[i]:
        if st.button(f"{s.icon} {s.label}", key=f"league_sched_sport_btn_{s.key}",
                    type="primary" if current == s.key else "secondary", width="stretch"):
            st.session_state["sport"] = s.key
            st.rerun()
coming = [s for s in sports.REGISTRY.values() if not s.enabled]
for i, s in enumerate(coming):
    with cols[len(live) + i]:
        st.button(f"{s.icon} {s.label}\n*(coming soon)*", key=f"league_sched_sport_btn_coming_{s.key}",
                 disabled=True, width="stretch")

_active = sports.REGISTRY.get(current)
if not _active:
    st.stop()
E = _active.engine
st.divider()

if not hasattr(E, "get_schedule"):
    st.info(f"No real schedule data source is wired up for {_active.label} yet."
           + (" Head to **UFC Fight Card** for tonight's real card." if _active.key == "UFC" else ""))
    st.stop()

WEEKLY_SPORTS = {"NFL", "NCAAF"}   # see this file's own module docstring for the real reasoning


# ----------------------------------------------------------------- fallback flat renderer (NCAAMB etc.)
def _team(g: dict, side: str) -> str:
    return g.get(f"{side}_name") or g.get(f"{side}_team") or "?"


def _score(g: dict, side: str):
    return g.get(f"{side}_score") if g.get(f"{side}_score") is not None else g.get(f"{side}_points")


def _render_game_flat(g: dict):
    home, away = _team(g, "home"), _team(g, "away")
    hs, as_ = _score(g, "home"), _score(g, "away")
    raw_date = g.get("game_date") or g.get("start_date")
    dt = game_dt(raw_date)
    when = dt.strftime("%a %-I:%M %p ET") if dt else (raw_date or "TBD")
    status = g.get("status") or g.get("status_detail") or ""
    line = f"**{away} @ {home}**  ·  {when}"
    if hs is not None and as_ is not None:
        line += f"  ·  {away} {as_:g} – {home} {hs:g}"
    if status:
        line += f"  ·  _{status}_"
    st.markdown(line)


def _merge_schedule_results(results: list) -> dict:
    """Merges several schedule_board.todays_schedule() results (one per real calendar date
    within a selected week) into one combined grouped/other/has_divisions structure -- needed
    because todays_schedule() itself is scoped to ONE date, but an NFL/NCAAF week spans several
    real ones. Reuses todays_schedule() completely as-is per date; this only combines the
    already-correct per-date results, no grouping logic reimplemented here."""
    merged_grouped: dict = {}
    merged_other: list = []
    has_divisions = False
    for r in results:
        if r is None:
            continue
        has_divisions = has_divisions or r["has_divisions"]
        for conf, divs in r["grouped"].items():
            merged_grouped.setdefault(conf, {})
            for div, gs in divs.items():
                merged_grouped[conf].setdefault(div, []).extend(gs)
        merged_other.extend(r["other"])
    return {"grouped": merged_grouped, "other": merged_other, "has_divisions": has_divisions}


rich = current in SB.SUPPORTED_SPORTS

if current in WEEKLY_SPORTS:
    season = st.number_input("Season", min_value=2015, max_value=2100, value=datetime.now().year, step=1)

    @st.cache_data(ttl=3600, show_spinner="Loading season schedule...")
    def load_schedule(season_inner: int):
        return E.get_schedule(int(season_inner))

    schedule = load_schedule(season)
    if not schedule:
        st.info(f"No real schedule data available for the {int(season)} {_active.label} season yet.")
        st.stop()

    weeks = sorted({g["week"] for g in schedule if g.get("week") is not None})
    if not weeks:
        st.info("Real schedule data loaded, but no week numbers were present on it.")
        st.stop()

    today_str = datetime.now(eastern).strftime("%Y-%m-%d")
    default_week = E._resolve_week(schedule, today_str) if hasattr(E, "_resolve_week") else None
    default_idx = weeks.index(default_week) if default_week in weeks else 0
    week = st.selectbox("Week", weeks, index=default_idx)

    games = [g for g in schedule if g.get("week") == week]
    date_field = "game_date" if current == "NFL" else "start_date"   # real, confirmed per-sport field name
    if current == "NFL":
        real_dates = sorted({g[date_field] for g in games if g.get(date_field)})   # NFL's own field is date-only already
    else:
        real_dates = sorted({dt.strftime("%Y-%m-%d") for g in games if (dt := game_dt(g.get(date_field)))})

    if rich and real_dates:
        with st.spinner(f"Loading Week {week}..."):
            results = [SB.todays_schedule(current, d) for d in real_dates]
        merged = _merge_schedule_results(results)
        C.todays_schedule_board(merged, _active.icon, _active.label,
                                heading=f"Week {week}, {int(season)} — {_active.label} Schedule")
    else:
        games.sort(key=lambda g: g.get("game_date") or g.get("start_date") or "")
        st.caption(f"{len(games)} game(s) — Week {week}, {int(season)}")
        for g in games:
            _render_game_flat(g)

else:
    target = st.date_input("Date", datetime.now(eastern))
    date_str = target.strftime("%Y-%m-%d")

    if rich:
        with st.spinner("Loading schedule..."):
            result = SB.todays_schedule(current, date_str)
        C.todays_schedule_board(result, _active.icon, _active.label,
                                heading=f"{date_str} — {_active.label} Schedule")
    else:
        @st.cache_data(ttl=300, show_spinner="Loading schedule...")
        def load_schedule_for_date(date_str_inner: str):
            return E.get_schedule(date_str_inner)

        games = load_schedule_for_date(date_str)
        if not games:
            st.info(f"No {_active.label} games scheduled for {date_str}.")
            st.stop()
        games.sort(key=lambda g: g.get("game_date") or "")
        st.caption(f"{len(games)} game(s) — {date_str}")
        for g in games:
            _render_game_flat(g)

st.divider()
st.caption("Read-only schedule data — this page doesn't feed any projection, pick, grade, or "
          "the calibration feedback loop. It's its own process, not part of the model pipeline.")
