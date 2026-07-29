"""
ncaaf_data.py — nightly-cached CollegeFootballData.com (CFBD) data: rosters, season player
stats, and schedule. See config_ncaaf.py's own docstring for why this is a CACHED-file engine
(like matchup_data.py/statcast_data.py) rather than a live-per-page-load one like every other
sport's engine here -- CFBD's free tier is metered at ~1,000 calls/month, unlike MLB Stats
API/ESPN/nflreadpy's effectively-unlimited free access.

refresh_ncaaf.py is the thin CLI wrapper that calls the refresh_*() functions below on a
schedule (GitHub Action). ncaaf_engine.py (a separate, not-yet-built module) will be the one
that reads the cached CSVs via the load_*() functions below and turns them into build_slate()-
shaped rows, the same division of responsibility matchup_data.py/mlb_engine.py already have.

RAW REST, NOT THE OFFICIAL `cfbd` PYTHON CLIENT -- A REAL, TESTED REASON, NOT A STYLE CHOICE:
the official `cfbd` package (OpenAPI-generated) hard-pins `pydantic<2` (confirmed directly
against its published package metadata: "Requires-Dist: pydantic<2,>=1.10.5", true of every
current release, not one bad version). This app's own nfl_engine.py already depends on
nflreadpy, which requires `pydantic>=2.0.0`. Installing both in the SAME environment doesn't
just create a pip warning -- it was tested directly during this build: with `cfbd` installed,
`import nflreadpy` throws `ModuleNotFoundError: No module named 'pydantic._internal'`
immediately, because pip's resolver silently downgrades pydantic to satisfy cfbd's hard ceiling,
which nflreadpy's own pydantic-2-only code can't run under. Since this is one Streamlit app
where a person can navigate from an NFL page to an NCAAF page in the same running process, both
packages need to import successfully in the SAME environment -- there's no "isolate the GitHub
Action's own requirements" escape hatch here, because the deployed APP itself needs both. Raw
`requests` calls against the same REST API `cfbd` wraps sidesteps the conflict entirely, costs
zero new dependencies (requests is already pinned in requirements.txt), and matches how every
other API integration in this codebase already works (odds_api.py, mlb_engine.py, ufc_engine.py
-- none of them use a generated client library either).

CALL BUDGET, confirmed against CFBD's own published API docs (github.com/CFBD/cfbd-python/
blob/main/docs/) -- the REST paths and params are identical whether called through the official
client or raw, so that research still applies even though the client itself isn't used:
  - GET /stats/player/season?year=YYYY -- ONE call, ALL players, ALL teams, for the whole season.
  - GET /roster?year=YYYY -- team is OPTIONAL; ONE call returns every FBS/FCS team's full roster.
  - GET /games?year=YYYY -- ONE call, whole season's schedule (optionally add week= to narrow).
That's 3 calls for a COMPLETE refresh, not one call per team or per player -- the same "load
once per slate, not once per player" discipline nflreadpy's engine already follows, which is
what makes even a metered free tier workable for a weekly-cadence sport. A refresh even every
single day of a ~15-week season costs roughly 3 x 7 x 15 = 315 calls -- comfortably inside the
~1,000/month budget with real room to spare, even before considering a weekly-only cadence
(which would need a fraction of that).

UNVERIFIED AGAINST A LIVE RESPONSE, same honest posture nfl_engine.py's own docstring carries for
nflreadpy before its first real pull -- this sandbox's network doesn't reach
api.collegefootballdata.com, so nothing below has been exercised against real data, only against
CFBD's own published OpenAPI documentation:
  - /stats/player/season returns LONG-format rows: {season, player_id, player, position, team,
    conference, category, stat_type, stat (a STRING, not numeric)} -- one row per (player,
    category, stat_type) combination, confirmed via CFBD's own PlayerStat.md schema doc, NOT one
    row per player with stat columns. The exact string values CFBD uses for category/stat_type
    (e.g. is passing yards category="passing", stat_type="YDS"? Something else?) are NOT guessed
    at here -- refresh_player_season_stats pivots whatever comes back, faithfully, into a wide
    player x (category_stattype) table, and prints the real column names it produced. The first
    real refresh run is what actually confirms which columns exist; a future ncaaf_engine.py
    reads specific columns and will need real column names to match against, not assumed ones.
  - CFBD's docs (generated from a Pydantic model) show snake_case field names (player_id,
    stat_type, start_date, ...), but many real-world OpenAPI-generated APIs serve raw JSON in
    camelCase over the wire and let the client library handle the camelCase->snake_case mapping
    -- meaning the RAW JSON this module parses could plausibly use either convention. Every
    field access below tries both (e.g. `s.get("playerId") or s.get("player_id")`) specifically
    because of this uncertainty, rather than assuming one. The first real refresh run's printed
    column list is what actually confirms which convention CFBD's raw API uses.
  - Roster player "id" and PlayerStat "player_id" are both documented as strings, but whether
    they're the SAME id space (so a roster row and a stat row for the same real person share one
    id) is not confirmed by the docs alone -- flagged here rather than assumed. If the first real
    refresh shows they don't line up, joining by name+team is the fallback, not a silent gap.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

import pandas as pd
import requests

BASE = "https://api.collegefootballdata.com"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ROSTER_PATH = os.path.join(DATA_DIR, "ncaaf_rosters.csv")
PLAYER_STATS_PATH = os.path.join(DATA_DIR, "ncaaf_player_stats.csv")
SCHEDULE_PATH = os.path.join(DATA_DIR, "ncaaf_schedule.csv")
PLAYER_GAME_STATS_PATH = os.path.join(DATA_DIR, "ncaaf_player_game_stats.csv")


class CFBDError(Exception):
    pass


def _get(path: str, params: Dict, api_key: str) -> list:
    """Raw GET against the CFBD REST API. Bearer-token auth, confirmed via CFBD's own docs
    ("Configure Bearer authorization: apiKey") -- same shape as odds_api.py's own _get(), same
    reason: a thin, dependency-free wrapper is easier to keep correct than a generated client,
    and here it's not just easier, it's required (see this module's own docstring)."""
    try:
        r = requests.get(f"{BASE}{path}", params=params,
                         headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
    except requests.RequestException as e:
        raise CFBDError(f"network error: {e}") from e
    if r.status_code == 401:
        raise CFBDError("401 Unauthorized — check CFBD_API_KEY.")
    if r.status_code == 429:
        raise CFBDError("429 — out of CFBD quota for this period.")
    if r.status_code != 200:
        raise CFBDError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


_ROSTER_COLUMNS = ["id", "first_name", "last_name", "name", "team", "position",
                  "year", "jersey", "height", "weight"]


def refresh_rosters(year: int, api_key: str, out_path: str = ROSTER_PATH) -> str:
    """Every FBS/FCS team's full roster for `year`, ONE call (team= left unset deliberately --
    see this module's own docstring for the confirmed-optional param).

    Falls back to `year - 1` if the requested year comes back empty, clearly logged as a
    fallback. Confirmed via a real run, not theoretical: GET /roster?year=2026 returned 0
    players on July 28, 2026 -- weeks before the 2026 season's own Week 0 (Aug 27). CFBD's own
    client docs default this same param to 2025, a real hint that a not-yet-started season's
    roster genuinely isn't populated yet, not that the request itself is malformed (no auth/rate
    error came back, just a valid empty list). A season roster is far more stable year over year
    than in-season stats are, so last year's roster is a reasonable placeholder until the current
    year's actually populates -- much better than caching nothing.

    Restricted to classification="fbs" -- confirmed via a real run that the unfiltered pull
    returns EVERY division (FBS/FCS/D2/D3 combined: 30,072 players for one recent season), far
    more than the FBS-only slate this platform's audience and the odds market itself actually
    cover (sportsbooks don't offer player props on FCS/D2/D3 games). The exact string value
    CFBD's raw API expects for this filter ("fbs" lowercase, matching the prose in its own docs
    -- "Optional filter to only include players from FBS or FCS teams") is inferred from
    convention, not confirmed against a live response the way the rest of this module's
    unverified items are -- if this run's printed player count doesn't drop meaningfully from
    30,072, the filter value needs adjusting, and that'll be visible directly in the log."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    def _fetch(y):
        players = _get("/roster", {"year": y, "classification": "fbs"}, api_key)
        return [{
            "id": p.get("id"), "first_name": p.get("first_name") or p.get("firstName"),
            "last_name": p.get("last_name") or p.get("lastName"),
            "name": f"{(p.get('first_name') or p.get('firstName') or '')} "
                   f"{(p.get('last_name') or p.get('lastName') or '')}".strip(),
            "team": p.get("team"), "position": p.get("position"), "year": p.get("year"),
            "jersey": p.get("jersey"), "height": p.get("height"), "weight": p.get("weight"),
        } for p in players]

    rows = _fetch(year)
    used_year = year
    if not rows:
        print(f"[NCAAF] GET /roster?year={year} returned 0 players -- likely too early in the "
             f"season for this year's roster to be posted yet. Falling back to year={year - 1}.")
        rows = _fetch(year - 1)
        used_year = year - 1

    df = pd.DataFrame(rows, columns=_ROSTER_COLUMNS) if rows else pd.DataFrame(columns=_ROSTER_COLUMNS)
    df.to_csv(out_path, index=False)
    print(f"[NCAAF] GET /roster?year={used_year}: {len(df)} players cached"
         f"{' (fallback year)' if used_year != year else ''}.")
    return out_path


def refresh_player_season_stats(year: int, api_key: str, out_path: str = PLAYER_STATS_PATH) -> str:
    """Season stat lines for every player, ONE call. CFBD returns this in LONG format (one row
    per player-category-stat_type combo) -- pivoted here into one row per player with a column
    per (category, stat_type) pair, so the cached CSV is directly usable the way every other
    sport's cached/season-stat table already is, without a future reader needing to know CFBD's
    own wire format. Prints the real resulting column names so the exact stat_type strings CFBD
    actually used are visible in the refresh log, not just assumed.

    Same year-fallback as refresh_rosters, for the same confirmed-real reason: season stats for
    a not-yet-started season are empty by definition (no games played yet to generate stats
    from) -- last year's full-season stats are a far more useful starting projection basis than
    an empty cache until the current season's own games start accumulating real stats."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    def _fetch(y):
        return _get("/stats/player/season", {"year": y}, api_key)

    stats = _fetch(year)
    used_year = year
    if not stats:
        print(f"[NCAAF] GET /stats/player/season?year={year} returned 0 rows -- likely no games "
             f"played yet this season. Falling back to year={year - 1}.")
        stats = _fetch(year - 1)
        used_year = year - 1

    long_rows = [{
        "season": s.get("season"),
        "player_id": s.get("playerId") or s.get("player_id"),
        "player": s.get("player"), "position": s.get("position"),
        "team": s.get("team"), "conference": s.get("conference"),
        "stat_col": f"{s.get('category')}_{s.get('statType') or s.get('stat_type')}".strip("_"),
        "value": s.get("stat"),
    } for s in stats]
    if not long_rows:
        df = pd.DataFrame(columns=["season", "player_id", "player", "position", "team", "conference"])
        df.to_csv(out_path, index=False)
        print(f"[NCAAF] GET /stats/player/season?year={used_year} also returned 0 rows -- wrote an empty cache.")
        return out_path

    long_df = pd.DataFrame(long_rows)
    # Numeric where possible; CFBD's `stat` field is typed as a string in its own schema (see
    # this module's docstring), so this cast is required, not defensive-for-no-reason.
    long_df["value"] = pd.to_numeric(long_df["value"], errors="coerce")

    identity = (long_df[["season", "player_id", "player", "position", "team", "conference"]]
               .drop_duplicates("player_id").set_index("player_id"))
    wide = long_df.pivot_table(index="player_id", columns="stat_col", values="value",
                               aggfunc="first")
    out = identity.join(wide, how="left").reset_index()
    out.to_csv(out_path, index=False)
    print(f"[NCAAF] GET /stats/player/season?year={used_year}: {len(out)} players, "
         f"{len(wide.columns)} stat columns.{' (fallback year)' if used_year != year else ''}")
    print(f"[NCAAF] ALL stat columns: {sorted(wide.columns)}")
    return out_path


_SCHEDULE_COLUMNS = ["id", "season", "week", "start_date", "start_time_tbd", "completed",
                    "neutral_site", "venue", "home_id", "home_team", "home_conference",
                    "home_points", "away_id", "away_team", "away_conference", "away_points"]


def refresh_schedule(years: List[int], api_key: str, out_path: str = SCHEDULE_PATH) -> str:
    """Full schedule for every season in `years`, ONE call per year (all weeks; the week= param
    is left unset on purpose -- narrowing per-week would mean one call per week instead of one
    call per season).

    ACCEPTS MULTIPLE YEARS -- a real, live-confirmed bug, not a hypothetical: refresh_rosters and
    refresh_player_season_stats both fall back to year-1 when the current season is empty (see
    their own docstrings), but this function used to pull ONLY the target year's schedule. When a
    fallback happened, ncaaf_engine._team_games_played_for_stats_season needed the FALLBACK
    year's own schedule (to count that season's real completed games as the rate denominator),
    and it simply didn't exist in the cache -- get_schedule(fallback_year) came back empty,
    every team's games-played resolved to 0, and player_row's own zero-games guard silently
    dropped every single player from the slate. Confirmed directly: a real refresh_ncaaf.py run
    showed a real 2026 schedule (99 games that "night") alongside real 2025-fallback stats, and
    Best Bets showed zero plays for every date tried. The caller (refresh_ncaaf.py) is
    responsible for figuring out which years are actually needed (the target year, plus
    whichever year roster/stats actually landed on) and passing all of them here.

    No year-fallback INSIDE this function, still -- unlike roster/stats, an empty response for a
    year that was explicitly asked for is a genuine anomaly worth seeing as zero games for that
    year, not silently substituting a different one; the caller decides which years to ask for,
    this function just fetches exactly those, faithfully."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    all_rows: List[Dict] = []
    for year in years:
        games = _get("/games", {"year": year, "classification": "fbs"}, api_key)
        all_rows.extend([{
            "id": g.get("id"), "season": g.get("season"), "week": g.get("week"),
            "start_date": g.get("startDate") or g.get("start_date"),
            "start_time_tbd": g.get("startTimeTBD") if "startTimeTBD" in g else g.get("start_time_tbd"),
            "completed": g.get("completed"),
            "neutral_site": g.get("neutralSite") if "neutralSite" in g else g.get("neutral_site"),
            "venue": g.get("venue"),
            "home_id": g.get("homeId") or g.get("home_id"), "home_team": g.get("homeTeam") or g.get("home_team"),
            "home_conference": g.get("homeConference") or g.get("home_conference"),
            "home_points": g.get("homePoints") if "homePoints" in g else g.get("home_points"),
            "away_id": g.get("awayId") or g.get("away_id"), "away_team": g.get("awayTeam") or g.get("away_team"),
            "away_conference": g.get("awayConference") or g.get("away_conference"),
            "away_points": g.get("awayPoints") if "awayPoints" in g else g.get("away_points"),
        } for g in games])
        print(f"[NCAAF] GET /games?year={year}: {len(games)} games.")
    df = pd.DataFrame(all_rows, columns=_SCHEDULE_COLUMNS) if all_rows else pd.DataFrame(columns=_SCHEDULE_COLUMNS)
    df.to_csv(out_path, index=False)
    print(f"[NCAAF] Schedule cache: {len(df)} games total across {sorted(set(years))} -- "
         f"{df['week'].nunique() if not df.empty else 0} distinct week numbers.")
    return out_path


def refresh_player_game_stats(year: int, api_key: str, completed_weeks: List[int],
                              out_path: str = PLAYER_GAME_STATS_PATH) -> str:
    """Per-game player stat logs -- ONE call per completed week (see this module's own docstring
    for the call-budget accounting: ~14 calls for a full season pulled once, comfortably inside
    the ~1,000/month budget). This is what unlocks two things every other sport's engine already
    has and NCAAF's Phase 2 build explicitly deferred: a real recency-window bootstrap
    (ncaaf_projections.simulate_player_stat can resample real game-to-game values instead of
    assuming an unvalidated spread) and real Retrospective grading
    (ncaaf_engine.get_player_results can finally return real per-game results instead of always
    {}).

    completed_weeks: which weeks to actually pull -- pass only weeks the cached schedule marks
    completed=True (see refresh_ncaaf.py), not every week 1-15 blindly; querying a week with no
    games played yet just burns a call for an empty result.

    RESPONSE SHAPE, the least-confirmed piece of this whole integration -- flagged directly, not
    glossed over: GET /games/players returns a deeply nested structure, confirmed down to
    {id, teams: [{school, conference, home_away, points, categories: [{name, types: [{...,
    athletes: [{...}]}]}]}]} against CFBD's own published model docs (PlayerGame -> 
    PlayerGameTeams -> PlayerGameCategories -> PlayerGameTypes -> PlayerGameAthletes). The two
    deepest models' exact field names (does a "type" entry key its name as "name" or "type"? does
    an athlete entry use "id"/"name"/"stat" like PlayerStat, or different keys?) resisted full
    documentation confirmation despite real effort during this build. Every field access below
    tries multiple plausible key names for exactly that reason (same defensive posture already
    used for the camelCase/snake_case uncertainty elsewhere in this module) -- and this function
    prints the FULL raw nested structure of the first athlete entry it finds, unconditionally, on
    every run, so the real shape is visible in the very first refresh log rather than inferred."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    long_rows: List[Dict] = []
    printed_sample = False

    for week in completed_weeks:
        try:
            games = _get("/games/players", {"year": year, "week": week}, api_key)
        except CFBDError as e:
            print(f"[NCAAF] GET /games/players?year={year}&week={week} failed: {e}")
            continue
        for game in games:
            game_id = game.get("id")
            for team in (game.get("teams") or []):
                school = team.get("school")
                for category in (team.get("categories") or []):
                    cat_name = category.get("name")
                    for type_ in (category.get("types") or []):
                        type_name = type_.get("name") or type_.get("type") or type_.get("statType")
                        for athlete in (type_.get("athletes") or []):
                            if not printed_sample:
                                print(f"[NCAAF] raw /games/players athlete sample (week {week}): "
                                     f"category={cat_name!r} type={type_name!r} athlete={athlete!r}")
                                printed_sample = True
                            athlete_id = (athlete.get("id") or athlete.get("athleteId")
                                         or athlete.get("playerId") or athlete.get("player_id"))
                            athlete_name = athlete.get("name") or athlete.get("player")
                            stat_val = athlete.get("stat") or athlete.get("value")
                            if athlete_id is None or not cat_name or not type_name:
                                continue
                            long_rows.append({
                                "game_id": game_id, "week": week, "team": school,
                                "player_id": athlete_id, "player": athlete_name,
                                "stat_col": f"{cat_name}_{type_name}".strip("_"),
                                "value": stat_val,
                            })

    if not long_rows:
        cols = ["game_id", "week", "team", "player_id", "player"]
        pd.DataFrame(columns=cols).to_csv(out_path, index=False)
        print(f"[NCAAF] GET /games/players: 0 rows across {len(completed_weeks)} week(s) -- "
             "wrote an empty cache.")
        return out_path

    long_df = pd.DataFrame(long_rows)
    long_df["value"] = pd.to_numeric(long_df["value"], errors="coerce")
    identity = (long_df[["game_id", "week", "team", "player_id", "player"]]
               .drop_duplicates(["game_id", "player_id"]).set_index(["game_id", "player_id"]))
    wide = long_df.pivot_table(index=["game_id", "player_id"], columns="stat_col",
                               values="value", aggfunc="first")
    out = identity.join(wide, how="left").reset_index()
    out.to_csv(out_path, index=False)
    print(f"[NCAAF] GET /games/players: {len(out)} player-game row(s) across "
         f"{len(completed_weeks)} week(s), {len(wide.columns)} stat columns: {sorted(wide.columns)}")
    return out_path


