"""
ncaaf_engine.py — NCAA Football (FBS) data layer, reading from ncaaf_data.py's nightly-cached
CFBD files (never talks to CFBD directly — see ncaaf_data.py's own docstring for why this is a
cached-file engine, unlike every other sport's live-per-page-load engine here).

TWO REAL, CONFIRMED DATA LIMITATIONS THAT SHAPE THIS ENGINE'S DESIGN — NOT GUESSES, NOT SILENT
SIMPLIFICATIONS:

  1. SEASON TOTALS, NOT PER-GAME LOGS. CFBD's /stats/player/season endpoint (what
     ncaaf_data.refresh_player_season_stats caches) returns season-aggregate totals, confirmed
     via its own PlayerStat schema (season/player/category/stat_type/stat — no per-game
     breakdown at all). Every other sport's engine here (MLB, WNBA, NBA, NCAAMB, NFL) computes a
     RECENT-FORM window from real individual game logs (config_ncaaf.RECENT_GAMES_N=4 was written
     with that same intent). NCAAF genuinely can't do that from this cache — there's no
     per-game data to window over. What this engine does instead: season-to-date PER-GAME RATE
     (season total / team games played so far), a single-number season average, not a recency-
     weighted one. A real, deliberate v1 scope decision, not an oversight — CFBD's
     /games/players endpoint (get_game_player_stats) DOES have real per-game logs and could
     upgrade this to a true recency window in a later pass, at the cost of extra API calls (one
     per week or per team, not a single bulk pull the way season stats are) that would need
     their own call-budget accounting against ncaaf_data.py's already-documented ~1,000/month
     ceiling.

  2. NO "GAMES PLAYED" FIELD PER PLAYER, AND NO "TARGETS" STAT. Confirmed against the real,
     complete column list from a live refresh run (not assumed): passing/rushing/receiving/
     kicking/punting/defensive/kickReturns/puntReturns/fumbles/interceptions are all present,
     but nothing resembling "games played" exists in any category, and receiving stats include
     REC (receptions) but not a separate targets count the way NFL's own weekly stats do.
     Consequences, both handled explicitly rather than silently:
       - Games-played denominator: approximated as the PLAYER'S TEAM's own completed-game count
         so far this season (from the cached schedule), not a true individual count. This
         assumes a rostered player with real season totals played in most of their team's games
         so far — a reasonable assumption for the STARTERS this engine's rotation floors (see
         config_ncaaf.py) are built to keep, less accurate for backups, who the floors are
         designed to filter out anyway.
       - RB/WR/TE opportunity floor uses RECEPTIONS instead of targets (config_ncaaf.MIN_WR_
         TARGETS is checked against receiving_REC, not a targets column that doesn't exist in
         this cache) — a real, honest substitution, not a silent one: receptions conflates
         opportunity with catch rate/QB accuracy in a way targets wouldn't, so this floor is
         noisier than NFL's own equivalent. Flagged here, not hidden.

Player identity join: roster rows (id/first_name/last_name/team) and season-stat rows
(player_id/player/team) are joined PRIMARILY by id -- UNVERIFIED whether RosterPlayer.id and
PlayerStat.player_id share the same id space (see ncaaf_data.py's own docstring for this same
caveat). Falls back to normalized name+team matching when the id join comes up empty for a given
player, logged so a systematic id-space mismatch (as opposed to a few legitimately-missing
players) is visible rather than silently eating the whole roster.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import config_ncaaf as CFG
import ncaaf_data as ND


def _diag(msg: str) -> None:
    if os.environ.get("H2_DIAG"):
        print(f"[NCAAF] {msg}")


# odds_market_key -> (season-stat column, display name, rotation-floor stat column, floor value
# CHECKED AGAINST THE FLOOR COLUMN'S PER-GAME RATE, same "player's own average, not a fixed
# global number" contract nfl_engine.py's own _MARKET_SPEC has). Column names below are the
# CONFIRMED real ones from a live refresh run, not guessed (see this module's own docstring).
_MARKET_SPEC: Dict[str, Tuple[str, str, str, float]] = {
    "player_pass_yds":      ("passing_YDS",   "Pass Yards",     "passing_ATT",   CFG.MIN_QB_ATTEMPTS),
    "player_rush_yds":      ("rushing_YDS",   "Rush Yards",     "_touches",      CFG.MIN_RB_TOUCHES),
    "player_receptions":    ("receiving_REC", "Receptions",     "receiving_REC", CFG.MIN_WR_TARGETS),
    "player_reception_yds": ("receiving_YDS", "Receiving Yards", "receiving_REC", CFG.MIN_WR_TARGETS),
}

_MARKETS_FOR_POSITION: Dict[str, List[str]] = {
    "QB": ["player_pass_yds", "player_rush_yds"],   # many FBS QBs run meaningfully -- unlike
                                                     # most NFL QBs, worth the rush-yards market
    "RB": ["player_rush_yds", "player_receptions", "player_reception_yds"],
    "WR": ["player_receptions", "player_reception_yds"],
    "TE": ["player_receptions", "player_reception_yds"],
}


# --------------------------------------------------------------------------- schedule / weeks
def get_schedule(season: int) -> List[Dict[str, Any]]:
    """This season's cached FBS schedule, from ncaaf_data's cache -- never a live CFBD call."""
    return [g for g in ND.load_schedule() if g.get("season") == season]


def _resolve_week(schedule: List[Dict], date_str: str) -> Optional[int]:
    return ND.resolve_week(date_str, schedule=schedule)


def games_for_week(schedule: List[Dict], week: int) -> List[Dict]:
    return [g for g in schedule if g.get("week") == week]


def get_team_recent_scoring(team_name: str, schedule: List[Dict], before_week: int,
                            n: int = 4) -> Optional[Dict[str, float]]:
    """This team's own points scored, recent (last n completed games before before_week) vs.
    season-to-date -- built entirely from the already-fetched full-season schedule (get_schedule),
    zero new network calls. Same reasoning as nfl_engine.py's own identical function -- see
    sports.team_trend_tag's own docstring for the full cross-sport reasoning.

    Uses NCAAF's own real field names (home_points/away_points, completed) -- NOT NFL's
    (home_score/away_score) -- these are two genuinely different cached schedules, not a shared
    schema, confirmed against ncaaf_data.py's own _SCHEDULE_COLUMNS.

    Returns None if this team has no completed games before before_week at all -- an honest
    "no data yet", not a fabricated average."""
    played = [g for g in schedule if g.get("completed") and g.get("week", 999) < before_week
             and (g.get("home_team") == team_name or g.get("away_team") == team_name)]
    scored = []
    for g in sorted(played, key=lambda g: g["week"]):
        is_home = g.get("home_team") == team_name
        pts = g.get("home_points") if is_home else g.get("away_points")
        if pts is not None:
            scored.append(float(pts))
    if not scored:
        return None
    recent = scored[-n:]
    return {"recent_avg": sum(recent) / len(recent), "season_avg": sum(scored) / len(scored),
           "recent_games": len(recent), "season_games": len(scored)}


def _team_games_played_before(schedule: List[Dict], team: str, week: int) -> int:
    """How many of `team`'s games have already been COMPLETED strictly before `week` this
    season -- the per-game-rate denominator this engine uses in place of a true individual
    games-played count (see this module's own docstring for why)."""
    n = 0
    for g in schedule:
        if g.get("week") is None or g["week"] >= week:
            continue
        if not g.get("completed"):
            continue
        if g.get("home_team") == team or g.get("away_team") == team:
            n += 1
    return n


def _team_games_played_total(schedule: List[Dict], team: str) -> int:
    """A team's total completed games across a FULL season -- used instead of
    _team_games_played_before when the cached player stats turn out to be from a completed
    PRIOR season (ncaaf_data's own year-fallback), not the season currently being built for.
    See _team_games_played_for_stats_season's own docstring for why this distinction is real
    and not academic: dividing a completed season's full total by "games before week 1 of the
    NEW season" (always 0) would zero out every player's rate, not just understate it."""
    return sum(1 for g in schedule
              if g.get("completed") and (g.get("home_team") == team or g.get("away_team") == team))


def _team_games_played_for_stats_season(target_schedule: List[Dict], stats_season: int,
                                        target_season: int, team: str, week: int) -> int:
    """The correct games-played denominator for THIS team's stats, aware of which season those
    stats actually came from -- confirmed as a real, not theoretical, necessity: testing this
    engine against week 1 of a new season (0 games played yet) while the cached stats were last
    season's full totals (via ncaaf_data's own documented year-fallback) produced ZERO rows,
    not just noisy ones, because every player's rate came out to total/0 -> filtered by the
    `team_games_played <= 0` guard in player_row.

    If stats_season == target_season: the stats are for the season currently being built --
    "games played before this week" is the right, current-season-aware denominator.
    If stats_season < target_season: the stats are a completed PRIOR season (fallback) --
    the right denominator is that WHOLE season's game count, not anything from the new season's
    schedule at all, which is why this takes stats_season as its own schedule lookup."""
    if stats_season == target_season:
        return _team_games_played_before(target_schedule, team, week)
    stats_schedule = get_schedule(stats_season)
    return _team_games_played_total(stats_schedule, team)


def _infer_season(date_str: str) -> Optional[int]:
    """Same rule as nfl_engine.py's own _infer_season, for the same reason: the college football
    season "year" runs Aug/Sep - Jan, so a January/early-February date belongs to the PRIOR
    year's season (e.g. a January 2027 CFP National Championship date is part of the 2026
    season, not a "2027 season" that CFBD doesn't have real data for yet)."""
    try:
        season = int(date_str[:4])
        if int(date_str[5:7]) <= 2:
            season -= 1
        return season
    except (ValueError, TypeError):
        return None


# Translates this engine's own confirmed CFBD per-game column names into the SAME stat-key
# vocabulary retro.py's shared MARKET_STAT dict already expects for these exact display market
# names ("Pass Yards", "Rush Yards", "Receptions", "Receiving Yards" -- NCAAF's market_map in
# sports.py deliberately reuses NFL's own display names). Confirmed by reading retro.py directly,
# not assumed: MARKET_STAT maps "Pass Yards" -> "passing_yards", NOT "passing_YDS". Without this
# translation, get_player_results would return real data under keys retro.py never looks up --
# every NCAAF play would silently grade as "no result" even with real per-game stats present.
_RESULT_KEY_MAP = {
    "passing_YDS": "passing_yards", "rushing_YDS": "rushing_yards",
    "receiving_REC": "receptions", "receiving_YDS": "receiving_yards",
}


def get_player_results(date_str: str) -> Dict[str, Dict[str, float]]:
    """Same contract as mlb_engine.get_player_results/nfl_engine.get_player_results (keyed by
    player id, {stat_col: value}) -- required by Retrospective's grading logic. Real per-game
    results, from ncaaf_data's per-game cache (populated by refresh_player_game_stats) -- no
    longer always {} now that per-game data exists. Still returns {} gracefully for a date/week
    with no cached per-game rows (not yet refreshed, or a not-yet-played week), same honest
    degradation every other sport's version already has for a future date."""
    season = _infer_season(date_str)
    if season is None:
        _diag(f"get_player_results({date_str}): could not infer season from date_str")
        return {}
    schedule = get_schedule(season)
    week = _resolve_week(schedule, date_str)
    if week is None:
        return {}

    rows = [r for r in ND.load_player_game_stats() if r.get("week") == week]
    out: Dict[str, Dict[str, float]] = {}
    for r in rows:
        pid = r.get("player_id")
        if pid is None:
            continue
        translated = {}
        for cfbd_col, market_key in _RESULT_KEY_MAP.items():
            val = r.get(cfbd_col)
            if not _missing(val):
                translated[market_key] = float(val)
        if translated:
            out[str(pid)] = translated
    _diag(f"get_player_results({date_str}): season {season} week {week}, {len(out)} player result(s)")
    return out


# --------------------------------------------------------------------------- roster / stats join
def _missing(v) -> bool:
    """True for None or NaN. Real production bug this guards against: pandas' CSV round-trip
    (ncaaf_data.load_rosters/load_player_stats) turns a genuinely missing cell into NaN, not
    None -- and NaN is TRUTHY in Python (`bool(float('nan'))` is True), so the common `(x or
    default)` idiom silently lets it through unchanged. Confirmed live: a roster row with no
    position value produced `(nan or "").upper()`, which is `nan.upper()` -- AttributeError,
    not a graceful "no position known" skip."""
    return v is None or (isinstance(v, float) and v != v)


def _normalize_name(name) -> str:
    if _missing(name):
        return ""
    return " ".join(str(name).lower().replace(".", "").replace("-", " ").split())


def _stats_by_id_and_name(season: int) -> Tuple[Dict[str, Dict], Dict[Tuple[str, str], Dict]]:
    """Season-stat rows, indexed two ways: by player_id (the primary join) and by
    (normalized_name, team) (the fallback -- see this module's own docstring on the unverified
    id-space question)."""
    by_id: Dict[str, Dict] = {}
    by_name_team: Dict[Tuple[str, str], Dict] = {}
    for r in ND.load_player_stats():
        pid = r.get("player_id")
        if not _missing(pid):
            by_id[str(pid)] = r
        name, team = r.get("player"), r.get("team")
        if not _missing(name) and not _missing(team):
            by_name_team[(_normalize_name(name), team)] = r
    return by_id, by_name_team


def player_recent_games(player_id, before_week: int, n: int = CFG.RECENT_GAMES_N) -> List[Dict]:
    """This player's last n games STRICTLY BEFORE before_week this season, most recent first --
    same "strictly before" lookahead-bias discipline as nfl_engine.player_recent_games (see its
    own docstring for the full reasoning; identical concern applies here).

    Reads ncaaf_data's per-game cache -- empty if refresh_player_game_stats hasn't been run yet,
    or for a player/week with no cached rows. This is the real per-game data that upgrades
    ncaaf_projections.py from its original parametric-only approach to an actual bootstrap, the
    same method every other sport's engine here already uses."""
    rows = [r for r in ND.load_player_game_stats()
           if str(r.get("player_id")) == str(player_id) and r.get("week") is not None
           and r["week"] < before_week]
    rows.sort(key=lambda r: r["week"], reverse=True)
    return rows[:n]


def get_player_season_games(player_id, before_date: str, max_games: int = 20) -> List[Dict]:
    """This player's full game log for the season so far (any opponent), most recent first --
    the baseline QB Lab's TD:INT efficiency table and Matchup Lab compare a recent/head-to-head
    sample against. Same role as nfl_engine.get_player_season_games; max_games=20 comfortably
    covers a full ~14-game FBS regular season plus a conference championship, without needing
    NFL's 25 (a shorter season overall)."""
    season = _infer_season(before_date)
    if season is None:
        return []
    schedule = get_schedule(season)
    week = _resolve_week(schedule, before_date)
    if week is None:
        return []
    return player_recent_games(player_id, before_week=week, n=max_games)


_ALLOWED_STAT_COLS = ["passing_YDS", "rushing_YDS", "receiving_REC", "receiving_YDS"]


def get_team_allowed_stats(team: str, before_date: str, n: Optional[int] = None) -> Dict[str, float]:
    """Average PassYds/RushYds/Receptions/RecYds ALLOWED by this team's defense -- n=None for the
    whole season so far, n=int for just their last n games. Same construction as
    nfl_engine.get_team_allowed_stats: group the per-game cache by game (every OPPOSING player's
    stat line against this team, summed per game = that game's real team total against them),
    then average across games. Depends on the per-game cache's opponent_team field (added
    specifically to support this function -- see ncaaf_data.refresh_player_game_stats's own
    docstring)."""
    season = _infer_season(before_date)
    if season is None:
        return {}
    schedule = get_schedule(season)
    week = _resolve_week(schedule, before_date)
    if week is None:
        return {}
    rows = [r for r in ND.load_player_game_stats()
           if r.get("opponent_team") == team and r.get("week") is not None and r["week"] < week]
    if not rows:
        return {}
    by_game: Dict[object, Dict[str, float]] = {}
    for r in rows:
        gid = r.get("game_id")
        acc = by_game.setdefault(gid, {c: 0.0 for c in _ALLOWED_STAT_COLS})
        for col in _ALLOWED_STAT_COLS:
            val = r.get(col)
            if not _missing(val):
                acc[col] += float(val)
    games = list(by_game.values())
    if n is not None:
        # Most-recent-n by week -- re-derive game order from the rows rather than assuming
        # by_game's dict insertion order is chronological.
        game_weeks = {r["game_id"]: r["week"] for r in rows if r.get("game_id") is not None}
        ordered_ids = sorted(game_weeks, key=lambda gid: game_weeks[gid], reverse=True)[:n]
        games = [by_game[gid] for gid in ordered_ids if gid in by_game]
    if not games:
        return {}
    return {col: sum(g[col] for g in games) / len(games) for col in _ALLOWED_STAT_COLS}


def get_player_history_vs_opponent(player_id, opp_name: str, before_date: str,
                                   max_games: int = 10) -> List[Dict]:
    """BUILT DIRECTLY ON REQUEST, adapting nfl_engine.get_player_history_vs_opponent's own
    proven approach (see its docstring for the full head-to-head reasoning -- identical concern
    applies here). This player's stats in every game THIS SEASON their team has played against
    one specific opponent, most recent first. Genuinely likely to come back EMPTY more often
    than not -- most FBS opponents meet exactly once a season (conference/rivalry games
    sometimes twice), unlike a balanced round-robin schedule. That's the honest, common case
    here, not the exception -- reported honestly, never padded with a guess or a prior season's
    roster (a reshuffled college roster the year before tells you less than nothing reliable).

    opp_name: the real school name string (e.g. "Alabama"), matching get_team_allowed_stats'
    own convention -- NOT a numeric team_id, since NCAAF's own per-game cache stores
    opponent_team as a name, unlike NFL's abbreviation-keyed data."""
    season = _infer_season(before_date)
    if season is None:
        return []
    schedule = get_schedule(season)
    week = _resolve_week(schedule, before_date)
    if week is None:
        return []
    rows = [r for r in ND.load_player_game_stats()
           if str(r.get("player_id")) == str(player_id) and r.get("week") is not None
           and r["week"] < week and r.get("opponent_team") == opp_name]
    rows.sort(key=lambda r: r["week"], reverse=True)
    return rows[:max_games]


def get_team_rest_info(team_name: str, before_date: str) -> Dict[str, Any]:
    """BUILT DIRECTLY ON REQUEST, adapting nfl_engine.get_team_rest_info's own real intent to
    NCAAF's genuinely different data shape -- a REAL, CONFIRMED DIFFERENCE, not a guess: CFBD's
    own schedule has no pre-computed home_rest/away_rest fields the way nflreadpy's does (see
    ncaaf_data._SCHEDULE_COLUMNS' own real, confirmed column list), so this computes days-since-
    last-game directly from start_date, rather than reading a field that doesn't exist here.

    \"is_short_week\" is DELIBERATELY OMITTED, not silently defaulted to False -- NFL's own
    definition (a Thursday game after a Sunday one, ~4 days rest) is a real, specific NFL
    scheduling pattern that has no honest FBS equivalent; college football is overwhelmingly
    Saturday games, and manufacturing a "short week" threshold with no real basis to compare it
    against would be a guess dressed up as a signal. rest_days alone is the honest, real value
    here."""
    empty: Dict[str, Any] = {"rest_days": None, "last_game_date": None, "last_opp_name": None}
    season = _infer_season(before_date)
    if season is None:
        return empty
    schedule = get_schedule(season)
    week = _resolve_week(schedule, before_date)
    if week is None:
        return empty
    team_games = [g for g in schedule if g.get("week") is not None and g["week"] < week and
                 (g.get("home_team") == team_name or g.get("away_team") == team_name)
                 and g.get("start_date")]
    if not team_games:
        return empty
    last = max(team_games, key=lambda g: g["week"])
    is_home = last.get("home_team") == team_name
    opp = last.get("away_team") if is_home else last.get("home_team")
    try:
        last_dt = datetime.fromisoformat(str(last["start_date"]).replace("Z", "+00:00"))
        target_dt = datetime.fromisoformat(before_date if "T" in before_date else before_date + "T00:00:00+00:00")
        rest_days = (target_dt.date() - last_dt.date()).days
    except (ValueError, TypeError, KeyError):
        rest_days = None
    return {"rest_days": rest_days, "last_game_date": last.get("start_date"), "last_opp_name": opp}


# BUILT DIRECTLY ON REQUEST, extending _ALLOWED_STAT_COLS' own established pattern to touchdown
# columns -- a REAL, HONEST, FLAGGED UNCERTAINTY, not a confirmed fact: unlike passing_YDS/
# rushing_YDS/receiving_REC/receiving_YDS (all confirmed present in this module's own earlier,
# live-run testing), these TD column names are a PLAUSIBLE, NOT YET LIVE-VERIFIED guess, built
# by extrapolating CFBD's own confirmed "{category}_{statType}" naming convention (see
# refresh_player_game_stats' own docstring) to touchdowns -- passing_TD/rushing_TD/receiving_TD.
# CFBD's API isn't reachable from this build environment (see sports.py's own NCAAF entry for
# the same real limitation QB Lab already carries), so this is the same "first real live load is
# the actual verification step" posture already established elsewhere on this platform, not a
# claim these column names are confirmed correct.
_TD_STAT_COLS = {"passing": "passing_TD", "rushing": "rushing_TD", "receiving": "receiving_TD"}


def _get_team_td_stat_allowed(team: str, before_date: str, td_col: str,
                              n: Optional[int] = None) -> Optional[float]:
    """Shared real implementation behind get_team_tds_allowed/get_team_passing_tds_allowed/
    get_team_rushing_tds_allowed -- same real by-game grouping as get_team_allowed_stats above,
    just for one specific TD column rather than the fixed _ALLOWED_STAT_COLS set, since a caller
    needs either one specific TD type or all three combined (get_team_tds_allowed sums them)."""
    season = _infer_season(before_date)
    if season is None:
        return None
    schedule = get_schedule(season)
    week = _resolve_week(schedule, before_date)
    if week is None:
        return None
    rows = [r for r in ND.load_player_game_stats()
           if r.get("opponent_team") == team and r.get("week") is not None and r["week"] < week]
    if not rows:
        return None
    by_game: Dict[object, float] = {}
    for r in rows:
        gid = r.get("game_id")
        val = r.get(td_col)
        if _missing(val):
            continue
        by_game[gid] = by_game.get(gid, 0.0) + float(val)
    if n is not None:
        game_weeks = {r["game_id"]: r["week"] for r in rows if r.get("game_id") is not None}
        ordered_ids = sorted(game_weeks, key=lambda gid: game_weeks[gid], reverse=True)[:n]
        by_game = {gid: v for gid, v in by_game.items() if gid in ordered_ids}
    if not by_game:
        return None
    return sum(by_game.values()) / len(by_game)


def get_team_passing_tds_allowed(team: str, before_date: str, n: Optional[int] = None) -> Optional[float]:
    """Average passing TDs allowed by this team's defense per game -- n=None for the whole
    season so far, n=int for just their last n games. See _TD_STAT_COLS' own docstring for the
    real, flagged uncertainty on the underlying column name."""
    return _get_team_td_stat_allowed(team, before_date, _TD_STAT_COLS["passing"], n)


def get_team_rushing_tds_allowed(team: str, before_date: str, n: Optional[int] = None) -> Optional[float]:
    """Average rushing TDs allowed by this team's defense per game. See _TD_STAT_COLS' own
    docstring for the real, flagged uncertainty on the underlying column name."""
    return _get_team_td_stat_allowed(team, before_date, _TD_STAT_COLS["rushing"], n)


def get_team_tds_allowed(team: str, before_date: str, n: Optional[int] = None) -> Optional[float]:
    """Average TOTAL touchdowns (rushing + receiving combined) allowed by this team's defense
    per game -- CORRECTED to match NFL's own real, confirmed implementation exactly (verified by
    reading nfl_engine.get_team_tds_allowed directly, not assumed): rushing + receiving, since
    this is the general, non-QB-specific Matchup Lab TD row (a skill-position player's own TDs
    come from rushing or receiving, never passing). Kept genuinely separate from
    get_team_passing_tds_allowed (the QB-specific signal), not summed together with it."""
    rushing = get_team_rushing_tds_allowed(team, before_date, n)
    receiving = _get_team_td_stat_allowed(team, before_date, _TD_STAT_COLS["receiving"], n)
    if rushing is None and receiving is None:
        return None
    return (rushing or 0.0) + (receiving or 0.0)


def _get_league_average_allowed(before_date: str, stat_col: str) -> float:
    """League-wide average of `stat_col` allowed per team-game, up through (not including) the
    week before_date resolves to -- the neutral baseline get_team_allowed_stats' own per-opponent
    number gets compared against for a matchup factor. Same "group by (opponent_team, game),
    average across games" construction as get_team_allowed_stats, just not restricted to one
    team first. Deliberately season-wide only, not a recent-N-games version: a league-wide
    "recent" baseline is genuinely ambiguous (recent for WHICH teams' games?) in a way a single
    team's own recent-N-games isn't -- same reasoning nfl_engine's own version documents."""
    season = _infer_season(before_date)
    if season is None:
        return 0.0
    schedule = get_schedule(season)
    week = _resolve_week(schedule, before_date)
    if week is None:
        return 0.0
    rows = [r for r in ND.load_player_game_stats()
           if r.get("week") is not None and r["week"] < week]
    if not rows:
        return 0.0
    # Group by (opponent_team, game_id), NOT game_id alone -- a real bug caught by testing
    # against realistic two-sided data: grouping by game_id alone sums BOTH teams' offensive
    # output for that game into one number, double-counting rather than isolating each defense's
    # own allowed total. This matches nfl_engine's own (opponent_team, week) grouping semantic,
    # just keyed by game_id instead of week (more robust here -- see get_team_allowed_stats'
    # own reasoning for using game_id, not week, as the per-game key).
    by_defense_game: Dict[tuple, float] = {}
    for r in rows:
        val = r.get(stat_col)
        if _missing(val):
            continue
        key = (r.get("opponent_team"), r.get("game_id"))
        by_defense_game[key] = by_defense_game.get(key, 0.0) + float(val)
    if not by_defense_game:
        return 0.0
    return sum(by_defense_game.values()) / len(by_defense_game)


def get_league_average_pass_yards_allowed(before_date: str) -> float:
    """League-wide average pass yards allowed per team-game -- see _get_league_average_allowed's
    own docstring for the full reasoning (season-wide only, not a recent-N-games version)."""
    return _get_league_average_allowed(before_date, "passing_YDS")


def get_league_average_rush_yards_allowed(before_date: str) -> float:
    """League-wide average rush yards allowed per team-game -- the baseline QB Lab's matchup-
    adjusted Rush Yards projection compares one opponent's own allowed rate against, same role
    get_league_average_pass_yards_allowed plays for the Pass Yards projection."""
    return _get_league_average_allowed(before_date, "rushing_YDS")


def player_row(player: Dict, team: str, opp: str, game_label: str, game_date: Optional[str],
              stats_row: Optional[Dict], team_games_played: int,
              opp_id: Optional[str] = None, team_id: Optional[str] = None,
              recent_games: Optional[List[Dict]] = None) -> Optional[Dict]:
    """Flat row for one player on the slate. None if the player doesn't clear ANY position-
    relevant rotation floor, or has no season-stat row to project from at all -- same "filter
    no-real-role noise off the slate" purpose every other sport's engine has, see config_ncaaf.py
    for the specific thresholds."""
    raw_position = player.get("position")
    position = "" if _missing(raw_position) else str(raw_position).upper()
    markets = _MARKETS_FOR_POSITION.get(position)
    if not markets or not stats_row or team_games_played <= 0:
        return None

    def per_game(col: str) -> float:
        val = stats_row.get(col)
        if _missing(val):
            return 0.0
        return float(val) / team_games_played

    touches = per_game("rushing_CAR") + per_game("receiving_REC")

    cleared_markets = []
    for mkey in markets:
        _stat_col, _disp, floor_col, floor_val = _MARKET_SPEC[mkey]
        rate = touches if floor_col == "_touches" else per_game(floor_col)
        if rate >= floor_val:
            cleared_markets.append(mkey)
    if not cleared_markets:
        return None

    row = {
        "Player": player.get("name"), "Team": team, "GameLabel": game_label, "Opp": opp,
        "Position": position,
        "PassYds": round(per_game("passing_YDS"), 1), "RushYds": round(per_game("rushing_YDS"), 1),
        "Receptions": round(per_game("receiving_REC"), 1),
        "RecYds": round(per_game("receiving_YDS"), 1),
        # private fields consumed by ncaaf_projections.py -- _recent_games is real per-game data
        # when available (see player_recent_games above), None when refresh_player_game_stats
        # hasn't been run yet or this player/week has no cached rows; ncaaf_projections.py falls
        # back to the season-average parametric approach in that case, same graceful-degradation
        # posture as everything else in this module.
        "_pid": player.get("id"), "_stats_row": stats_row, "_team_games_played": team_games_played,
        "_recent_games": recent_games or [],
        "_game_date": game_date, "_opp_id": opp_id, "_team_id": team_id, "_markets": cleared_markets,
    }
    return row


# --------------------------------------------------------------------------- orchestration
def build_slate(date_str: str, season: Optional[int] = None) -> Tuple[List[Dict], List[Dict]]:
    """Fetch and assemble the full NCAAF (FBS) slate for whichever week date_str resolves into.

    Returns (rows, meta), matching every other sport's engine contract -- Edge Board/Best Bets/
    Matchup Lab don't need to know NCAAF's slate is weekly under the hood, same as NFL.

    season defaults to _infer_season(date_str)."""
    if season is None:
        season = _infer_season(date_str)
        if season is None:
            _diag(f"build_slate({date_str}): could not infer season from date_str, aborting")
            return [], []

    schedule = get_schedule(season)
    if not schedule:
        _diag(f"build_slate({date_str}): no cached schedule for season {season} -> nothing to build")
        return [], []

    week = _resolve_week(schedule, date_str)
    if week is None:
        _diag(f"build_slate({date_str}): could not resolve a week from the cached schedule")
        return [], []

    games = games_for_week(schedule, week)
    if not games:
        _diag(f"build_slate({date_str}): resolved to week {week} but 0 games found")
        return [], []

    roster = ND.load_rosters()
    if not roster:
        _diag(f"build_slate({date_str}): resolved to week {week}, but the roster cache is empty")
        return [], []
    roster_by_team: Dict[str, List[Dict]] = {}
    for p in roster:
        roster_by_team.setdefault(p.get("team"), []).append(p)

    stats_by_id, stats_by_name_team = _stats_by_id_and_name(season)
    id_join_misses = 0
    all_stats_rows = list(stats_by_id.values()) or list(stats_by_name_team.values())
    stats_season = next((r.get("season") for r in all_stats_rows if r.get("season") is not None), season)
    if stats_season != season:
        _diag(f"build_slate({date_str}): cached player stats are from season {stats_season}, "
             f"not the target season {season} (ncaaf_data's own year-fallback) -- using "
             f"season {stats_season}'s own game counts as the per-game-rate denominator")

    def _lookup_stats(player: Dict) -> Optional[Dict]:
        nonlocal id_join_misses
        pid = player.get("id")
        if pid is not None and str(pid) in stats_by_id:
            return stats_by_id[str(pid)]
        row = stats_by_name_team.get((_normalize_name(player.get("name")), player.get("team")))
        if row is not None:
            id_join_misses += 1
        return row

    meta: List[Dict] = []
    rows: List[Dict] = []
    for g in games:
        label = f"{g['away_team']} @ {g['home_team']}"
        meta.append({"label": label, "away_name": g["away_team"], "home_name": g["home_team"],
                    "game_date": g.get("start_date"), "week": week,
                    "home_id": g.get("home_id"), "away_id": g.get("away_id"),
                    "venue": g.get("venue"), "neutral_site": g.get("neutral_site")})
        for team, opp, opp_id, team_id in (
            (g["home_team"], g["away_team"], g.get("away_id"), g.get("home_id")),
            (g["away_team"], g["home_team"], g.get("home_id"), g.get("away_id")),
        ):
            team_games = _team_games_played_for_stats_season(schedule, stats_season, season, team, week)
            for player in roster_by_team.get(team, []):
                stats_row = _lookup_stats(player)
                pid = player.get("id")
                recent = player_recent_games(pid, week) if not _missing(pid) else []
                row = player_row(player, team, opp, label, g.get("start_date"), stats_row,
                                 team_games, opp_id=opp_id, team_id=team_id, recent_games=recent)
                if row is not None:
                    rows.append(row)

    if id_join_misses:
        _diag(f"build_slate({date_str}): {id_join_misses} player(s) matched by name+team, not id "
             f"-- worth checking if roster.id and player_stats.player_id share an id space at all")
    _diag(f"build_slate({date_str}): season {season} week {week}, {len(games)} game(s) -> "
         f"{len(rows)} player(s) cleared a rotation floor")
    return rows, meta


# ============================================================================ Drive-level simulation
# BUILT DIRECTLY ON REQUEST, second piece of the drive-level simulation build (see ncaaf_data.
# refresh_drives' own docstring for the full reasoning behind the new /drives endpoint this
# section builds on). This is the FIRST genuinely new data source this NCAAF build has added --
# everything else built on data this platform already had cached and proven.

def compute_drive_points(game_drives: List[Dict]) -> List[Dict]:
    """The single most important, easiest-to-get-wrong piece of this whole build, done once here
    rather than left for every future caller to reimplement (and possibly get wrong). Adds two
    real, honest fields to each drive: "points_this_drive" (points the OFFENSE scored on this
    specific drive -- TD/FG/safety they earned) and "defensive_points_this_drive" (points the
    DEFENSE scored during this same drive -- a pick-six, a fumble return TD, a blocked-punt
    return -- genuinely rare, but real, and a naive version of this function that only tracks
    offense_score deltas would silently miss these entirely, since the scoring team is never
    listed as "offense" on that drive).

    THE REAL, CONFIRMED DATA-SHAPE ISSUE THIS SOLVES: offense_score/defense_score are CUMULATIVE
    running totals as of the end of that drive, not points scored on it (see refresh_drives' own
    docstring). Getting the real per-drive point value requires comparing THIS team's own score
    now to the LAST time this exact team's own score was known -- not just the immediately
    preceding drive (which was the other team's own possession), and not just this team's own
    previous OFFENSIVE drive either, since a defensive score also changes their running total.

    Sorts by drive_number (the one unambiguous chronological-order field within a single game --
    start_period+clock is a real, plausible alternative but drive_number is simpler and, per the
    real sources this build's data shape is corroborated against, reliably present). Expects
    game_drives to already be filtered to ONE real game -- mixing drives from different games
    would silently corrupt the running-score tracking, since team names aren't unique to a game."""
    sorted_drives = sorted(game_drives, key=lambda d: d.get("drive_number") or 0)
    last_score: Dict[str, float] = {}
    out: List[Dict] = []
    for d in sorted_drives:
        offense, defense = d.get("offense"), d.get("defense")
        off_score_now, def_score_now = d.get("offense_score"), d.get("defense_score")

        off_points = None
        if offense and off_score_now is not None and not _missing(off_score_now):
            off_points = float(off_score_now) - last_score.get(offense, 0.0)
            last_score[offense] = float(off_score_now)

        def_points = None
        if defense and def_score_now is not None and not _missing(def_score_now):
            def_points = float(def_score_now) - last_score.get(defense, 0.0)
            last_score[defense] = float(def_score_now)

        out.append({**d, "points_this_drive": off_points, "defensive_points_this_drive": def_points})
    return out


def _outcome_for_drive(points_this_drive: Optional[float], defensive_points_this_drive: Optional[float]) -> Optional[str]:
    """One drive's own outcome, bucketed into the real, standard categories a possession
    simulation needs: touchdown / field_goal / safety / defensive_score / no_score. Honest None
    (never a guessed bucket) when the real point value isn't known for this drive at all.

    6 or 7 or 8 real points -> touchdown (7 is the modal case -- a made extra point -- but 6 (a
    missed/blocked PAT or a real, deliberate 2pt-conversion miss) and 8 (a real, made 2pt
    conversion) are both genuinely possible and must not be misclassified as anything else, since
    this same 6-8 range is exactly the ambiguity a naive "== 7" check would get wrong)."""
    if defensive_points_this_drive and defensive_points_this_drive > 0:
        return "defensive_score"
    if points_this_drive is None:
        return None
    if points_this_drive in (6, 7, 8):
        return "touchdown"
    if points_this_drive == 3:
        return "field_goal"
    if points_this_drive == 2:
        return "safety"
    if points_this_drive == 0:
        return "no_score"
    return "no_score"   # a real, negative or otherwise unexpected value -- treated as no real score for this team, not silently dropped


def get_team_drive_outcomes(team_name: str, before_date: str, n: Optional[int] = None) -> List[str]:
    """This team's own real, bucketed drive outcomes (touchdown/field_goal/safety/
    defensive_score/no_score) across every real completed drive on offense before before_date --
    n=None for the whole season so far, n=int for their last n real games' worth of drives. The
    real, direct input a possession-level Monte Carlo simulation needs: real empirical rates,
    not an assumed distribution.

    Groups drives by game_id first, since compute_drive_points' own running-score tracking is
    only valid WITHIN one real game -- computing it across multiple games at once would silently
    corrupt the delta math (see compute_drive_points' own docstring)."""
    season = _infer_season(before_date)
    if season is None:
        return []
    schedule = get_schedule(season)
    week = _resolve_week(schedule, before_date)
    if week is None:
        return []
    rows = [r for r in ND.load_drives()
           if r.get("offense") == team_name and r.get("week") is not None and r["week"] < week]
    if not rows:
        return []
    by_game: Dict[object, List[Dict]] = {}
    for r in rows:
        by_game.setdefault(r.get("game_id"), []).append(r)

    if n is not None:
        game_weeks = {gid: g[0]["week"] for gid, g in by_game.items()}
        ordered_ids = sorted(game_weeks, key=lambda gid: game_weeks[gid], reverse=True)[:n]
        by_game = {gid: g for gid, g in by_game.items() if gid in ordered_ids}

    outcomes: List[str] = []
    for gid, game_drives in by_game.items():
        with_points = compute_drive_points(game_drives)
        for d in with_points:
            if d.get("offense") != team_name:
                continue
            outcome = _outcome_for_drive(d.get("points_this_drive"), d.get("defensive_points_this_drive"))
            if outcome is not None:
                outcomes.append(outcome)
    return outcomes

