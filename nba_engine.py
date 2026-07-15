"""
nba_engine.py — NBA data layer using ESPN's public (unofficial) API.

Provides the same contract as wnba_engine.py (see that module's docstring for the full data-
source history that led to this shape):
  - get_schedule(date_str) -> games scheduled for a date
  - get_team_roster(team_id) -> a team's roster
  - get_player_recent_games(player_id, last_n, team_id, before_date) -> last N game logs
    (PTS/REB/AST/FG3M/MIN)
  - build_slate(date_str) -> (rows, meta), matching the platform's cross-sport engine contract
    (see mlb_engine.build_slate / sports.py's Sport.engine)

BUILT AS A COPY-ADAPT OF wnba_engine.py, per the plan laid out in basketball_engine.py's module
docstring: rather than guessing NBA's endpoint quirks in advance, this follows the exact same
ESPN-basketball-API shape wnba_engine.py already proved out (site.api.espn.com for schedule/
roster/injuries, cdn.espn.com/core/{league}/boxscore for the actual box score, since ESPN's "site"
API family was confirmed for WNBA to return team-level stats only, no player-level, on this same
CDN vs. site distinction — untested for NBA specifically, so this module fails soft and logs
loudly, same discipline as WNBA's build, rather than assuming the shortcut is safe here too).

The four pieces WNBA proved out the hard way (pace/possession math, rest calc, blowout tag,
injury parsing) are NOT reimplemented here — this module thin-wraps basketball_engine.py for
those, the same way wnba_engine.py does. See basketball_engine.py's module docstring for why the
rest (schedule/roster/player-log fetching, build_slate's orchestration) is NOT similarly shared
yet: those parts' NBA-specific quirks, if any, aren't known until tested against a live NBA slate.

NOT YET LIVE-CONFIRMED (flagged honestly, same posture as WNBA's build before its own live
verification): the CDN boxscore endpoint's shape for NBA specifically (cdn.espn.com/core/nba/
boxscore) — a generic cdn.espn.com/core/{sport}/boxscore?xhr=1&gameId={id} pattern is documented
and confirmed live for NFL, and the team-level statistics[] combo-key naming
("fieldGoalsMade-fieldGoalsAttempted") was independently confirmed live for an NBA game via a
different endpoint (site.web.api.espn.com's /summary) — but the exact CDN response's player-level
shape for NBA hasn't been hit live the way WNBA's was (with real responses pasted back during that
build). Diagnostic dumps carry over from basketball_engine.py/this module to surface a wrong guess
loudly rather than silently returning empty results.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

import config_nba as CFG
import basketball_engine as BB

logger = logging.getLogger(__name__)

SITE_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; H2Sports/1.0)"}
_TIMEOUT = 15

# Simple per-process cache so fetching 10 games' worth of boxscores for a roster costs one request
# per game, not one per player (every player on both teams shares the same game's boxscore). No
# TTL — fine for the lifetime of a single slate build. Tests should not rely on this persisting.
_response_cache: Dict[Tuple[str, Tuple], Optional[Dict]] = {}
_diag_seen: set = set()   # keys already printed about — avoids repeating the same diagnostic line


def _diag(msg: str) -> None:
    """Stage-by-stage visibility for the ONE failure mode logging.exception can't catch: every
    request succeeding (200 OK, valid JSON) while the parsing code quietly extracts nothing,
    because the real shape doesn't match what was coded against. print() (not the `logging`
    module) — Streamlit Cloud's log viewer reliably captures stdout, per the same finding that
    shaped wnba_engine.py's identical helper."""
    print(f"[NBA] {msg}", flush=True)


