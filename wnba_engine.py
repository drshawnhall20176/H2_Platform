"""
wnba_engine.py — WNBA data layer using ESPN's public (unofficial) API.

Provides:
  - get_schedule(date_str) -> games scheduled for a date
  - get_team_roster(team_id) -> a team's roster
  - get_player_recent_games(player_id, last_n, team_id, before_date) -> last N game logs
    (PTS/REB/AST/FG3M/MIN)
  - build_slate(date_str) -> (rows, meta), matching the platform's cross-sport engine contract
    (see mlb_engine.build_slate / sports.py's Sport.engine)

DATA SOURCE CHANGE #1 (from the original nba_api build): nba_api wraps stats.nba.com, which has a
long-documented history (github.com/swar/nba_api/issues/182, /320, /498, going back to 2020) of
blocking/throttling cloud-hosting IP ranges — confirmed here by a production ReadTimeout from
Streamlit Cloud. Switched to ESPN's public API instead.

DATA SOURCE CHANGE #2 (within the ESPN rewrite itself): the first version of this file used
`.../athletes/{id}/gamelog`, following github.com/pseudo-r/Public-ESPN-API's documented example.
Live testing (with Dr. Hall pasting real responses back) showed that endpoint's real shape
diverges from the doc in two ways for WNBA: `events` is a dict keyed by game ID, not a list, and —
more importantly — individual events carry game CONTEXT (opponent, score, result) but no
per-player stat line at all. wehoop (the R package SportsDataverse built specifically for ESPN's
WNBA/WBB data) independently documents this exact endpoint family as "less stable than the rest of
the surface," which matches. Rewritten here to pull stats from the per-GAME boxscore instead
(`.../summary?event={id}`) — one fetch covers every player in that game, for both teams, so it's
also fetched once per game and reused (see `_get_json`'s cache) rather than once per player.
Team-level fields in that endpoint were confirmed against a real independent example (a live NBA
boxscore shown in a ScrapeCreators walkthrough); the player-level `statistics[].names/athletes/
stats` shape is still sourced from documentation rather than a live WNBA response — same honesty
as before: verify on first deploy, and this module fails soft (empty result, logged) rather than
crashing if that shape is also off in some way not yet caught.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

import config_wnba as CFG

logger = logging.getLogger(__name__)

SITE_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; H2Sports/1.0)"}
_TIMEOUT = 15

# Simple per-process cache so fetching 10 games' worth of boxscores for a 12-player roster costs
# 10 requests, not 120 (every player on both teams shares the same game's boxscore). No TTL —
# fine for the lifetime of a single slate build. Tests should not rely on this persisting; see
# test_wnba_engine.py's use of monkeypatch on _get_json_cached directly where caching matters.
_response_cache: Dict[Tuple[str, Tuple], Optional[Dict]] = {}


def _get_json(url: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """Shared fetch helper: returns the parsed JSON body, or None on any failure (bad status,
    timeout, malformed JSON). Every caller below treats None the same way it treats an empty
    result — fail soft, log, move on — so one bad request can't take down the whole slate build."""
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("WNBA ESPN API request failed: %s params=%s", url, params)
        return None


def _get_json_cached(url: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """_get_json, but de-duplicated within this process — see _response_cache above."""
    key = (url, tuple(sorted((params or {}).items())))
    if key not in _response_cache:
        _response_cache[key] = _get_json(url, params)
    return _response_cache[key]


# --------------------------------------------------------------------------- schedule
def get_schedule(date_str: str) -> List[Dict[str, Any]]:
    """Games scheduled for date_str (YYYY-MM-DD). One dict per game with both team ids/names —
    both pulled directly from the scoreboard response, no separate team lookup needed."""
    espn_date = date_str.replace("-", "")   # ESPN wants YYYYMMDD; we use YYYY-MM-DD everywhere else
    data = _get_json(f"{SITE_API}/scoreboard", params={"dates": espn_date})
    if not data:
        return []

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
                "away_id": int(away["team"]["id"]),
                "away_name": away["team"].get("displayName", "Unknown"),
            })
        except (KeyError, TypeError, ValueError):
            logger.exception("WNBA scoreboard event had an unexpected shape: %s", event.get("id"))
            continue
    return games


# --------------------------------------------------------------------------- rosters
def get_team_roster(team_id: int) -> List[Dict[str, Any]]:
    """A team's roster: [{id, name}, ...]. ESPN groups the roster by position (`athletes` is a
    list of {position, items: [...]} groups) — flattened here into one player list. Empty list
    (not an exception) on any fetch failure, so one bad team doesn't take down the whole build."""
    data = _get_json(f"{SITE_API}/teams/{team_id}/roster")
    if not data:
        return []
    out = []
    for group in data.get("athletes", []):
        for item in group.get("items", []):
            pid = item.get("id")
            if pid is None:
                continue
            try:
                out.append({"id": int(pid), "name": item.get("displayName", "Unknown")})
            except (TypeError, ValueError):
                continue
    return out


