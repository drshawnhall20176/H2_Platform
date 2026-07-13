"""
wnba_engine.py — WNBA data layer using nba_api (league_id='10').

Provides:
  - get_schedule(date_str) -> games scheduled for a date
  - get_team_roster(team_id) -> a team's roster
  - get_player_recent_games(player_id, last_n) -> last N game logs (PTS/REB/AST/FG3M/MIN)
  - build_slate(date_str) -> (rows, meta), matching the platform's cross-sport engine contract
    (see mlb_engine.build_slate / sports.py's Sport.engine)

Data source: nba_api (https://github.com/swar/nba_api), wrapping stats.wnba.com — free, no key,
the same "public stats API" pattern MLB (MLB Stats API) and NFL (nfl_data_py) already use here.

IMPORTANT — this module's live HTTP calls could not be exercised from the build sandbox
(stats.wnba.com is outside its network allowlist). Two specific unknowns can't be resolved without
a live response, so rather than guess a single answer, both are handled defensively:

  1. WNBA's season STRING format. WNBA-specific wrappers (wehoop's wnba_playergamelog) suggest a
     plain year ("2026"); general stats.nba.com docs (py_ball) describe a cross-year "YYYY-YY"
     shape used elsewhere on the same backend. `_season_candidates()` tries both, in that order,
     and every season-dependent fetch below stops at the first one that returns data.
  2. `LeagueGameFinder`'s date_from/date_to filters have a documented history of returning empty
     results even when used correctly (github.com/swar/nba_api/issues/95, issues/207).
     `get_schedule` therefore also falls back to pulling the whole season and filtering by date
     client-side if the server-side date filter comes back empty.

Verify against a real slate on first deploy. If a column name has drifted instead, these
functions still return empty rather than raising, which is easy to miss — the first-deploy
checklist in PLATFORM_CHECKPOINT.md covers what to check.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import config_wnba as CFG

try:
    from nba_api.stats.endpoints import leaguegamefinder, playergamelog, commonteamroster
except ImportError:
    raise ImportError("Install nba_api: pip install nba_api")

logger = logging.getLogger(__name__)


def _season_candidates() -> List[str]:
    """Season strings to try, in order, until one returns data. See module docstring."""
    primary = CFG.current_season()          # e.g. "2026"
    y = int(primary)
    cross_year = f"{y}-{str(y + 1)[-2:]}"    # e.g. "2026-27"
    return [primary, cross_year]


# --------------------------------------------------------------------------- schedule
def get_schedule(date_str: str) -> List[Dict[str, Any]]:
    """Games scheduled for date_str (YYYY-MM-DD). One dict per game with both team ids/names."""
    df = _fetch_schedule_frame(date_str)
    if df is None or df.empty:
        return []

    games: Dict[str, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        gid = row["GAME_ID"]
        is_home = "vs." in str(row.get("MATCHUP", ""))
        team_id = int(row["TEAM_ID"])
        team_name = CFG.TEAMS.get(team_id, (row.get("TEAM_NAME", "Unknown"),))[0]
        g = games.setdefault(gid, {"gameId": gid, "game_date": row.get("GAME_DATE")})
        if is_home:
            g["home_id"], g["home_name"] = team_id, team_name
        else:
            g["away_id"], g["away_name"] = team_id, team_name
    # Only keep games where both sides resolved (guards against a partial/odd API response).
    return [g for g in games.values() if "home_id" in g and "away_id" in g]


def _fetch_schedule_frame(date_str: str):
    """Tries several strategies in order and returns the first non-empty result — see the
    module docstring for why (documented LeagueGameFinder date-filter flakiness + unverifiable
    WNBA season string format). Returns None if every strategy comes back empty."""
    attempts = [dict(date_from_nullable=date_str, date_to_nullable=date_str)]   # no season guess
    for season in _season_candidates():
        attempts.append(dict(date_from_nullable=date_str, date_to_nullable=date_str, season_nullable=season))
    whole_season_attempts = [dict(season_nullable=s, season_type_nullable="Regular Season")
                             for s in _season_candidates()]

    for kwargs in attempts:
        df = _try_game_finder(kwargs)
        if df is not None and not df.empty:
            return df
    for kwargs in whole_season_attempts:
        df = _try_game_finder(kwargs)
        if df is not None and not df.empty:
            df = df[df["GAME_DATE"].astype(str).str[:10] == date_str]
            if not df.empty:
                return df
    return None


def _try_game_finder(kwargs: Dict):
    try:
        finder = leaguegamefinder.LeagueGameFinder(league_id_nullable=CFG.LEAGUE_ID, **kwargs)
        return finder.get_data_frames()[0]
    except Exception:
        logger.exception("WNBA LeagueGameFinder attempt failed: %s", kwargs)
        return None


# --------------------------------------------------------------------------- rosters
def get_team_roster(team_id: int) -> List[Dict[str, Any]]:
    """A team's roster: [{id, name}, ...]. Empty list (not an exception) on any fetch failure,
    so one bad team doesn't take down the whole slate build. Tries both season-string candidates
    (see module docstring)."""
    df = None
    for season in _season_candidates():
        try:
            roster = commonteamroster.CommonTeamRoster(
                team_id=team_id, season=season, league_id_nullable=CFG.LEAGUE_ID,
            )
            candidate = roster.get_data_frames()[0]
        except Exception:
            logger.exception("WNBA roster fetch failed for team_id=%s season=%s", team_id, season)
            continue
        if not candidate.empty:
            df = candidate
            break
    if df is None:
        return []
    out = []
    for _, r in df.iterrows():
        pid = r.get("PLAYER_ID")
        if pid is None:
            continue
        out.append({"id": int(pid), "name": r.get("PLAYER", "Unknown")})
    return out


# --------------------------------------------------------------------------- recent form
def get_player_recent_games(player_id: int, last_n: int = CFG.RECENT_GAMES_N) -> List[Dict[str, float]]:
    """Last N regular-season game logs for a player: [{pts, reb, ast, fg3m, min}, ...], most
    recent first (PlayerGameLog is already ordered that way). Empty list on any failure. Tries
    both season-string candidates (see module docstring)."""
    df = None
    for season in _season_candidates():
        try:
            log = playergamelog.PlayerGameLog(
                player_id=player_id, season=season, league_id_nullable=CFG.LEAGUE_ID,
            )
            candidate = log.get_data_frames()[0]
        except Exception:
            logger.exception("WNBA game log fetch failed for player_id=%s season=%s", player_id, season)
            continue
        if not candidate.empty:
            df = candidate
            break
    if df is None:
        return []
    out = []
    for _, r in df.iterrows():
        try:
            out.append({
                "pts": float(r.get("PTS", 0) or 0),
                "reb": float(r.get("REB", 0) or 0),
                "ast": float(r.get("AST", 0) or 0),
                "fg3m": float(r.get("FG3M", 0) or 0),
                "min": float(r.get("MIN", 0) or 0),
            })
        except (TypeError, ValueError):
            continue
    return out[:last_n]


# --------------------------------------------------------------------------- pure logic (no network)
def avg_minutes(game_log: List[Dict[str, float]]) -> float:
    return (sum(g["min"] for g in game_log) / len(game_log)) if game_log else 0.0


def player_row(player: Dict, team_name: str, opp_name: str, game_label: str,
               game_date: Optional[str], game_log: List[Dict[str, float]],
               min_avg_minutes: float = CFG.MIN_AVG_MINUTES) -> Optional[Dict]:
    """Flat row for one player on the slate (mirrors mlb_engine._hitter_row: public display
    columns + private '_'-prefixed fields consumed by wnba_projections.py). None if the player
    doesn't clear the rotation-minutes bar — filters deep-bench noise off the slate, the same
    role LINEUP_SPOT_PA/active-roster fallback plays for MLB."""
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
        # private fields consumed by wnba_projections.py
        "_pid": player["id"],
        "_game_log": game_log,
        "_game_date": game_date,
    }


# --------------------------------------------------------------------------- orchestration
def build_slate(date_str: str, min_avg_minutes: float = CFG.MIN_AVG_MINUTES,
                last_n_games: int = CFG.RECENT_GAMES_N, max_workers: int = 8
                ) -> Tuple[List[Dict], List[Dict]]:
    """Fetch and assemble the full WNBA slate concurrently.

    Returns (rows, meta), matching mlb_engine.build_slate's contract:
      rows : list of flat per-player dicts ready for a DataFrame / the projections module
      meta : list of per-game dicts (label, names, game_date)
    """
    games = get_schedule(date_str)
    if not games:
        return [], []

    meta: List[Dict] = []
    tasks: List[Tuple[Dict, str, str, str, Optional[str]]] = []
    for g in games:
        label = f"{g['away_name']} @ {g['home_name']}"
        meta.append({"label": label, "away_name": g["away_name"], "home_name": g["home_name"],
                     "game_date": g.get("game_date")})
        for team_id, team_name, opp_name in ((g["home_id"], g["home_name"], g["away_name"]),
                                              (g["away_id"], g["away_name"], g["home_name"])):
            for player in get_team_roster(team_id):
                tasks.append((player, team_name, opp_name, label, g.get("game_date")))

    def fetch_one(item):
        player, team_name, opp_name, label, game_date = item
        log = get_player_recent_games(player["id"], last_n_games)
        return player_row(player, team_name, opp_name, label, game_date, log, min_avg_minutes)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        rows = [r for r in ex.map(fetch_one, tasks) if r is not None]

    return rows, meta
