"""
League Schedules — a real, standalone season/week (or day-by-day) schedule browser for
whichever sport is currently active, reusing the SAME sport selector every other page already
shares (sports.active()).

ITS OWN PROCESS, ON PURPOSE, PER DIRECT REQUEST: this page reads real schedule data and displays
it. Full stop. It never writes anything to session_state beyond its own local widget state
(Streamlit's own automatic per-widget keys), never touches best_bets_data/build_mlb_board or any
sport's own build_best_bets, never feeds a projection, a conviction, a grade, or the calibration
feedback loop. Nothing on this page can affect what any other page shows. If this page's own
schedule fetch fails or a sport has no schedule function at all, every other page keeps working
exactly as it did before this page existed.

TWO GENUINELY DIFFERENT REAL SHAPES, HANDLED EXPLICITLY, NOT PAPERED OVER: NFL/NCAAF's own
get_schedule(season) returns a WHOLE SEASON at once (these sports play once a week, so "browse
by week" is the real, natural unit); MLB/WNBA/NBA/NCAAMB's own get_schedule(date_str) returns ONE
DAY at a time (these sports play daily, so "browse by date" is the real, natural unit). WEEKLY_
SPORTS below is a real, small, explicit set precisely because this genuinely doesn't generalize
from one shared code path -- forcing both shapes through the same UI would mean either a fake
"week" concept for a daily sport or a fake "date" concept for a weekly one.

UFC (and any other sport with no real get_schedule at all) is left out on purpose, not a bug --
UFC Fight Card already exists and already serves this exact real purpose for UFC specifically;
duplicating it here would just be a second, competing "what's on" page for the same sport.
"""

import streamlit as st
import components as C
from datetime import datetime
import pytz

import sports

_active = sports.active()
E = _active.engine
eastern = pytz.timezone("US/Eastern")
game_dt = sports.game_dt

C.base_css()
C.page_header("📅", "League Schedules",
             f"Real season schedule, browse by {'week' if _active.key in ('NFL', 'NCAAF') else 'date'} "
             f"— {_active.icon} {_active.label}")

if not hasattr(E, "get_schedule"):
    st.info(f"No real schedule data source is wired up for {_active.label} yet. "
            + ("Head to **UFC Fight Card** for tonight's real card." if _active.key == "UFC" else ""))
    st.stop()

WEEKLY_SPORTS = {"NFL", "NCAAF"}   # see this file's own module docstring for the real reasoning


def _team(g: dict, side: str) -> str:
    """side: 'home' or 'away'. Tries every real field name this platform's own sport engines
    actually use across MLB/WNBA/NBA/NCAAMB/NFL/NCAAF (confirmed by reading each one directly,
    not guessed) -- home_name/away_name (MLB, WNBA, NBA, NCAAMB, NFL) or home_team/away_team
    (NFL/NCAAF's own alternate naming), falling back to a real, honest "?" rather than crashing
    on a field this specific engine doesn't happen to carry."""
    return g.get(f"{side}_name") or g.get(f"{side}_team") or "?"


def _score(g: dict, side: str):
    """None (not 0) when no real score exists yet -- MLB carries home_score/away_score directly
    on get_schedule's own output; NFL/NCAAF carry the same under home_score/away_score too;
    WNBA/NBA/NCAAMB's own get_schedule doesn't include a score field at all (confirmed directly
    -- it was built for pre-game slate assembly, not a post-game recap), so this is honestly
    None for those, not a fabricated 0."""
    return g.get(f"{side}_score") if g.get(f"{side}_score") is not None else g.get(f"{side}_points")


def _render_game(g: dict):
    home, away = _team(g, "home"), _team(g, "away")
    hs, as_ = _score(g, "home"), _score(g, "away")
    # game_date (MLB/WNBA/NBA/NCAAMB/NFL) or start_date (NCAAF's own real field name, confirmed
    # directly against ncaaf_data.py's own schedule row shape -- NOT game_date for this sport).
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


if _active.key in WEEKLY_SPORTS:
    season = st.number_input("Season", min_value=2015, max_value=2100,
                             value=datetime.now().year, step=1)

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

    # A sensible DEFAULT week (today's real, current week), not always week 1 -- reuses this
    # sport's own already-tested _resolve_week (the exact function NFL Matchup Lab's own week
    # picker already calls), same real "what week is today" logic, not reinvented here.
    today_str = datetime.now(eastern).strftime("%Y-%m-%d")
    default_week = E._resolve_week(schedule, today_str) if hasattr(E, "_resolve_week") else None
    default_idx = weeks.index(default_week) if default_week in weeks else 0
    week = st.selectbox("Week", weeks, index=default_idx)

    games = [g for g in schedule if g.get("week") == week]
    games.sort(key=lambda g: g.get("game_date") or g.get("start_date") or "")
    st.caption(f"{len(games)} game(s) — Week {week}, {int(season)}")
    for g in games:
        _render_game(g)

else:
    target = st.date_input("Date", datetime.now(eastern))
    date_str = target.strftime("%Y-%m-%d")

    @st.cache_data(ttl=300, show_spinner="Loading schedule...")
    def load_schedule_for_date(date_str_inner: str):
        return E.get_schedule(date_str_inner)

    games = load_schedule_for_date(date_str)
    if not games:
        st.info(f"No {_active.label} games scheduled for {date_str}.")
        st.stop()

    games.sort(key=lambda g: g.get("game_date") or g.get("start_date") or "")
    st.caption(f"{len(games)} game(s) — {date_str}")
    for g in games:
        _render_game(g)

st.divider()
st.caption("Read-only schedule data — this page doesn't feed any projection, pick, grade, or "
          "the calibration feedback loop. It's its own process, not part of the model pipeline.")