# --------------------------------------------------------------------------- recent form
def _parse_stat_value(raw) -> float:
    """ESPN's boxscore stats are strings. Combo fields report made-attempted ('12-24') — we want
    the makes (left side) for the bootstrap model. Plain numeric fields (PTS, REB, AST, MIN) pass
    through as-is. Anything unparseable becomes 0.0 — the safe default for a missed/DNP game,
    since it gets filtered out downstream by the minutes bar anyway."""
    if raw is None:
        return 0.0
    s = str(raw).strip()
    if "-" in s and not s.startswith("-"):
        s = s.split("-", 1)[0]
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def get_team_recent_game_ids(team_id: int, before_date: str,
                             n: int = CFG.RECENT_GAMES_N) -> List[str]:
    """A team's last n COMPLETED game IDs at/before before_date (YYYY-MM-DD), most recent first.
    Found by scanning the scoreboard across a 45-day trailing window and filtering to games where
    this team appears as a competitor — reuses get_schedule's already-verified scoreboard parsing
    rather than the separate, unverified teams/{id}/schedule endpoint. 45 days comfortably covers
    n=10 games at the WNBA's ~2-4 games/week pace. The "completed" filter naturally excludes the
    game currently being projected (still STATUS_SCHEDULED), so no separate date-cutoff math is
    needed."""
    end = datetime.strptime(before_date, "%Y-%m-%d")
    start = end - timedelta(days=45)
    date_range = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"
    data = _get_json_cached(f"{SITE_API}/scoreboard", params={"dates": date_range, "limit": 200})
    if not data:
        return []

    found: List[Tuple[str, str]] = []   # (game_id, date) so we can sort by date
    for event in data.get("events", []):
        status = ((event.get("status") or {}).get("type") or {})
        if not status.get("completed"):
            continue
        comps = event.get("competitions") or []
        if not comps:
            continue
        competitors = comps[0].get("competitors") or []
        ids = set()
        for c in competitors:
            try:
                ids.add(int(c["team"]["id"]))
            except (KeyError, TypeError, ValueError):
                continue
        if team_id in ids and event.get("id"):
            found.append((event["id"], event.get("date") or ""))

    found.sort(key=lambda g: g[1], reverse=True)
    return [gid for gid, _ in found[:n]]


def get_game_boxscore(game_id: str) -> Dict[int, Dict[str, float]]:
    """{player_id: {pts, reb, ast, fg3m, min}} for every player who appeared in a game — one
    fetch covers both teams, shared across every player on the slate who played that game (see
    _get_json_cached). Empty dict on any failure or if a player didn't play (didNotPlay=True)."""
    data = _get_json_cached(f"{SITE_API}/summary", params={"event": game_id})
    if not data:
        return {}
    out: Dict[int, Dict[str, float]] = {}
    teams = ((data.get("boxscore") or {}).get("teams")) or []
    for team_block in teams:
        for player_group in team_block.get("players", []):
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
    return out


def get_player_recent_games(player_id: int, last_n: int = CFG.RECENT_GAMES_N,
                            team_id: Optional[int] = None,
                            before_date: Optional[str] = None) -> List[Dict[str, float]]:
    """Last N game logs for a player: [{pts, reb, ast, fg3m, min}, ...], most recent first.
    Requires team_id and before_date (build_slate always supplies both) — without them there's no
    way to know which games to look at, so this returns an empty list rather than guessing."""
    if team_id is None or before_date is None:
        return []
    game_ids = get_team_recent_game_ids(team_id, before_date, last_n)
    out = []
    for gid in game_ids:
        box = get_game_boxscore(gid)
        line = box.get(player_id)
        if line:
            out.append(line)
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
    _response_cache.clear()   # don't serve a previous slate-date's cached scoreboard/boxscores
    games = get_schedule(date_str)
    if not games:
        return [], []

    meta: List[Dict] = []
    tasks: List[Tuple[Dict, str, str, str, Optional[str], int]] = []
    for g in games:
        label = f"{g['away_name']} @ {g['home_name']}"
        meta.append({"label": label, "away_name": g["away_name"], "home_name": g["home_name"],
                     "game_date": g.get("game_date")})
        for team_id, team_name, opp_name in ((g["home_id"], g["home_name"], g["away_name"]),
                                              (g["away_id"], g["away_name"], g["home_name"])):
            for player in get_team_roster(team_id):
                tasks.append((player, team_name, opp_name, label, g.get("game_date"), team_id))

    def fetch_one(item):
        player, team_name, opp_name, label, game_date, team_id = item
        log = get_player_recent_games(player["id"], last_n_games, team_id=team_id,
                                      before_date=date_str)
        return player_row(player, team_name, opp_name, label, game_date, log, min_avg_minutes)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        rows = [r for r in ex.map(fetch_one, tasks) if r is not None]

    return rows, meta
