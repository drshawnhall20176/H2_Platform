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
_diag_seen: set = set()   # keys already printed about — avoids repeating the same diagnostic line
                          # once per player when a team/game is looked at by every player on it


def _diag(msg: str) -> None:
    """Stage-by-stage visibility for the ONE failure mode logging.exception can't catch: every
    request succeeding (200 OK, valid JSON) while the parsing code quietly extracts nothing,
    because the real shape doesn't match what was coded against. print() (not the `logging`
    module) specifically because Streamlit Cloud's log viewer reliably captures stdout — a prior
    round of debugging this exact module found zero logger.exception output even after a
    confirmed-fresh rebuild+refresh, which points at logging-module output not surfacing on this
    platform the way stdout does, not at zero problems existing."""
    print(f"[WNBA] {msg}", flush=True)


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
    """Games scheduled for date_str (YYYY-MM-DD). One dict per game with both team ids/names/
    abbreviations — all pulled directly from the scoreboard response, no separate team lookup
    needed. Abbreviations (e.g. "ATL") exist alongside id/displayName in the same competitor
    "team" object ESPN already returns here — captured because get_team_injuries needs one (the
    injuries endpoint keys by abbreviation, not ESPN's numeric team id), not because anything
    else in this module needs it yet."""
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
            logger.exception("WNBA scoreboard event had an unexpected shape: %s", event.get("id"))
            continue
    _diag(f"get_schedule({date_str}): {len(games)} game(s) found ({len(data.get('events', []))} raw events)")
    return games


