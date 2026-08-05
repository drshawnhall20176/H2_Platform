"""
schedule_board.py — "Today's Schedule" data layer for Home.py: today's games for the active
sport, grouped by conference (and division where that data exists), sorted chronologically by
real start time.

DELIBERATELY BUILT ON EACH ENGINE'S OWN get_schedule(), NOT build_slate() -- get_schedule is the
lightweight, games-only fetch every engine already has (team names, start time, venue), completely
separate from the heavy per-player projection pipeline build_slate runs. A schedule display has no
reason to wait on player-level data it isn't showing.

SCOPE: MLB, NBA, WNBA, NFL, NCAAF, NCAAMB. UFC (individual bouts, not team matchups -- UFC Fight
Card already IS its own schedule) is deliberately not covered here -- see league_structure.py's
own docstring. Home.py's own caller is responsible for simply not rendering this section for that
one sport, the same "hidden entirely, not shown broken" posture the rest of this platform already
uses for sport-gated content.

NCAAMB, ADDED DIRECTLY ON REQUEST, HONESTLY, NOT WITH A FABRICATED CONFERENCE TABLE: 350+
Division I teams across dozens of conferences is real, substantial reference data this platform
doesn't have sourced and verified -- typing one by hand here would risk silently mislabeling real
teams, worse than not grouping them at all. _conference_lookup's own existing fallback (an empty
lookup, has_divisions=False) already sends every NCAAMB game into group_games' own "Other" bucket
-- which was ALREADY built, tested, and gets the exact same real visual treatment (colored box,
grid-aligned rows, status badges) as a real conference section, just without a conference/division
sub-grouping. So NCAAMB gets the SAME fancy rendering everything else does, honestly labeled as
missing conference data (the "Other" bucket's own existing caption already says so), rather than
either a fabricated/risky mapping or staying on a visually plainer fallback page. Uses the exact
same ESPN scoreboard shape/fetch as NBA/WNBA (_basketball_games, confirmed field-for-field against
ncaamb_engine.get_schedule's own real output) -- no new fetch logic needed for this sport at all.

DATE HANDLING, PER SPORT -- real, confirmed differences, not a uniform assumption:
  - MLB / NBA / WNBA: game_date is a full ISO-UTC timestamp -- run through sports.game_dt (the
    platform's own shared UTC->US/Eastern conversion) for both the date filter and the
    chronological sort, same real fix odds_api.py/ufc_engine.py's own _eastern_date_str already
    established (a late-night ET game can roll to the next UTC calendar day; a raw string-prefix
    comparison would silently drop it from "today").
  - NCAAF: start_date is also a full ISO-UTC timestamp (confirmed against ncaaf_data.py's own
    _SCHEDULE_COLUMNS, which carries a separate start_time_tbd flag alongside it -- that flag only
    makes sense if start_date normally carries a real time). Same game_dt handling as above.
  - NFL: nflreadpy's own "gameday" field (this engine's game_date) is DATE ONLY, no time-of-day --
    confirmed by what nfl_engine.get_schedule actually extracts today. Running a bare date string
    through game_dt would silently do the wrong thing (Python's fromisoformat treats a date-only
    string as a NAIVE local midnight, then .astimezone() offsets it by the SERVER's own timezone,
    not a real Eastern conversion) -- compared directly as a date string instead, no conversion.
    Real consequence, stated honestly: NFL games on the same date can't be chronologically sorted
    by real kickoff time with what this engine currently captures -- they fall back to a stable
    alphabetical-by-away-team order and display as "Time TBD" rather than fabricate a kickoff.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import streamlit as st

import league_structure as LS
import sports

# Sports this section covers -- see module docstring for why UFC is excluded and NCAAMB isn't.
SUPPORTED_SPORTS = {"MLB", "NBA", "WNBA", "NFL", "NCAAF", "NCAAMB"}


def _categorize_status(raw_text: Optional[str], espn_state: Optional[str] = None) -> str:
    """Maps a sport's own raw status text (MLB's detailedState: "Scheduled", "In Progress",
    "Final", "Postponed", "Delayed Start", "Suspended", "Cancelled", etc.) and/or ESPN's coarse
    state (pre/in/post, for NBA/WNBA) into ONE of this platform's own 5 categories: scheduled,
    delayed, canceled, in-progress, finished.

    TEXT CHECKED FIRST, REGARDLESS OF STATE -- a real, deliberate ordering: ESPN can report
    state="in" for a game that's actually paused for a rain delay (the clock stops, state doesn't
    change), and MLB's own "Suspended"/"Postponed" don't map cleanly onto pre/in/post at all.
    Keyword-matching the human-readable text first catches these real cases regardless of which
    coarse bucket the source system itself puts them in; the state fallback below only fires when
    the text itself doesn't say anything more specific (or is missing entirely, e.g. NFL/NCAAF's
    derived-only status -- see their own callers for why those two sports only ever produce
    "scheduled" or "finished").

    Never returns anything outside the 5 real categories, and always returns SOMETHING -- an
    unrecognized/missing status honestly defaults to "scheduled" (a real game the platform simply
    doesn't have detail on yet is closer to "hasn't started" than any of the other 4 for display
    purposes), never a blank or a crash."""
    s = (raw_text or "").lower()
    if "cancel" in s:
        return "canceled"
    if "postpon" in s or "delay" in s or "suspend" in s:
        return "delayed"
    if "final" in s or "game over" in s or ("complet" in s and "incomplet" not in s):
        return "finished"
    if "progress" in s:
        return "in-progress"
    if espn_state == "post":
        return "finished"
    if espn_state == "in":
        return "in-progress"
    return "scheduled"


def _mlb_games(date_str: str) -> List[Dict[str, Any]]:
    import mlb_engine as E
    out = []
    for g in E.get_schedule(date_str):
        dt = sports.game_dt(g.get("game_date"))
        if dt is None or dt.strftime("%Y-%m-%d") != date_str:
            continue
        # MLB's own official static logo CDN, keyed by the real numeric team ID the Stats API
        # already returns on every schedule row (home_id/away_id) -- a real, confirmed, widely-
        # used pattern (mlbstatic.com/team-logos/{id}.svg), not a guessed URL. None-safe: a
        # missing id just means no logo, never a crash.
        home_id, away_id = g.get("home_id"), g.get("away_id")
        # Real lineup-confirmation status per side -- see mlb_engine.get_lineup_status's own
        # docstring. One extra live fetch per game; safe here specifically because the whole
        # todays_schedule() result is cached below (see that function's own comment).
        game_pk = g.get("gamePk")
        home_confirmed = away_confirmed = None
        if game_pk and home_id and away_id:
            home_confirmed, away_confirmed = E.get_lineup_status(game_pk, home_id, away_id)
        out.append({
            "home": g.get("home_name"), "away": g.get("away_name"),
            "home_logo": f"https://www.mlbstatic.com/team-logos/{home_id}.svg" if home_id else None,
            "away_logo": f"https://www.mlbstatic.com/team-logos/{away_id}.svg" if away_id else None,
            "dt": dt, "time_known": True, "venue": g.get("venue_name"),
            "status": _categorize_status(g.get("status")),
            "home_lineup_confirmed": home_confirmed, "away_lineup_confirmed": away_confirmed,
        })
    return out


def _basketball_games(date_str: str, engine_module: str) -> List[Dict[str, Any]]:
    """Shared by NBA and WNBA -- identical ESPN scoreboard shape, see league_structure.py's own
    note on why these are keyed by full display name rather than a guessed abbreviation."""
    E = __import__(engine_module)
    out = []
    for g in E.get_schedule(date_str):
        dt = sports.game_dt(g.get("game_date"))
        if dt is None or dt.strftime("%Y-%m-%d") != date_str:
            continue
        # Real logo URL ESPN's own scoreboard response already carries -- see nba_engine.py/
        # wnba_engine.py's own get_schedule for where this is captured. Never a guess.
        out.append({"home": g.get("home_name"), "away": g.get("away_name"),
                    "home_logo": g.get("home_logo"), "away_logo": g.get("away_logo"),
                    "dt": dt, "time_known": True, "venue": None,
                    "status": _categorize_status(g.get("status_detail"), g.get("status_state")),
                    # No confirmed lineup-status signal for these two sports yet -- see
                    # schedule_board.py's own module-level notes on scope. None (not False),
                    # so the renderer knows to skip the bubble entirely rather than show a
                    # red "not confirmed" that isn't a real, checked answer.
                    "home_lineup_confirmed": None, "away_lineup_confirmed": None})
    return out


def _espn_cdn_logo(sport_slug: str, abbr: Optional[str]) -> Optional[str]:
    """ESPN's own well-known team-logo CDN pattern (confirmed: a real logo URL of exactly this
    shape appears directly inside ESPN's own API responses for other sports, e.g.
    "https://a.espncdn.com/i/teamlogos/nba/500/cle.png") -- used here for NFL specifically only
    because nfl_engine.get_schedule has no logo field of its own to capture (nflreadpy's schedule
    data doesn't carry one), unlike NBA/WNBA above where the real URL is captured directly.
    REAL, STATED RISK: a small number of abbreviations could differ from ESPN's own file-naming
    convention (not verified live from this sandbox, no network path to espncdn.com here) -- see
    components.py's own onerror handling on the <img> tag, which hides a wrong guess cleanly
    instead of showing a broken-image icon."""
    if not abbr:
        return None
    return f"https://a.espncdn.com/i/teamlogos/{sport_slug}/500/{abbr.lower()}.png"


def _nfl_games(date_str: str) -> List[Dict[str, Any]]:
    import nfl_engine as E
    season = E._infer_season(date_str)
    if season is None:
        return []
    schedule = E.get_schedule(season)
    week = E._resolve_week(schedule, date_str)
    if week is None:
        return []
    out = []
    for g in E.games_for_week(schedule, week):
        # Direct string comparison, deliberately -- see module docstring on why NFL's date-only
        # game_date can't safely go through game_dt the way the timestamp-based sports do.
        if g.get("game_date") != date_str:
            continue
        out.append({"home": g.get("home_team"), "away": g.get("away_team"),
                    "home_logo": _espn_cdn_logo("nfl", g.get("home_team")),
                    "away_logo": _espn_cdn_logo("nfl", g.get("away_team")),
                    "dt": None, "time_known": False, "venue": None,
                    # date_str kept as the raw, real, already-filtered-on YYYY-MM-DD string --
                    # A REAL, CONFIRMED FIX, not the original design: this used to be computed
                    # (for the filter above) and then discarded, leaving the display layer with
                    # NOTHING date-related to show for NFL (dt is always None here, by design,
                    # since NFL's date-only field can't safely go through game_dt -- see module
                    # docstring). _schedule_game_row falls back to this real date when dt itself
                    # isn't available, rather than showing a bare, uninformative "Time TBD" for
                    # every single NFL game regardless of which real day it's actually on.
                    "date_str": g.get("game_date"),
                    # HONEST LIMITATION, not a gap in this function's own logic: nflreadpy's
                    # schedule data isn't a live feed, so "delayed"/"in-progress"/"canceled"
                    # genuinely can't be told apart here -- only whether a real final score has
                    # posted yet. Real score presence (not just "did the scheduled time pass")
                    # is the honest signal, since a postponed/delayed game's own start time
                    # already came and went without becoming Finished.
                    "status": ("finished" if g.get("home_score") is not None
                              and g.get("away_score") is not None else "scheduled"),
                    "home_lineup_confirmed": None, "away_lineup_confirmed": None})
    return out


def _conference_lookup(sport_key: str):
    """(lookup_dict, has_divisions) for sport_key -- has_divisions is False for sports whose real
    structure has no division level (WNBA: East/West only; NCAAF: most real conferences dropped
    divisions in the 2024+ realignment, never modeled here as a result), so the caller knows not
    to render an empty division sub-header for those.

    NCAAMB falls through to the final, generic ({}, False) below -- a real, deliberate gap, not
    an oversight: 350+ Division I teams across dozens of conferences is real reference data this
    platform hasn't sourced and verified, so every NCAAMB game lands in group_games' own "Other"
    bucket honestly, rather than risk a hand-typed mapping silently mislabeling a real team."""
    if sport_key == "MLB":
        return LS.MLB_TEAM_LEAGUE, True
    if sport_key == "NBA":
        return LS.NBA_TEAM_CONFERENCE, True
    if sport_key == "NFL":
        return LS.NFL_TEAM_CONFERENCE, True
    if sport_key == "WNBA":
        return {name: (conf, None) for name, conf in LS.wnba_team_conference().items()}, False
    if sport_key == "NCAAF":
        return {}, False   # NCAAF groups by conference directly from the game row -- see below
    return {}, False   # NCAAMB (and any future sport) -- see this function's own docstring above


def group_games(sport_key: str, games: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Groups already-fetched games by (conference[, division]), sorted chronologically within
    each group. Games whose home team isn't found in the reference table land in "Other" --
    FAILS SAFE, never dropped and never a crash (see league_structure.py's own docstring).

    Returns {"grouped": {conference: {division_or_None: [games...]}}, "other": [games...],
    "has_divisions": bool} -- has_divisions tells the renderer whether to show a division
    sub-header at all (WNBA/NCAAF never have one, see _conference_lookup)."""
    lookup, has_divisions = _conference_lookup(sport_key)
    grouped: Dict[str, Dict[Optional[str], List[Dict]]] = {}
    other: List[Dict[str, Any]] = []

    for g in sorted(games, key=lambda x: (x["dt"] is None, x["dt"], x.get("away") or "")):
        conf = div = None
        if sport_key == "NCAAF":
            # NCAAF's own schedule rows already carry conference directly -- no lookup table
            # needed at all, the one sport where this data was already there for free.
            conf = g.pop("_home_conference", None)
        else:
            entry = lookup.get(g["home"])
            if entry:
                conf, div = entry
        if not conf:
            other.append(g)
            continue
        grouped.setdefault(conf, {}).setdefault(div, []).append(g)

    return {"grouped": grouped, "other": other, "has_divisions": has_divisions}


@st.cache_data(ttl=300, show_spinner=False)
def todays_schedule(sport_key: str, date_str: str) -> Optional[Dict[str, Any]]:
    """Public entry point. Returns None for a sport outside SUPPORTED_SPORTS (the caller should
    simply not render the section, not show an empty/broken one) -- otherwise a dict from
    group_games above, always a real (possibly empty) result, never a crash on a bad fetch.

    CACHED, 5-minute TTL -- MLB's own per-game lineup-status check (get_lineup_status) adds one
    real boxscore fetch PER GAME shown, on top of the base schedule fetch; without caching, every
    Streamlit rerun on Home.py (which happens on any widget interaction anywhere on the page, not
    just a real refresh) would re-run the whole slate's worth of live fetches. Same TTL convention
    best_bets_data.py's own today_board already uses for live-ish data."""
    if sport_key not in SUPPORTED_SPORTS:
        return None
    try:
        if sport_key == "MLB":
            games = _mlb_games(date_str)
        elif sport_key == "NBA":
            games = _basketball_games(date_str, "nba_engine")
        elif sport_key == "WNBA":
            games = _basketball_games(date_str, "wnba_engine")
        elif sport_key == "NFL":
            games = _nfl_games(date_str)
        elif sport_key == "NCAAF":
            games = _ncaaf_games_with_conference(date_str)
        elif sport_key == "NCAAMB":
            games = _basketball_games(date_str, "ncaamb_engine")
        else:
            games = []
    except Exception:
        # A live fetch failure here must never take down Home.py itself -- an empty schedule
        # section (or the caller choosing not to render it) is the honest degradation, matching
        # every other engine's own fail-soft posture elsewhere in this platform.
        games = []
    return group_games(sport_key, games)


def next_scheduled_date(sport_key: str, date_str: str, max_days_ahead: int = 21) -> Optional[str]:
    """ADDED DIRECTLY ON REQUEST: the next real date with at least one real scheduled game for
    sport_key, searching forward from date_str -- meant to be called only AFTER todays_schedule
    for that same date came back real but empty (a genuine off-day, not a fetch failure), so a
    caller can show "no games today, but here's the next real slate" instead of a bare dead end.

    TWO GENUINELY DIFFERENT REAL STRATEGIES, matching each sport's own real data shape, not one
    uniform approach:
      - NFL/NCAAF: get_schedule(season) already returns the WHOLE real season in one fetch (see
        _nfl_games/_ncaaf_games_with_conference above, which already call it this way) -- scanned
        in memory for the next real date, zero new fetches. Capped to the CURRENTLY LOADED
        season's own real schedule -- this does not reach into a future season that hasn't
        started yet (e.g. asking in the real off-season between one season ending and the next
        one's own schedule being published), an honest boundary, not a gap.
      - MLB/NBA/WNBA/NCAAMB: get_schedule(date_str) is scoped to ONE real date -- scanned day by
        day, using each engine's own RAW get_schedule call directly (NOT _mlb_games/
        _basketball_games, which each add real per-game enrichment -- lineup status, logos --
        this only needs to know whether ANY real game exists that day, the cheapest possible real
        check). Capped at max_days_ahead (default 21) real days forward -- a genuine, long
        real off-season (WNBA/NBA between seasons) will exceed this and honestly return None
        rather than hammering a real API once per day for months look‑ahead.

    None if nothing real is found within the real search bounds above -- an honest "genuinely
    can't tell you when, from what's loaded" rather than a guess."""
    from datetime import datetime, timedelta
    if sport_key not in SUPPORTED_SPORTS:
        return None
    try:
        if sport_key in ("NFL", "NCAAF"):
            import importlib
            E = importlib.import_module("nfl_engine" if sport_key == "NFL" else "ncaaf_engine")
            season = E._infer_season(date_str)
            if season is None:
                return None
            schedule = E.get_schedule(season)
            date_field = "game_date" if sport_key == "NFL" else "start_date"
            future_dates = sorted({(g.get(date_field) or "")[:10] for g in schedule
                                   if (g.get(date_field) or "")[:10] > date_str})
            return future_dates[0] if future_dates else None

        engine_name = {"MLB": "mlb_engine", "NBA": "nba_engine", "WNBA": "wnba_engine",
                      "NCAAMB": "ncaamb_engine"}.get(sport_key)
        if engine_name is None:
            return None
        import importlib
        E = importlib.import_module(engine_name)
        start = datetime.strptime(date_str, "%Y-%m-%d")
        for i in range(1, max_days_ahead + 1):
            candidate = (start + timedelta(days=i)).strftime("%Y-%m-%d")
            if E.get_schedule(candidate):   # the raw, lightweight fetch -- no per-game enrichment
                return candidate
        return None
    except Exception:
        # Same fail-soft posture as todays_schedule itself -- a lookup failure here must never
        # take down the page; an honest None (the caller's own "nothing found" path) is the
        # correct degradation, not a crash.
        return None


def _ncaaf_games_with_conference(date_str: str) -> List[Dict[str, Any]]:
    """Same as _ncaaf_games, but stashes the home team's real conference (already on the raw
    schedule row -- see module docstring) onto each game so group_games can read it back off
    without a second lookup table NCAAF doesn't need."""
    import ncaaf_engine as E
    season = E._infer_season(date_str)
    if season is None:
        return []
    schedule = E.get_schedule(season)
    week = E._resolve_week(schedule, date_str)
    if week is None:
        return []
    out = []
    for g in E.games_for_week(schedule, week):
        dt = sports.game_dt(g.get("start_date"))
        if dt is None or dt.strftime("%Y-%m-%d") != date_str:
            continue
        out.append({"home": g.get("home_team"), "away": g.get("away_team"), "dt": dt,
                    "time_known": not bool(g.get("start_time_tbd")), "venue": g.get("venue"),
                    # No logo source for NCAAF yet -- CFBD's schedule cache doesn't carry one,
                    # and (unlike NFL) there's no safe abbreviation to build an ESPN CDN guess
                    # from -- CFBD team names ("Georgia") don't reliably map to ESPN's own file
                    # slugs for 130+ FBS teams the way a small, well-known 32-team league does.
                    # Real, stated gap: would need its own CFBD teams-endpoint fetch+cache,
                    # same pattern the schedule itself already uses, not a guess.
                    "home_logo": None, "away_logo": None,
                    # HONEST LIMITATION, same as NFL's own: CFBD's schedule cache is refreshed
                    # periodically, not a live feed, so only Scheduled/Finished are real signals
                    # here -- "completed" is CFBD's own real field, already on this row.
                    "status": "finished" if g.get("completed") else "scheduled",
                    "home_lineup_confirmed": None, "away_lineup_confirmed": None,
                    "_home_conference": g.get("home_conference")})
    return out