def _get_json(url: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """Shared fetch helper: returns the parsed JSON body, or None on any failure (bad status,
    timeout, malformed JSON). Every caller below treats None the same way it treats an empty
    result — fail soft, log, move on — so one bad request can't take down the whole slate build."""
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("NBA ESPN API request failed: %s params=%s", url, params)
        return None


def _get_json_cached(url: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """_get_json, but de-duplicated within this process — see _response_cache above."""
    key = (url, tuple(sorted((params or {}).items())))
    if key not in _response_cache:
        _response_cache[key] = _get_json(url, params)
    return _response_cache[key]


# --------------------------------------------------------------------------- schedule
def get_schedule(date_str: str) -> List[Dict[str, Any]]:
    """Games scheduled for date_str (YYYY-MM-DD). One dict per game with both team ids/names/
    abbreviations — all pulled directly from the scoreboard response, no separate team lookup
    needed."""
    espn_date = date_str.replace("-", "")   # ESPN wants YYYYMMDD; we use YYYY-MM-DD everywhere else
    data = _get_json(f"{SITE_API}/scoreboard", params={"dates": espn_date})
    if not data:
        _diag(f"get_schedule({date_str}): scoreboard fetch returned nothing (request failed)")
        return []
    if "events" not in data:
        _diag(f"get_schedule({date_str}): response had no 'events' key — keys were {list(data.keys())}")

    games = []
    for event in data.get("events", []):
        comps = event.get("competitions") or []
        if not comps:
            continue
        competitors = comps[0].get("competitors") or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        try:
            games.append({
                "gameId": event.get("id"),
                "game_date": event.get("date"),
                "home_id": int(home["team"]["id"]),
                "home_name": home["team"].get("displayName", "Unknown"),
                "home_abbr": home["team"].get("abbreviation"),
                "away_id": int(away["team"]["id"]),
                "away_name": away["team"].get("displayName", "Unknown"),
                "away_abbr": away["team"].get("abbreviation"),
            })
        except (KeyError, TypeError, ValueError):
            logger.exception("NBA scoreboard event had an unexpected shape: %s", event.get("id"))
            continue
    _diag(f"get_schedule({date_str}): {len(games)} game(s) found ({len(data.get('events', []))} raw events)")
    return games


def team_abbrs_from_meta(meta: List[Dict]) -> Dict[int, str]:
    """{team_id: abbreviation} for every team on the slate, derived from build_slate's own
    `meta` return value — zero extra network cost. Entries with no abbreviation in the source
    response are simply omitted, not guessed."""
    out: Dict[int, str] = {}
    for g in meta:
        if g.get("home_abbr"):
            out[g["home_id"]] = g["home_abbr"]
        if g.get("away_abbr"):
            out[g["away_id"]] = g["away_abbr"]
    return out


# --------------------------------------------------------------------------- rosters
def get_team_roster(team_id: int) -> List[Dict[str, Any]]:
    """A team's roster: [{id, name}, ...]. ESPN groups the roster by position (`athletes` is a
    list of {position, items: [...]} groups) — flattened here into one player list, handling both
    the grouped shape and a flat player-list shape (WNBA's real response used the latter; NBA's
    hasn't been confirmed either way, so both are handled defensively rather than guessing which
    one applies). Empty list (not an exception) on any fetch failure, so one bad team doesn't take
    down the whole build."""
    data = _get_json(f"{SITE_API}/teams/{team_id}/roster")
    if not data:
        _diag(f"get_team_roster({team_id}): roster fetch returned nothing (request failed)")
        return []
    if "athletes" not in data:
        _diag(f"get_team_roster({team_id}): response had no 'athletes' key — keys were {list(data.keys())}")
    out = []
    flat_count = 0
    for entry in data.get("athletes", []):
        items = entry.get("items")
        if items is not None:
            candidates = items
        else:
            candidates = [entry]
            flat_count += 1
        for item in candidates:
            pid = item.get("id")
            if pid is None:
                continue
            try:
                out.append({"id": int(pid), "name": item.get("displayName", "Unknown")})
            except (TypeError, ValueError):
                continue
    if flat_count and flat_count == len(data.get("athletes", [])):
        _diag(f"get_team_roster({team_id}): 'athletes' was a flat player list, not grouped by position")
    _diag(f"get_team_roster({team_id}): {len(out)} player(s) found")
    return out


# --------------------------------------------------------------------------- recent form
# Thin alias — the actual logic lives in basketball_engine.py (shared with wnba_engine.py).
_parse_stat_value = BB.parse_stat_value


def get_team_recent_game_ids(team_id: int, before_date: str,
                             n: int = CFG.RECENT_GAMES_N, days_back: int = 45) -> List[Dict[str, Any]]:
    """A team's last n COMPLETED games STRICTLY BEFORE before_date (YYYY-MM-DD), most recent
    first: [{"gameId", "date", "opp_id", "opp_name"}, ...]. Thin NBA wrapper around
    basketball_engine.get_team_recent_game_ids (shared with wnba_engine.py) — supplies NBA's
    SITE_API and this module's own cache/diag objects.

    days_back defaults to 45 (comfortably covers n=10 games at an 82-game-season pace — NBA teams
    play roughly 3-4 games/week, similar cadence to WNBA's, so the same default carries over)."""
    return BB.get_team_recent_game_ids(team_id, before_date, SITE_API, _get_json_cached, _diag,
                                       n=n, days_back=days_back, diag_seen=_diag_seen)


CDN_API = "https://cdn.espn.com/core/nba/boxscore"


def get_game_boxscore(game_id: str) -> Dict[int, Dict[str, float]]:
    """{player_id: {pts, reb, ast, fg3m, min}} for every player who appeared in a game — one
    fetch covers both teams, shared across every player on the slate who played that game.

    DATA SOURCE: cdn.espn.com, not site.api.espn.com — following WNBA's own build here, where
    both "site" API subdomains were confirmed live to return only team-level stats, not
    player-level, forcing the CDN endpoint instead. NOT independently confirmed for NBA yet — the
    generic cdn.espn.com/core/{sport}/boxscore?xhr=1&gameId={id} pattern is documented and
    confirmed live for NFL, and this module fails soft (empty result, logged) with a diagnostic
    dump if the real shape here turns out to differ, same discipline as WNBA's build before its
    own live verification."""
    data = _get_json_cached(CDN_API, params={"xhr": "1", "gameId": game_id})
    if not data:
        if game_id not in _diag_seen:
            _diag(f"get_game_boxscore({game_id}): CDN fetch returned nothing")
            _diag_seen.add(game_id)
        return {}
    out: Dict[int, Dict[str, float]] = {}
    gp = data.get("gamepackageJSON") or {}
    if "gamepackageJSON" not in data:
        if game_id not in _diag_seen:
            _diag(f"get_game_boxscore({game_id}): response had no 'gamepackageJSON' key — keys were {list(data.keys())}")
    box = gp.get("boxscore") or {}
    player_groups = box.get("players") or []
    for player_group in player_groups:
        for stat_group in player_group.get("statistics", []):
            names = stat_group.get("names") or []
            for a in stat_group.get("athletes", []):
                if a.get("didNotPlay") or not names:
                    continue
                athlete = a.get("athlete") or {}
                pid = athlete.get("id")
                stats = a.get("stats") or []
                if pid is None or not stats:
                    continue
                try:
                    pid_int = int(pid)
                except (TypeError, ValueError):
                    continue
                row = {n: _parse_stat_value(v) for n, v in zip(names, stats)}
                out[pid_int] = {
                    "pts": row.get("PTS", 0.0),
                    "reb": row.get("REB", 0.0),
                    "ast": row.get("AST", 0.0),
                    "fg3m": row.get("3PT", 0.0),
                    "min": row.get("MIN", 0.0),
                }

    if not out and player_groups and "_cdn_stat_shape_dump" not in _diag_seen:
        _diag_seen.add("_cdn_stat_shape_dump")
        pg0 = player_groups[0]
        _diag(f"get_game_boxscore CDN shape dump: player_group keys = {list(pg0.keys())}")
        stats_val = pg0.get("statistics")
        _diag(f"get_game_boxscore CDN shape dump: player_group['statistics'] = "
             f"{type(stats_val).__name__}, len={len(stats_val) if hasattr(stats_val, '__len__') else 'n/a'}")
        if stats_val:
            sg0 = stats_val[0]
            _diag(f"get_game_boxscore CDN shape dump: statistics[0] keys = "
                 f"{list(sg0.keys()) if isinstance(sg0, dict) else type(sg0).__name__}")

    if game_id not in _diag_seen:
        _diag(f"get_game_boxscore({game_id}): {len(out)} player(s) extracted "
             f"({len(player_groups)} player group(s) in response)")
        _diag_seen.add(game_id)
    return out


# Thin alias — the actual logic lives in basketball_engine.py.
_find_team_stat = BB.find_team_stat


def get_game_team_totals(game_id: str) -> Dict[int, Dict[str, float]]:
    """{team_id: {pts, reb, ast, fg3m, poss}} TEAM-level totals for a game. Thin NBA wrapper
    around basketball_engine.get_game_team_totals (shared with wnba_engine.py) — supplies NBA's
    CDN_API and this module's own cache/diag objects."""
    return BB.get_game_team_totals(game_id, CDN_API, _get_json_cached, _diag, diag_seen=_diag_seen)


def get_team_recent_allowed_stats(team_id: int, before_date: str,
                                  n: int = CFG.RECENT_GAMES_N, days_back: int = 45) -> Dict[str, float]:
    """Average PTS/REB/AST/FG3M this team has ALLOWED over their last n completed games, plus
    "poss" (opponent's own estimated possessions in those games, for pace-adjustment downstream).
    Same aggregation as wnba_engine.py's version — kept as its own small implementation here
    (rather than delegating to basketball_engine.get_team_recent_allowed_stats) so it calls this
    module's own get_team_recent_game_ids/get_game_team_totals by name, keeping this module's
    functions independently monkeypatch-able the same way wnba_engine.py's are."""
    games = get_team_recent_game_ids(team_id, before_date, n, days_back=days_back)
    totals = {"pts": [], "reb": [], "ast": [], "fg3m": [], "poss": []}
    for g in games:
        opp_id = g.get("opp_id")
        if opp_id is None:
            continue
        try:
            opp_id = int(opp_id)
        except (TypeError, ValueError):
            continue
        game_totals = get_game_team_totals(g["gameId"])
        opp_totals = game_totals.get(opp_id)
        if opp_totals:
            for k in totals:
                totals[k].append(opp_totals.get(k, 0.0))
    return {k: (sum(v) / len(v) if v else 0.0) for k, v in totals.items()}


def get_team_rest_info(team_id: int, before_date: str, days_back: int = 10) -> Dict[str, Any]:
    """Rest context for a team heading into `before_date`: days since their last completed game,
    and whether tonight is a back-to-back. Same small wrapper pattern as
    get_team_recent_allowed_stats above — calls get_team_recent_game_ids by name."""
    games = get_team_recent_game_ids(team_id, before_date, n=1, days_back=days_back)
    empty = {"rest_days": None, "is_back_to_back": False, "last_game_date": None, "last_opp_name": None}
    if not games:
        return empty
    last = games[0]
    last_date_str = (last.get("date") or "")[:10]
    if not last_date_str:
        return empty
    try:
        d_before = datetime.strptime(before_date, "%Y-%m-%d")
        d_last = datetime.strptime(last_date_str, "%Y-%m-%d")
    except ValueError:
        return empty
    rest_days = (d_before - d_last).days
    return {"rest_days": rest_days, "is_back_to_back": rest_days <= 1,
            "last_game_date": last_date_str, "last_opp_name": last.get("opp_name")}


def get_team_injuries(team_abbr: str) -> List[Dict[str, Any]]:
    """Team injury report for one team, by ESPN abbreviation (e.g. "ATL"). Thin NBA wrapper around
    basketball_engine.get_team_injuries — CONFIRMED LIVE for NBA specifically during the original
    scoping pass (site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries?team=ATL returned
    real, current per-player injury records), unlike get_game_boxscore's CDN endpoint above."""
    return BB.get_team_injuries(team_abbr, SITE_API, _get_json_cached, _diag, diag_seen=_diag_seen)


def get_player_results(date_str: str) -> Dict[int, Dict[str, float]]:
    """Actual per-player results for all games on date_str, keyed by player id — same contract as
    mlb_engine.get_player_results, so retro.py's grading logic works identically for either sport."""
    results: Dict[int, Dict[str, float]] = {}
    for g in get_schedule(date_str):
        box = get_game_boxscore(g["gameId"])
        for pid, rec in box.items():
            results.setdefault(pid, {}).update(rec)
    return results


def get_player_recent_games(player_id: int, last_n: int = CFG.RECENT_GAMES_N,
                            team_id: Optional[int] = None,
                            before_date: Optional[str] = None, days_back: int = 45) -> List[Dict[str, float]]:
    """Last N game logs for a player: [{pts, reb, ast, fg3m, min, opp, date}, ...], most recent
    first. Requires team_id and before_date (build_slate always supplies both)."""
    if team_id is None or before_date is None:
        return []
    games_info = get_team_recent_game_ids(team_id, before_date, last_n, days_back=days_back)
    out = []
    for g in games_info:
        box = get_game_boxscore(g["gameId"])
        line = box.get(player_id)
        if line:
            out.append({**line, "opp": g.get("opp_name"), "date": g.get("date")})
    return out[:last_n]


# 2026-27 NBA regular season start. NOT YET CONFIRMED LIVE — flagged honestly: this build happened
# during the NBA's off-season (2026-07-15; the 2025-26 season ran Oct 21, 2025 - Apr 12, 2026,
# confirmed live), and the 2026-27 schedule wasn't officially set at build time. "2026-10-01" is a
# placeholder aligned with the league's typical mid-to-late-October openers (2025-26 opened Oct
# 21), not a confirmed date. MUST be re-verified against NBA.com/ESPN once the 2026-27 schedule is
# announced — same re-verify discipline config_wnba.TEAMS documents for its own season-boundary
# facts. get_team_recent_game_ids clips its own scan window regardless, so an off-by-a-few-weeks
# SEASON_START only affects how wide season-long scans (head-to-head, season-baseline) reach, not
# correctness.
SEASON_START = "2026-10-01"


def _days_since_season_start(before_date: str) -> int:
    try:
        return max((datetime.strptime(before_date, "%Y-%m-%d")
                   - datetime.strptime(SEASON_START, "%Y-%m-%d")).days + 1, 1)
    except ValueError:
        return 200


def get_player_season_games(player_id: int, team_id: int, before_date: str,
                            max_games: int = 82) -> List[Dict[str, float]]:
    """This player's full game log for the season so far (any opponent), most recent first —
    the baseline Matchup Lab compares a head-to-head sample against."""
    days_back = _days_since_season_start(before_date)
    return get_player_recent_games(player_id, last_n=max_games, team_id=team_id,
                                   before_date=before_date, days_back=days_back)


def get_player_history_vs_opponent(player_id: int, team_id: int, opp_id: int, before_date: str,
                                   max_games: int = 20) -> List[Dict[str, float]]:
    """This player's stats in every game THIS SEASON their team has played against one specific
    opponent, most recent first: [{pts, reb, ast, fg3m, min, opp, date}, ...]."""
    days_back = _days_since_season_start(before_date)
    games = get_team_recent_game_ids(team_id, before_date, n=82, days_back=days_back)
    matchups = []
    for g in games:
        try:
            gid_opp = int(g.get("opp_id"))
        except (TypeError, ValueError):
            continue
        if gid_opp == opp_id:
            matchups.append(g)
    out = []
    for g in matchups[:max_games]:
        box = get_game_boxscore(g["gameId"])
        line = box.get(player_id)
        if line:
            out.append({**line, "opp": g.get("opp_name"), "date": g.get("date")})
    return out


# --------------------------------------------------------------------------- pure logic (no network)
def avg_minutes(game_log: List[Dict[str, float]]) -> float:
    return (sum(g["min"] for g in game_log) / len(game_log)) if game_log else 0.0


def player_row(player: Dict, team_name: str, opp_name: str, game_label: str,
               game_date: Optional[str], game_log: List[Dict[str, float]],
               min_avg_minutes: float = CFG.MIN_AVG_MINUTES,
               opp_id: Optional[int] = None, team_id: Optional[int] = None) -> Optional[Dict]:
    """Flat row for one player on the slate. None if the player doesn't clear the rotation-
    minutes bar — filters deep-bench noise off the slate."""
    m = avg_minutes(game_log)
    if not game_log or m < min_avg_minutes:
        return None
    n = len(game_log)
    return {
        "Player": player["name"],
        "Team": team_name,
        "GameLabel": game_label,
        "Opp": opp_name,
        "AvgMin": round(m, 1),
        "PTS": round(sum(g["pts"] for g in game_log) / n, 1),
        "REB": round(sum(g["reb"] for g in game_log) / n, 1),
        "AST": round(sum(g["ast"] for g in game_log) / n, 1),
        "FG3M": round(sum(g["fg3m"] for g in game_log) / n, 1),
        # private fields consumed by nba_projections.py
        "_pid": player["id"],
        "_game_log": game_log,
        "_game_date": game_date,
        "_opp_id": opp_id,
        "_team_id": team_id,
    }


# --------------------------------------------------------------------------- orchestration
def build_slate(date_str: str, min_avg_minutes: float = CFG.MIN_AVG_MINUTES,
                last_n_games: int = CFG.RECENT_GAMES_N, max_workers: int = 8
                ) -> Tuple[List[Dict], List[Dict]]:
    """Fetch and assemble the full NBA slate concurrently.

    Returns (rows, meta), matching mlb_engine.build_slate's contract:
      rows : list of flat per-player dicts ready for a DataFrame / the projections module
      meta : list of per-game dicts (label, names, game_date)
    """
    _response_cache.clear()
    _diag_seen.clear()
    games = get_schedule(date_str)
    if not games:
        _diag(f"build_slate({date_str}): 0 games -> nothing to build, stopping here")
        return [], []

    meta: List[Dict] = []
    tasks: List[Tuple[Dict, str, str, str, Optional[str], int, int]] = []
    for g in games:
        label = f"{g['away_name']} @ {g['home_name']}"
        meta.append({"label": label, "away_name": g["away_name"], "home_name": g["home_name"],
                     "game_date": g.get("game_date"),
                     "home_id": g["home_id"], "home_abbr": g.get("home_abbr"),
                     "away_id": g["away_id"], "away_abbr": g.get("away_abbr")})
        for team_id, team_name, opp_name, opp_id in (
                (g["home_id"], g["home_name"], g["away_name"], g["away_id"]),
                (g["away_id"], g["away_name"], g["home_name"], g["home_id"])):
            for player in get_team_roster(team_id):
                tasks.append((player, team_name, opp_name, label, g.get("game_date"), team_id, opp_id))
    _diag(f"build_slate({date_str}): {len(games)} game(s) -> {len(tasks)} roster slot(s) to project")

    def fetch_one(item):
        player, team_name, opp_name, label, game_date, team_id, opp_id = item
        log = get_player_recent_games(player["id"], last_n_games, team_id=team_id,
                                      before_date=date_str)
        return player_row(player, team_name, opp_name, label, game_date, log, min_avg_minutes,
                          opp_id, team_id)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        rows = [r for r in ex.map(fetch_one, tasks) if r is not None]

    _diag(f"build_slate({date_str}): {len(rows)} player(s) cleared the {min_avg_minutes}-min "
         f"rotation bar and made the final slate (of {len(tasks)} roster slots checked)")
    return rows, meta
