"""
wnba_engine.py — WNBA data layer using ESPN's public (unofficial) API.

Provides:
  - get_schedule(date_str) -> games scheduled for a date
  - get_team_roster(team_id) -> a team's roster
  - get_player_recent_games(player_id, last_n) -> last N game logs (PTS/REB/AST/FG3M/MIN)
  - build_slate(date_str) -> (rows, meta), matching the platform's cross-sport engine contract
    (see mlb_engine.build_slate / sports.py's Sport.engine)

DATA SOURCE CHANGE (from the original nba_api build): nba_api wraps stats.nba.com, which has a
long-documented history (github.com/swar/nba_api/issues/182, /320, /498, and others going back to
2020) of blocking or throttling requests from cloud-hosting IP ranges — confirmed here by a
production ReadTimeout from Streamlit Cloud. That's a network-level block, not something request
headers or retries fix. Switched to ESPN's public API (site.api.espn.com / site.web.api.espn.com)
instead: unofficial and undocumented like nba_api, but with no comparable pattern of cloud-IP
blocking in its own issue history. Endpoint choices and field names below come from
github.com/pseudo-r/Public-ESPN-API's documented response schemas (WNBA gamelog explicitly listed
as verified working), not from live testing — this sandbox can't reach either API, so the same
honesty applies as before: verify against a real slate on first deploy.

Notably simpler than the nba_api version: no team-ID cross-reference table needed (ESPN's
scoreboard response already carries each game's team IDs + display names inline), and no WNBA
season-string guessing (the gamelog endpoint defaults to the current season server-side).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import requests

import config_wnba as CFG

logger = logging.getLogger(__name__)

SITE_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba"
WEB_API = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/wnba"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; H2Sports/1.0)"}
_TIMEOUT = 15


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
def _parse_gamelog_value(raw) -> float:
    """ESPN's gamelog stats are strings. Combo fields report made-attempted ('12-24' for FG,
    3PT) — we want the makes (left side) for the bootstrap model. Plain numeric fields (PTS, REB,
    AST, MIN) pass through as-is. Anything unparseable becomes 0.0 — the safe default for a
    missed/DNP game, since it gets filtered out downstream by the minutes bar anyway."""
    if raw is None:
        return 0.0
    s = str(raw).strip()
    if "-" in s and not s.startswith("-"):
        s = s.split("-", 1)[0]
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def get_player_recent_games(player_id: int, last_n: int = CFG.RECENT_GAMES_N) -> List[Dict[str, float]]:
    """Last N game logs for a player: [{pts, reb, ast, fg3m, min}, ...], most recent first
    (ESPN's gamelog is already ordered that way). Empty list on any failure.

    ESPN's gamelog response uses parallel arrays: `names` lists every column (meta fields like
    date/opponent/result FIRST, then the actual stat columns), but each event's `stats` array only
    holds the stat-column values — the meta fields are separate top-level keys on the event
    instead. Aligning `names[-len(stats):]` against `stats` (from the right, not the left) handles
    however many meta fields there are without hardcoding which specific ones."""
    data = _get_json(f"{WEB_API}/athletes/{player_id}/gamelog")
    if not data:
        return []
    names = data.get("names") or []
    events = data.get("events") or []
    out = []
    for ev in events:
        stats = ev.get("stats") or []
        if not stats or not names:
            continue
        stat_names = names[-len(stats):]
        row = {n: _parse_gamelog_value(v) for n, v in zip(stat_names, stats)}
        out.append({
            "pts": row.get("points", 0.0),
            "reb": row.get("rebounds", 0.0),
            "ast": row.get("assists", 0.0),
            "fg3m": row.get("threePointsMade", 0.0),
            "min": row.get("minutes", 0.0),
        })
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