def load_rosters(path: str = ROSTER_PATH) -> List[Dict]:
    if not os.path.exists(path):
        return []
    try:
        return pd.read_csv(path).to_dict("records")
    except pd.errors.EmptyDataError:
        # A zero-row API response writes a columnless CSV (pd.DataFrame([]) has no columns at
        # all, not just no rows) -- read_csv on that raises rather than returning an empty
        # frame. A genuinely empty cache should load as [], not crash the caller.
        return []


def load_player_game_stats(path: str = PLAYER_GAME_STATS_PATH) -> List[Dict]:
    if not os.path.exists(path):
        return []
    try:
        return pd.read_csv(path).to_dict("records")
    except pd.errors.EmptyDataError:
        return []


def load_player_stats(path: str = PLAYER_STATS_PATH) -> List[Dict]:
    if not os.path.exists(path):
        return []
    try:
        return pd.read_csv(path).to_dict("records")
    except pd.errors.EmptyDataError:
        return []


def load_schedule(path: str = SCHEDULE_PATH) -> List[Dict]:
    if not os.path.exists(path):
        return []
    try:
        return pd.read_csv(path).to_dict("records")
    except pd.errors.EmptyDataError:
        return []


def resolve_week(target_date: str, schedule: Optional[List[Dict]] = None,
                 path: str = SCHEDULE_PATH) -> Optional[int]:
    """Which week a calendar date (YYYY-MM-DD) falls in, from the REAL cached schedule -- never
    a day-of-week rule (see config_ncaaf.py's own comment on why Week 0 vs Week 1 proper aren't
    a fixed offset from a hardcoded season-start date). Returns the week containing the closest
    game on or after target_date, or the season's last week if target_date is past it -- same
    "next upcoming week, else last week" fallback nfl_engine.py's own _resolve_week uses, for the
    same reason (a date picker can land on an off day with no games)."""
    schedule = schedule if schedule is not None else load_schedule(path)
    if not schedule:
        return None
    upcoming = sorted({g["week"] for g in schedule
                       if g.get("start_date") and str(g["start_date"])[:10] >= target_date})
    if upcoming:
        return upcoming[0]
    all_weeks = sorted({g["week"] for g in schedule if g.get("week") is not None})
    return all_weeks[-1] if all_weeks else None