def team_abbrs_from_meta(meta: List[Dict]) -> Dict[int, str]:
    """{team_id: abbreviation} for every team on the slate, derived from build_slate's own
    `meta` return value — genuinely zero extra network cost, since meta already carries
    home_id/home_abbr/away_id/away_abbr from the same scoreboard fetch build_slate already made.
    (An earlier version of this function called get_schedule() a second time to get the same
    data — a real, avoidable duplicate live request — deriving from meta instead of re-fetching
    fixes that.) Entries with no abbreviation in the source response are simply omitted, not
    guessed."""
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
    list of {position, items: [...]} groups) — flattened here into one player list. Empty list
    (not an exception) on any fetch failure, so one bad team doesn't take down the whole build."""
    data = _get_json(f"{SITE_API}/teams/{team_id}/roster")
    if not data:
        _diag(f"get_team_roster({team_id}): roster fetch returned nothing (request failed)")
        return []
    if "athletes" not in data:
        _diag(f"get_team_roster({team_id}): response had no 'athletes' key — keys were {list(data.keys())}")
    out = []
    flat_count = 0
    for entry in data.get("athletes", []):
        # Documented shape: entry is a position GROUP with a nested "items" list of players.
        # Observed-in-practice shape (WNBA, confirmed via diagnostic: 'athletes' present but 0
        # players extracted under the grouped assumption): entry IS the player object directly,
        # no grouping. Handle both rather than guess which is "correct" — a groups-shaped entry
        # has no "id" of its own, a player-shaped entry has no "items", so this can't double-count.
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
def _parse_stat_value(raw, side: str = "left") -> float:
    """ESPN's boxscore stats are strings. Combo fields report made-attempted ('12-24'). Default
    side="left" returns the makes, unchanged behavior for every existing caller (the bootstrap
    model, PTS/REB/AST/FG3M). side="right" returns the attempts instead — needed for the
    possession estimate (FGA/FTA), which cares about attempts, not makes. Plain numeric fields
    (PTS, REB, AST, MIN, TOV) have no '-' and pass through the same regardless of side. Anything
    unparseable becomes 0.0 — the safe default for a missed/DNP game or an unmatched field."""
    if raw is None:
        return 0.0
    s = str(raw).strip()
    if "-" in s and not s.startswith("-"):
        parts = s.split("-", 1)
        s = parts[1] if side == "right" and len(parts) > 1 else parts[0]
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def get_team_recent_game_ids(team_id: int, before_date: str,
                             n: int = CFG.RECENT_GAMES_N, days_back: int = 45) -> List[Dict[str, Any]]:
    """A team's last n COMPLETED games STRICTLY BEFORE before_date (YYYY-MM-DD), most recent
    first: [{"gameId", "date", "opp_id", "opp_name"}, ...]. Found by scanning the scoreboard
    across a trailing window and filtering to games where this team appears as a competitor —
    reuses get_schedule's already-verified scoreboard parsing rather than the separate,
    unverified teams/{id}/schedule endpoint. Opponent name/id are captured here (not looked up
    separately) since the scoreboard response already has them for free.

    days_back defaults to 45 (comfortably covers n=10 games at the WNBA's ~2-4 games/week pace —
    the "recent form" use case build_slate/get_player_recent_games rely on). Matchup Lab's
    head-to-head lookup calls this with a much wider days_back (~200, back to the season start)
    and a large n, then filters the result to one specific opponent — reusing this exact function
    rather than a second implementation of the same scoreboard-scanning logic.

    "Strictly before" (not "at or before") matters beyond tonight's live board: called for
    tonight's date, the game being projected is still STATUS_SCHEDULED, so "completed" alone
    would exclude it anyway. But this function is also reused for retrospective grading of a PAST
    date, called AFTER that date's games have finished — at that point they're "completed" too,
    and without an explicit date cutoff they'd leak into their own pre-game sample (a real
    lookahead-bias bug, not just a hypothetical one)."""
    end = datetime.strptime(before_date, "%Y-%m-%d")
    start = end - timedelta(days=days_back)
    date_range = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"
    # limit=500 (not the original 200): a full-season window (days_back~200) can hold ~300+ league
    # games across all 15 teams, and a truncated result here would silently under-count a
    # head-to-head history rather than error — better to ask for enough headroom than guess wrong.
    data = _get_json_cached(f"{SITE_API}/scoreboard", params={"dates": date_range, "limit": 500})
    diag_key = (team_id, before_date, days_back)
    if not data:
        if diag_key not in _diag_seen:
            _diag(f"get_team_recent_game_ids(team={team_id}): trailing-window scoreboard fetch returned nothing")
            _diag_seen.add(diag_key)
        return []

    found: List[Dict[str, Any]] = []
    for event in data.get("events", []):
        status = ((event.get("status") or {}).get("type") or {})
        if not status.get("completed"):
            continue
        ev_date = (event.get("date") or "")[:10]
        if not ev_date or ev_date >= before_date:   # strictly before, not at-or-before
            continue
        comps = event.get("competitions") or []
        if not comps:
            continue
        competitors = comps[0].get("competitors") or []
        this_team, opp_team = None, None
        for c in competitors:
            try:
                cid = int(c["team"]["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if cid == team_id:
                this_team = c
            else:
                opp_team = c
        if this_team is not None and event.get("id"):
            opp_info = (opp_team or {}).get("team") or {}
            found.append({
                "gameId": event["id"], "date": event.get("date") or "",
                "opp_id": opp_info.get("id"), "opp_name": opp_info.get("displayName", "Unknown"),
            })

    found.sort(key=lambda g: g["date"], reverse=True)
    result = found[:n]
    if diag_key not in _diag_seen:
        _diag(f"get_team_recent_game_ids(team={team_id}, before={before_date}, days_back={days_back}): "
             f"{len(result)} completed game(s) found "
             f"({len(data.get('events', []))} raw events scanned)")
        _diag_seen.add(diag_key)
    return result


CDN_API = "https://cdn.espn.com/core/wnba/boxscore"


def get_game_boxscore(game_id: str) -> Dict[int, Dict[str, float]]:
    """{player_id: {pts, reb, ast, fg3m, min}} for every player who appeared in a game — one
    fetch covers both teams, shared across every player on the slate who played that game (see
    _get_json_cached). Empty dict on any failure or if a player didn't play (didNotPlay=True).

    DATA SOURCE: cdn.espn.com, not site.api.espn.com/site.web.api.espn.com. Both "site" API
    subdomains were tried first (matching this module's original schema docs) and both were
    confirmed via live diagnostic logs to return only team-level stats for these WNBA games —
    `boxscore.teams[]` blocks with keys ['team', 'statistics', 'displayOrder', 'homeAway'], no
    'players' key anywhere, on either host. The CDN endpoint's response shape puts per-player
    data at `gamepackageJSON.boxscore.players` — a SIBLING array to `boxscore.teams`, not nested
    inside each team block the way the "site" family's documented schema assumes. Confirmed live:
    `boxscore.players` has one entry per team, each with a real `statistics` key."""
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

    # One more diagnostic layer in case `statistics[].names/athletes/stats` isn't quite the right
    # shape at this new location either — this fires only if extraction is still empty.
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


def _find_team_stat(stats_by_name: Dict[str, str], *candidates: str, side: str = "left") -> float:
    """Look up a team stat by trying each candidate name, exact match first, falling back to a
    prefix match. The prefix fallback exists because a real CDN boxscore example (confirmed live,
    ScrapeCreators' walkthrough) showed made-count stats under COMBO names —
    "threePointFieldGoalsMade-threePointFieldGoalsAttempted", not a bare "threePointFieldGoalsMade"
    key — the same naming pattern already found and handled for player-level stats. _parse_stat_
    value's existing "X-Y -> take X" logic handles the combo correctly once the right key is
    found; the fix here is finding it. side is forwarded to _parse_stat_value unchanged — "left"
    (default) for makes, "right" for attempts (needed by the possession estimate). Returns 0.0 if
    nothing matches any candidate."""
    for c in candidates:
        if c in stats_by_name:
            return _parse_stat_value(stats_by_name[c], side=side)
    for name, raw in stats_by_name.items():
        if any(name.startswith(c) for c in candidates):
            return _parse_stat_value(raw, side=side)
    return 0.0


def get_game_team_totals(game_id: str) -> Dict[int, Dict[str, float]]:
    """{team_id: {pts, reb, ast, fg3m, poss}} TEAM-level totals for a game — from
    `boxscore.teams[]` (the same CDN response get_game_boxscore already fetches and caches;
    calling both for the same game_id costs one network request total, not two, via
    _get_json_cached). This is the foundation for "stats allowed" (Hot Hand Engine's
    opponent-adjustment signal): a team's defensive profile is just the OTHER team's totals in
    each of their recent games.

    poss is an ESTIMATED POSSESSION count for that team's own box score in this game, using the
    standard formula FGA - OREB + TOV + 0.44*FTA (the same estimate used throughout basketball
    analytics for games without official play-by-play possession tracking). This exists to fix a
    real conflation in the "allowed" signal: "this team allows a lot" and "this team just plays
    fast, so everyone accumulates more against them" look identical in raw per-game allowed
    totals. Dividing an allowed stat by poss (done downstream, in get_team_recent_allowed_stats
    and build_hot_hand_board) turns it into a per-possession rate, which isn't fooled by pace.

    Field-name matching is defensive (see _find_team_stat) because the exact naming convention
    for THIS specific block (team-level, inside a boxscore, as opposed to player-level or
    season-cumulative scoreboard stats) hasn't been fully confirmed live for every field — the
    pts/reb/ast/fg3m names were confirmed live (see PLATFORM_CHECKPOINT), but the possession
    inputs (FGA, FTA, OREB, TOV field names) are still an educated guess based on ESPN's other
    documented naming conventions (the made-attempted combo pattern, the "total" prefix already
    seen on totalRebounds). The diagnostic dump below fires if poss comes back 0 despite the team
    block being present, the same safety net already proven for the pts/reb/ast/fg3m fix."""
    data = _get_json_cached(CDN_API, params={"xhr": "1", "gameId": game_id})
    if not data:
        return {}
    gp = data.get("gamepackageJSON") or {}
    box = gp.get("boxscore") or {}
    teams = box.get("teams") or []
    out: Dict[int, Dict[str, float]] = {}
    for team_block in teams:
        team_info = team_block.get("team") or {}
        try:
            tid = int(team_info.get("id"))
        except (TypeError, ValueError):
            continue
        stats_by_name = {}
        for s in team_block.get("statistics", []):
            name = s.get("name")
            if name:
                stats_by_name[name] = s.get("displayValue")
        fga = _find_team_stat(stats_by_name, "fieldGoalsMade-fieldGoalsAttempted",
                              "fieldGoalsAttempted", side="right")
        fta = _find_team_stat(stats_by_name, "freeThrowsMade-freeThrowsAttempted",
                              "freeThrowsAttempted", side="right")
        oreb = _find_team_stat(stats_by_name, "offensiveRebounds")
        tov = _find_team_stat(stats_by_name, "totalTurnovers", "turnovers")
        poss = fga - oreb + tov + 0.44 * fta
        out[tid] = {
            "pts": _find_team_stat(stats_by_name, "points"),
            "reb": _find_team_stat(stats_by_name, "totalRebounds", "rebounds"),
            "ast": _find_team_stat(stats_by_name, "assists"),
            "fg3m": _find_team_stat(stats_by_name, "threePointFieldGoalsMade"),
            "poss": poss if poss > 0 else 0.0,
        }

    dump_key = f"_team_totals_shape_dump:{game_id}"
    all_core_zero = teams and all(
        v["pts"] == 0.0 and v["reb"] == 0.0 and v["ast"] == 0.0 and v["fg3m"] == 0.0
        for v in out.values()
    )
    any_poss_zero = teams and any(v["poss"] == 0.0 for v in out.values())
    if (all_core_zero or any_poss_zero) and dump_key not in _diag_seen:
        _diag_seen.add(dump_key)
        tb0 = teams[0]
        _diag(f"get_game_team_totals({game_id}) shape dump: team_block keys = {list(tb0.keys())}")
        stat_names = [s.get("name") for s in tb0.get("statistics", [])]
        _diag(f"get_game_team_totals({game_id}) shape dump: statistics[].name values = {stat_names}")
        if any_poss_zero and not all_core_zero:
            _diag(f"get_game_team_totals({game_id}): poss=0 while pts/reb/ast/fg3m parsed fine — "
                 f"FGA/FTA/OREB/TOV candidate field names likely wrong, see values above")
    return out


def get_team_recent_allowed_stats(team_id: int, before_date: str,
                                  n: int = CFG.RECENT_GAMES_N, days_back: int = 45) -> Dict[str, float]:
    """Average PTS/REB/AST/FG3M this team has ALLOWED over their last n completed games —
    i.e., their opponents' team totals in those same games. Built entirely from box score data
    already fetched for build_slate; costs zero new network calls when Hot Hand Engine runs
    alongside a normal slate build (get_game_team_totals shares get_game_boxscore's cache).

    days_back defaults to 45 (Hot Hand Engine's "recent form" use). Matchup Lab calls this twice
    per opponent — once with the default (recent) and once with a season-wide window — to show
    whether a team's defense is trending better or worse than their own season norm, not just a
    single snapshot number.

    Also averages "poss" — the opponent's own estimated possessions in each of those same games
    (see get_game_team_totals). This is what turns a raw "allowed" total into a pace-adjusted
    rate downstream (build_hot_hand_board divides by it) — without it, a fast-paced team looks
    like a bad defense simply because there were more possessions to allow stats in."""
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
    """Rest context for a team heading into `before_date`: how many days since their last
    completed game, and whether tonight is the second night of a back-to-back. Built entirely
    from game dates already available via get_team_recent_game_ids — zero new network calls.

    days_back defaults to a short 10 days (not the 45-day "recent form" window) — rest only cares
    about the IMMEDIATELY prior game, so a short scan is both cheap and sufficient. A team with no
    completed game in the last 10 days (start of season, All-Star break) reports rest_days=None
    rather than a fabricated "well-rested" guess — an honest unknown, not a default.

    Returns {"rest_days": int|None, "is_back_to_back": bool, "last_game_date": str|None,
    "last_opp_name": str|None}. is_back_to_back is True when rest_days <= 1 (played yesterday, or
    — in the data-glitch case of a same-day double-count — today)."""
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
    """Team injury report for one team, by ESPN abbreviation (e.g. "ATL") — NOT team_id, since
    this endpoint keys by abbreviation. Confirmed live during scoping: `site.api.espn.com/apis/
    site/v2/sports/basketball/nba/injuries?team=ATL` returns real, current per-player injury
    records, sourced from Rotowire (same as espn.com/wnba/injuries, confirmed live and current for
    the 2026 WNBA season during the same scoping pass). WNBA follows the identical site.api.espn.
    com/apis/site/v2/sports/basketball/{league} pattern this module already relies on everywhere
    else — league="wnba" here, same as every other call in this file — but the WNBA JSON shape
    specifically hasn't been hit live yet (only the NBA JSON + the WNBA HTML page were), so the
    diagnostic dump below is a real safety net here, not just standard caution.

    Returns [{"player", "status", "position", "return_date", "comment"}, ...] — one entry per
    currently-listed injury. An empty list is a team with no news reported, treated as healthy —
    there's no reliable way to distinguish "confirmed healthy" from "fetch problem" from this
    endpoint alone, and treating silence as good news is the honest default here (the inverse of
    get_team_rest_info's "no data -> None, not a guess": there, silence means unknown; here,
    silence IS the informative case).

    "status" (e.g. "Out", "Day-To-Day", "Questionable") is intentionally left as the raw text
    ESPN/Rotowire assigned, not translated into a boolean playing/not-playing call — "Day-To-Day"
    isn't a hard out, and collapsing it into one wouldn't be honest. This is informational display
    only (Stage A of the injury/availability scoping) — it does NOT feed into Matchup Factor,
    Recent Avg, or any other computed signal. Quantifying an "opportunity boost" for teammates
    when a key player sits is a genuinely separate, harder modeling decision, deferred rather than
    guessed at here."""
    if not team_abbr:
        return []
    data = _get_json_cached(f"{SITE_API}/injuries", params={"team": team_abbr})
    if not data:
        return []
    out = []
    for inj in data.get("injuries", []):
        athlete = inj.get("athlete") or {}
        details = inj.get("details") or {}
        out.append({
            "player": athlete.get("displayName"),
            "status": inj.get("status"),
            "position": (athlete.get("position") or {}).get("abbreviation"),
            "return_date": details.get("returnDate"),
            "comment": inj.get("shortComment"),
        })

    dump_key = f"_injuries_shape_dump:{team_abbr}"
    if data.get("injuries") and not any(o["player"] for o in out) and dump_key not in _diag_seen:
        _diag_seen.add(dump_key)
        _diag(f"get_team_injuries({team_abbr}) shape dump: first injury item keys = "
             f"{list(data['injuries'][0].keys())}")
    return out


def get_player_results(date_str: str) -> Dict[int, Dict[str, float]]:
    """Actual per-player results for all games on date_str, keyed by player id — same contract as
    mlb_engine.get_player_results, so retro.py's grading logic (grade_play/grade_slate) works
    identically for either sport without modification. Empty for dates with no games, or games
    that haven't been played yet (their boxscore comes back with no player stats, contributing
    nothing rather than erroring — no separate "is this game final" check needed)."""
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
    first. `opp`/`date` come from get_team_recent_game_ids (free — already fetched for the
    schedule scan) so any consumer (the Best Bets diagnostic inspector, a future matchup tool)
    can show which actual game a number came from, not just "game #3". Requires team_id and
    before_date (build_slate always supplies both) — without them there's no way to know which
    games to look at, so this returns an empty list rather than guessing.

    days_back defaults to 45 (the model's own recency window). Matchup Lab's season-baseline
    comparison calls this with a season-wide days_back and a large last_n instead — see
    get_player_season_games, which wraps that specific call."""
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


# WNBA regular season start (2026-04-03, confirmed live from ESPN) plus a small buffer. Used only
# to bound season-wide scans (head-to-head, season-baseline) so they don't request an
# unnecessarily huge date range once the season is well underway — get_team_recent_game_ids
# clips date_from at "today - days_back" regardless, this just keeps days_back reasonable rather
# than guessing a huge fixed number.
SEASON_START = "2026-04-01"


def _days_since_season_start(before_date: str) -> int:
    try:
        return max((datetime.strptime(before_date, "%Y-%m-%d")
                   - datetime.strptime(SEASON_START, "%Y-%m-%d")).days + 1, 1)
    except ValueError:
        return 200


def get_player_season_games(player_id: int, team_id: int, before_date: str,
                            max_games: int = 82) -> List[Dict[str, float]]:
    """This player's full game log for the season so far (any opponent), most recent first —
    the baseline Matchup Lab compares a head-to-head sample against. Deliberately separate from
    get_player_recent_games's 45-day "what the model actually prices off" window: comparing a
    head-to-head average against the player's LAST 10 games conflates "this team's specific
    effect on her" with "she's just been hot/cold lately in general." Comparing against the full
    season isolates the team-specific signal from general form drift."""
    days_back = _days_since_season_start(before_date)
    return get_player_recent_games(player_id, last_n=max_games, team_id=team_id,
                                   before_date=before_date, days_back=days_back)


def get_player_history_vs_opponent(player_id: int, team_id: int, opp_id: int, before_date: str,
                                   max_games: int = 20) -> List[Dict[str, float]]:
    """This player's stats in every game THIS SEASON their team has played against one specific
    opponent, most recent first: [{pts, reb, ast, fg3m, min, opp, date}, ...]. Genuinely
    different from get_player_recent_games (which is "last N games, any opponent" — the model's
    recency signal); this is "every game vs THIS opponent, however long ago" — the head-to-head
    signal Matchup Lab is built around. Reuses get_team_recent_game_ids with a season-wide
    days_back rather than a second scoreboard-scanning implementation; empty list (not an error)
    if the two teams haven't played yet this season, which is common and expected — WNBA teams
    typically meet only 2-4 times across a full season."""
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
        "_opp_id": opp_id,     # for opponent-defense lookups (Hot Hand Engine, Matchup Lab)
        "_team_id": team_id,   # this player's own team — needed for the H2H lookup (Matchup Lab)
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
