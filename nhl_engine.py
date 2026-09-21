"""
nhl_engine.py — NHL data layer using ESPN's public (unofficial) hockey API.

Provides (same engine contract as wnba_engine / nba_engine, see sports.py's Sport.engine):
  - get_schedule(date_str)                      games on a date (Eastern), with team ids/names/logos
  - get_team_roster(team_id)                    [{id, name, pos, is_goalie}, ...]
  - get_game(game_id)                           ONE compact parsed record per finished game
  - get_player_recent_games(...)                a player's last N games (skater OR goalie shape)
  - build_slate(date_str) -> (rows, meta)       the platform's cross-sport engine contract
  - get_player_results(date_str)                {player_id: {pts, ast, goals, sog, blk | saves}}
  - get_team_recent_allowed_stats / _scored_stats, get_team_rest_info, get_team_injuries

WHY THIS IS NOT A COPY OF nba_engine.py: hockey's ESPN data has two real differences, both
confirmed live (a real 2025-26 game, VAN 8 @ COL 6, gameId 401803539) before this was written.
  1. The per-game boxscore comes from `site.api.espn.com/.../hockey/nhl/summary?event={id}` and
     carries full per-player stats under `boxscore.players[].statistics[]` (groups "forwards",
     "defenses", "goalies"). The `cdn.espn.com/core/nhl/boxscore` endpoint the basketball engines
     use returns 404 for NHL. The summary response is ~400 KB (it includes every play), so this
     module parses it once into a small dict and DISCARDS the raw response — caching raw
     summaries the way the basketball engines cache theirs would hold hundreds of MB.
  2. Stats are read by ESPN's own `keys` array, never by its `labels`, because the labels are
     misleading: the label "SOG" is SHOOTOUT goals (key `shootoutGoals`); shots on goal is the
     column labelled "S" (key `shotsTotal`).
Two players' worth of shape that ESPN does NOT give us: there is no "starter" flag on goalies, so
the goalie of record for a game is inferred as the team's goalie with the most ice time.

ESPN's `dates=START-END` scoreboard range syntax answers HTTP 400 for every range now (confirmed
live 2026-09-19), so the trailing-window scan goes through basketball_engine.
scoreboard_events_in_window's month/day fallback — that helper is sport-agnostic and is reused
here rather than copied.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from curl_cffi import requests
import pytz

import config_nhl as CFG
import basketball_engine as BB   # sport-agnostic ESPN scoreboard-window / rest / injury helpers

logger = logging.getLogger(__name__)

SITE_API = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl"
_TIMEOUT = 20

# Cache of scoreboard-type responses (small) for the lifetime of one slate build.
_response_cache: Dict[Tuple[str, Tuple], Optional[Dict]] = {}
_diag_seen: set = set()

# Parsed per-game records (small). Only FINISHED games are cached across calls — a live or
# scheduled game's summary changes, and caching its partial parse would freeze a stale answer.
_game_cache: Dict[str, Dict] = {}
_game_failed: set = set()      # game ids whose fetch failed during THIS build (cleared per build)
_game_locks: Dict[str, threading.Lock] = {}
_cache_lock = threading.Lock()
_GAME_CACHE_MAX = 4000         # ~5 KB each -> tens of MB at the very most; cleared when exceeded


def _diag(msg: str) -> None:
    """Stdout diagnostics (Streamlit Cloud's log viewer reliably captures print, not logging) —
    same posture as wnba_engine._diag."""
    print(f"[NHL] {msg}", flush=True)


def _get_json(url: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """Fetch helper: parsed JSON or None on ANY failure (fail soft, log, move on).
    impersonate="chrome" for the same confirmed TLS-fingerprint reason as wnba_engine._get_json."""
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT, impersonate="chrome")
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("NHL ESPN API request failed: %s params=%s", url, params)
        return None


def _get_json_cached(url: str, params: Optional[Dict] = None) -> Optional[Dict]:
    key = (url, tuple(sorted((params or {}).items())))
    if key not in _response_cache:
        _response_cache[key] = _get_json(url, params)
    return _response_cache[key]


# --------------------------------------------------------------------------- schedule
def get_schedule(date_str: str) -> List[Dict[str, Any]]:
    """Games on date_str (YYYY-MM-DD, Eastern). Same return shape as wnba_engine/nba_engine.

    ESPN files games under an Eastern calendar day but a single-date query is not reliable at the
    edges (a late 10 PM ET puck drop is already the next UTC day), so — exactly as the basketball
    engines do — three single-date queries (day-1, day, day+1) are merged and deduped by event id,
    then narrowed to the games whose own start time falls on date_str in US/Eastern."""
    all_events: List[Dict[str, Any]] = []
    seen_ids = set()
    any_real_response = False
    for offset in (-1, 0, 1):
        d = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=offset)).strftime("%Y%m%d")
        data = _get_json(f"{SITE_API}/scoreboard", params={"dates": d})
        if not data:
            continue
        any_real_response = True
        for event in data.get("events", []):
            eid = event.get("id")
            if eid is not None and eid in seen_ids:
                continue
            if eid is not None:
                seen_ids.add(eid)
            all_events.append(event)
    if not any_real_response:
        _diag(f"get_schedule({date_str}): all three scoreboard fetches failed")
        return []

    eastern = pytz.timezone("US/Eastern")
    games: List[Dict[str, Any]] = []
    for event in all_events:
        comps = event.get("competitions") or []
        if not comps:
            continue
        competitors = comps[0].get("competitors") or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        gd = event.get("date")
        try:
            local_date = (datetime.fromisoformat(gd.replace("Z", "+00:00"))
                          .astimezone(eastern).strftime("%Y-%m-%d"))
        except (TypeError, ValueError, AttributeError):
            continue
        if local_date != date_str:
            continue
        status_obj = ((comps[0].get("status") or {}).get("type") or {})
        try:
            games.append({
                "gameId": event.get("id"),
                "game_date": gd,
                "status_state": status_obj.get("state"),
                "status_detail": status_obj.get("description"),
                "home_id": int(home["team"]["id"]),
                "home_name": home["team"].get("displayName", "Unknown"),
                "home_abbr": home["team"].get("abbreviation"),
                "home_logo": home["team"].get("logo"),
                "away_id": int(away["team"]["id"]),
                "away_name": away["team"].get("displayName", "Unknown"),
                "away_abbr": away["team"].get("abbreviation"),
                "away_logo": away["team"].get("logo"),
            })
        except (KeyError, TypeError, ValueError):
            logger.exception("NHL scoreboard event had an unexpected shape: %s", event.get("id"))
    _diag(f"get_schedule({date_str}): {len(games)} game(s) ({len(all_events)} raw events across 3 queries)")
    return games


def team_abbrs_from_meta(meta: List[Dict]) -> Dict[int, str]:
    """{team_id: abbreviation}, derived from build_slate's own meta (no extra network call)."""
    out: Dict[int, str] = {}
    for g in meta:
        if g.get("home_abbr"):
            out[g["home_id"]] = g["home_abbr"]
        if g.get("away_abbr"):
            out[g["away_id"]] = g["away_abbr"]
    return out


# --------------------------------------------------------------------------- rosters
def get_team_roster(team_id: int) -> List[Dict[str, Any]]:
    """A team's roster: [{id, name, pos, is_goalie}, ...]. ESPN groups NHL rosters by position
    ("Centers", "Left Wings", "Right Wings", "Defense", "Goalies") — confirmed live — each group a
    dict with an `items` list; a flat player list is also tolerated. NOTE the roster is the whole
    organization's camp/preseason list (~65-70 names incl. prospects), not a 23-man gameday roster;
    players with no recent NHL game log simply never make the slate."""
    data = _get_json(f"{SITE_API}/teams/{team_id}/roster")
    if not data:
        _diag(f"get_team_roster({team_id}): roster fetch returned nothing")
        return []
    out: List[Dict[str, Any]] = []
    for entry in data.get("athletes", []):
        items = entry.get("items")
        group_pos = str(entry.get("position") or "")
        candidates = items if items is not None else [entry]
        for item in candidates:
            pid = item.get("id")
            if pid is None:
                continue
            try:
                pid_int = int(pid)
            except (TypeError, ValueError):
                continue
            pos = ((item.get("position") or {}).get("abbreviation")) or ""
            is_goalie = pos == "G" or group_pos.lower().startswith("goal")
            out.append({"id": pid_int, "name": item.get("displayName", "Unknown"),
                        "pos": pos or ("G" if is_goalie else ""), "is_goalie": is_goalie})
    _diag(f"get_team_roster({team_id}): {len(out)} player(s) found")
    return out


# --------------------------------------------------------------------------- per-game parsing
# ESPN `keys` read in parse_summary: skaters timeOnIce/goals/assists/shotsTotal/blockedShots; goalies
# timeOnIce/saves/shotsAgainst/goalsAgainst.
# Label fallback used ONLY when a group has no `keys` array. "S" (not "SOG" — that label is
# shootout goals) is shots on goal.
_SKATER_LABELS = {"TOI": "timeOnIce", "G": "goals", "A": "assists", "S": "shotsTotal",
                  "BS": "blockedShots", "HT": "hits", "PIM": "penaltyMinutes"}
_GOALIE_LABELS = {"TOI": "timeOnIce", "SV": "saves", "SA": "shotsAgainst", "GA": "goalsAgainst"}


def toi_minutes(raw) -> float:
    """"19:48" -> 19.8 minutes. Anything unparseable (None, "--", "") is 0.0."""
    if raw is None:
        return 0.0
    s = str(raw).strip()
    if not s or s in ("--", "-"):
        return 0.0
    try:
        if ":" in s:
            m, sec = s.split(":", 1)
            return int(m) + int(sec) / 60.0
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def _num(raw) -> float:
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return 0.0


def parse_summary(data: Optional[Dict]) -> Optional[Dict[str, Any]]:
    """Turn ONE raw ESPN hockey summary response into a compact record, or None if it has no
    usable boxscore:

      {"final": bool,
       "players": {player_id: {"team_id", "pos", "role": "skater"|"goalie", "toi",
                               skater: "g","a","pts","sog","blk"   goalie: "saves","sa","ga","gs"}},
       "teams":   {team_id: {"goals","assists","pts","sog","blk","saves","sa"}}}

    "gs" marks each team's goalie of record (most ice time, at least CFG.GOALIE_MIN_TOI minutes) —
    ESPN carries no starter flag. Team totals are summed from the player lines (goals here are the
    skaters' goals, so a shootout "winning goal" is not counted)."""
    if not data:
        return None
    box = data.get("boxscore") or {}
    groups_by_team = box.get("players") or []
    if not groups_by_team:
        return None
    comps = ((data.get("header") or {}).get("competitions") or [{}])
    final = bool(((comps[0].get("status") or {}).get("type") or {}).get("completed"))

    players: Dict[int, Dict[str, Any]] = {}
    for pg in groups_by_team:
        try:
            tid = int((pg.get("team") or {}).get("id"))
        except (TypeError, ValueError):
            continue
        for grp in pg.get("statistics") or []:
            is_goalie_grp = str(grp.get("name") or "").lower().startswith("goal")
            keys = grp.get("keys")
            if not keys:
                label_map = _GOALIE_LABELS if is_goalie_grp else _SKATER_LABELS
                keys = [label_map.get(lbl, lbl) for lbl in (grp.get("labels") or [])]
            for a in grp.get("athletes") or []:
                ath = a.get("athlete") or {}
                stats = a.get("stats") or []
                if a.get("didNotPlay") or not stats:
                    continue
                try:
                    pid = int(ath.get("id"))
                except (TypeError, ValueError):
                    continue
                m = dict(zip(keys, stats))
                toi = toi_minutes(m.get("timeOnIce"))
                if toi <= 0:
                    continue
                pos = (ath.get("position") or {}).get("abbreviation") or ("G" if is_goalie_grp else "")
                if is_goalie_grp:
                    saves, ga = _num(m.get("saves")), _num(m.get("goalsAgainst"))
                    sa = _num(m.get("shotsAgainst")) or (saves + ga)
                    players[pid] = {"team_id": tid, "pos": pos, "role": "goalie", "toi": toi,
                                    "saves": saves, "sa": sa, "ga": ga, "gs": False}
                else:
                    g, a_ = _num(m.get("goals")), _num(m.get("assists"))
                    players[pid] = {"team_id": tid, "pos": pos, "role": "skater", "toi": toi,
                                    "g": g, "a": a_, "pts": g + a_, "sog": _num(m.get("shotsTotal")),
                                    "blk": _num(m.get("blockedShots"))}

    # Goalie of record per team: most ice time, and at least GOALIE_MIN_TOI minutes.
    best: Dict[int, Tuple[float, int]] = {}
    for pid, rec in players.items():
        if rec["role"] != "goalie":
            continue
        cur = best.get(rec["team_id"])
        if cur is None or rec["toi"] > cur[0]:
            best[rec["team_id"]] = (rec["toi"], pid)
    for tid, (toi, pid) in best.items():
        if toi >= CFG.GOALIE_MIN_TOI:
            players[pid]["gs"] = True

    teams: Dict[int, Dict[str, float]] = {}
    for rec in players.values():
        t = teams.setdefault(rec["team_id"], {"goals": 0.0, "assists": 0.0, "pts": 0.0, "sog": 0.0,
                                              "blk": 0.0, "saves": 0.0, "sa": 0.0})
        if rec["role"] == "goalie":
            t["saves"] += rec["saves"]
            t["sa"] += rec["sa"]
        else:
            t["goals"] += rec["g"]
            t["assists"] += rec["a"]
            t["pts"] += rec["pts"]
            t["sog"] += rec["sog"]
            t["blk"] += rec["blk"]
    return {"final": final, "players": players, "teams": teams}


def get_game(game_id: str) -> Optional[Dict[str, Any]]:
    """The compact parsed record for one game (see parse_summary), fetched at most once per game
    per process for FINISHED games, and at most once per build for a failed fetch. Safe to call
    from many threads at once — a per-game lock stops N players' lookups from each re-downloading
    the same 400 KB response."""
    gid = str(game_id)
    with _cache_lock:
        if gid in _game_cache:
            return _game_cache[gid]
        if gid in _game_failed:
            return None
        lock = _game_locks.setdefault(gid, threading.Lock())
    with lock:
        with _cache_lock:
            if gid in _game_cache:
                return _game_cache[gid]
            if gid in _game_failed:
                return None
        data = _get_json(f"{SITE_API}/summary", params={"event": gid})
        parsed = parse_summary(data)          # the raw response is discarded right here
        with _cache_lock:
            if parsed is None:
                _game_failed.add(gid)
                _diag(f"get_game({gid}): no usable boxscore (fetch failed or no player data)")
            elif parsed["final"]:
                if len(_game_cache) >= _GAME_CACHE_MAX:
                    _game_cache.clear()
                _game_cache[gid] = parsed
            return parsed


def _prefetch_games(game_ids: List[str], max_workers: int = 16) -> None:
    """Warm the per-game cache in parallel so the per-player work below is pure lookups."""
    ids = [g for g in dict.fromkeys(str(x) for x in game_ids)]
    if not ids:
        return
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(get_game, ids))


# --------------------------------------------------------------------------- recent form
def get_team_recent_game_ids(team_id: int, before_date: str, n: int = CFG.RECENT_GAMES_N,
                             days_back: int = CFG.RECENT_DAYS_BACK) -> List[Dict[str, Any]]:
    """A team's last n COMPLETED games strictly before before_date, most recent first — thin
    wrapper over the shared basketball_engine scan (which owns the month/day scoreboard fallback)."""
    return BB.get_team_recent_game_ids(team_id, before_date, SITE_API, _get_json_cached, _diag,
                                       n=n, days_back=days_back, diag_seen=_diag_seen)


def player_log_from_games(player_id: int, games_info: List[Dict[str, Any]], is_goalie: bool,
                          last_n: int = CFG.RECENT_GAMES_N) -> List[Dict[str, float]]:
    """A player's game log from an already-fetched team game list (most recent first). Pure
    lookups on the per-game cache — call _prefetch_games first for speed.

    Skater log entry: {pts, ast, goals, sog, blk, toi, min, opp, date}. Goalie log entry: {saves,
    sa, ga, toi, min, opp, date} and ONLY for games he was the goalie of record — a backup who
    played a relief period would otherwise drag a starter-sized saves projection down."""
    out: List[Dict[str, float]] = []
    for g in games_info:
        game = get_game(g["gameId"])
        if not game:
            continue
        rec = game["players"].get(player_id)
        if not rec:
            continue
        if is_goalie:
            if rec["role"] != "goalie" or not rec["gs"]:
                continue
            out.append({"saves": rec["saves"], "sa": rec["sa"], "ga": rec["ga"], "toi": rec["toi"],
                        "min": rec["toi"], "opp": g.get("opp_name"), "date": g.get("date")})
        else:
            if rec["role"] != "skater":
                continue
            out.append({"pts": rec["pts"], "ast": rec["a"], "goals": rec["g"], "sog": rec["sog"],
                        "blk": rec["blk"], "toi": rec["toi"], "min": rec["toi"],
                        "opp": g.get("opp_name"), "date": g.get("date")})
    return out[:last_n]


def get_player_recent_games(player_id: int, last_n: int = CFG.RECENT_GAMES_N,
                            team_id: Optional[int] = None, before_date: Optional[str] = None,
                            days_back: int = CFG.RECENT_DAYS_BACK,
                            is_goalie: bool = False) -> List[Dict[str, float]]:
    """Last N game logs for one player, most recent first. Needs team_id and before_date (there is
    no way to know which games to look at otherwise) — empty list rather than a guess."""
    if team_id is None or before_date is None:
        return []
    games_info = get_team_recent_game_ids(team_id, before_date, last_n, days_back=days_back)
    return player_log_from_games(player_id, games_info, is_goalie, last_n)


_TEAM_STAT_KEYS = ("goals", "assists", "pts", "sog", "blk", "saves", "sa")


def _team_average(team_id: int, before_date: str, n: int, days_back: int, side: str) -> Dict[str, float]:
    games = get_team_recent_game_ids(team_id, before_date, n, days_back=days_back)
    totals: Dict[str, List[float]] = {k: [] for k in _TEAM_STAT_KEYS}
    for g in games:
        game = get_game(g["gameId"])
        if not game:
            continue
        teams = game["teams"]
        if side == "own":
            rec = teams.get(int(team_id))
        else:
            try:
                rec = teams.get(int(g.get("opp_id")))
            except (TypeError, ValueError):
                rec = None
        if rec:
            for k in _TEAM_STAT_KEYS:
                totals[k].append(rec.get(k, 0.0))
    return {k: (sum(v) / len(v) if v else 0.0) for k, v in totals.items()}


def get_team_recent_allowed_stats(team_id: int, before_date: str, n: int = CFG.RECENT_GAMES_N,
                                  days_back: int = CFG.RECENT_DAYS_BACK) -> Dict[str, float]:
    """Average totals this team's OPPONENTS put up against it over its last n games — shots on
    goal, goals, points, blocked shots (the defensive-trend signal). Zero extra network cost when a
    slate build already parsed those games."""
    return _team_average(team_id, before_date, n, days_back, "opp")


def get_team_recent_scored_stats(team_id: int, before_date: str, n: int = CFG.RECENT_GAMES_N,
                                 days_back: int = CFG.RECENT_DAYS_BACK) -> Dict[str, float]:
    """The mirror image: this team's OWN average totals (goals, shots, ...) over its last n games —
    what the "team trend" tag on Best Bets is built from (recent goals vs its own longer norm)."""
    return _team_average(team_id, before_date, n, days_back, "own")


def get_team_recent_scoring(team_id: int, before_date: str, n: int = CFG.RECENT_GAMES_N,
                            days_back: int = CFG.RECENT_DAYS_BACK) -> Dict[str, Any]:
    """{"goals_for", "goals_against", "games"}: this team's average final score over its last n
    completed games, read straight off the scoreboard events (no boxscore download at all — see
    basketball_engine.get_team_recent_game_ids' "score" fields). Includes shootout results (the
    winner's score carries the shootout goal), a small, symmetric distortion that is fine for a
    hot/cold tag. Empty games -> zeros with games=0, never a fabricated average."""
    gf, ga = [], []
    for g in get_team_recent_game_ids(team_id, before_date, n, days_back=days_back):
        try:
            gf.append(float(g["score"]))
            ga.append(float(g["opp_score"]))
        except (KeyError, TypeError, ValueError):
            continue
    if not gf:
        return {"goals_for": 0.0, "goals_against": 0.0, "games": 0}
    return {"goals_for": sum(gf) / len(gf), "goals_against": sum(ga) / len(ga), "games": len(gf)}


def get_team_rest_info(team_id: int, before_date: str, days_back: int = 10) -> Dict[str, Any]:
    """Rest days / back-to-back for a team heading into before_date (shared logic)."""
    return BB.get_team_rest_info(team_id, before_date, SITE_API, _get_json_cached, _diag,
                                 days_back=days_back, diag_seen=_diag_seen)


def get_team_injuries(team_abbr: str) -> List[Dict[str, Any]]:
    """Injury report by ESPN team abbreviation (confirmed live: .../hockey/nhl/injuries?team=COL).
    Informational display only — never folded into a projection."""
    return BB.get_team_injuries(team_abbr, SITE_API, _get_json_cached, _diag, diag_seen=_diag_seen)


# --------------------------------------------------------------------------- results (grading)
def get_player_results(date_str: str) -> Dict[int, Dict[str, float]]:
    """Actual per-player results for FINISHED games on date_str, keyed by integer player id — the
    same contract as the other engines, so retro.py / settle_results.py grade NHL plays with no
    special casing. Skaters carry {pts, ast, goals, sog, blk}; goalies carry {saves, sa, ga}.
    Games not yet final contribute nothing (a live game's partial box would grade a prop early)."""
    results: Dict[int, Dict[str, float]] = {}
    games = get_schedule(date_str)
    _prefetch_games([g["gameId"] for g in games])
    for g in games:
        game = get_game(g["gameId"])
        if not game or not game["final"]:
            continue
        for pid, rec in game["players"].items():
            if rec["role"] == "goalie":
                results.setdefault(pid, {}).update(
                    {"saves": rec["saves"], "sa": rec["sa"], "ga": rec["ga"]})
            else:
                results.setdefault(pid, {}).update(
                    {"pts": rec["pts"], "ast": rec["a"], "goals": rec["g"],
                     "sog": rec["sog"], "blk": rec["blk"]})
    return results


# --------------------------------------------------------------------------- pure logic
def avg_toi(game_log: List[Dict[str, float]]) -> float:
    return (sum(g["toi"] for g in game_log) / len(game_log)) if game_log else 0.0


def _avg(game_log: List[Dict[str, float]], key: str) -> float:
    return round(sum(g.get(key, 0.0) for g in game_log) / len(game_log), 2) if game_log else 0.0


def player_row(player: Dict, team_name: str, opp_name: str, game_label: str,
               game_date: Optional[str], game_log: List[Dict[str, float]],
               min_avg_toi: float = CFG.MIN_AVG_TOI,
               opp_id: Optional[int] = None, team_id: Optional[int] = None) -> Optional[Dict]:
    """Flat row for one player on the slate (mirrors the basketball engines' player_row: public
    display columns + private '_'-prefixed fields consumed by nhl_projections). None if a skater
    doesn't clear the TOI bar, or anyone has no log. A goalie's log only contains starts (see
    player_log_from_games), so a goalie row exists only for a recent goalie of record."""
    if not game_log:
        return None
    is_goalie = bool(player.get("is_goalie"))
    m = avg_toi(game_log)
    if not is_goalie and m < min_avg_toi:
        return None
    row = {
        "Player": player["name"], "Team": team_name, "GameLabel": game_label, "Opp": opp_name,
        "Pos": player.get("pos") or ("G" if is_goalie else ""),
        "Role": "goalie" if is_goalie else "skater",
        "AvgTOI": round(m, 1), "AvgMin": round(m, 1),     # AvgMin: same key the shared pages read
        "PTS": _avg(game_log, "pts"), "AST": _avg(game_log, "ast"), "G": _avg(game_log, "goals"),
        "SOG": _avg(game_log, "sog"), "BLK": _avg(game_log, "blk"), "SV": _avg(game_log, "saves"),
        "_pid": player["id"], "_game_log": game_log, "_game_date": game_date,
        "_opp_id": opp_id, "_team_id": team_id, "_role": "goalie" if is_goalie else "skater",
    }
    return row


# --------------------------------------------------------------------------- orchestration
def build_slate(date_str: str, min_avg_toi: float = CFG.MIN_AVG_TOI,
                last_n_games: int = CFG.RECENT_GAMES_N, max_workers: int = 16
                ) -> Tuple[List[Dict], List[Dict]]:
    """Fetch and assemble the full NHL slate. Returns (rows, meta) — the platform's cross-sport
    engine contract (see mlb_engine.build_slate / sports.py's Sport.engine).

    Order matters for cost: (1) schedule + rosters, (2) ONE recent-game list per team on the slate,
    (3) download + compact-parse every distinct game those lists name, in parallel, ONCE, (4) build
    every player's row from pure in-memory lookups. A goalie gets a row only if he was his team's
    goalie of record in one of its last CFG.GOALIE_LOOKBACK_GAMES games."""
    _response_cache.clear()
    _diag_seen.clear()
    with _cache_lock:
        _game_failed.clear()
    games = get_schedule(date_str)
    if not games:
        _diag(f"build_slate({date_str}): 0 games -> nothing to build")
        return [], []

    team_ids = sorted({tid for g in games for tid in (g["home_id"], g["away_id"])})
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        rosters = dict(zip(team_ids, ex.map(get_team_roster, team_ids)))
        team_games = dict(zip(team_ids, ex.map(
            lambda t: get_team_recent_game_ids(t, date_str, last_n_games), team_ids)))
    _prefetch_games([g["gameId"] for tg in team_games.values() for g in tg], max_workers=max_workers)

    meta: List[Dict] = []
    tasks: List[Tuple[Dict, str, str, str, Optional[str], int, int]] = []
    for g in games:
        label = f"{g['away_name']} @ {g['home_name']}"
        meta.append({"label": label, "away_name": g["away_name"], "home_name": g["home_name"],
                     "game_date": g.get("game_date"), "game_id": g.get("gameId"),
                     "home_id": g["home_id"], "home_abbr": g.get("home_abbr"),
                     "away_id": g["away_id"], "away_abbr": g.get("away_abbr")})
        for team_id, team_name, opp_name, opp_id in (
                (g["home_id"], g["home_name"], g["away_name"], g["away_id"]),
                (g["away_id"], g["away_name"], g["home_name"], g["home_id"])):
            for player in rosters[team_id]:
                tasks.append((player, team_name, opp_name, label, g.get("game_date"), team_id, opp_id))
    _diag(f"build_slate({date_str}): {len(games)} game(s) -> {len(tasks)} roster slot(s) to project")

    rows: List[Dict] = []
    for player, team_name, opp_name, label, game_date, team_id, opp_id in tasks:
        gi = team_games.get(team_id) or []
        if player.get("is_goalie"):
            recent_starters = {pid for g in gi[:CFG.GOALIE_LOOKBACK_GAMES]
                               for pid, rec in ((get_game(g["gameId"]) or {}).get("players") or {}).items()
                               if rec.get("role") == "goalie" and rec.get("gs")}
            if player["id"] not in recent_starters:
                continue
        log = player_log_from_games(player["id"], gi, bool(player.get("is_goalie")), last_n_games)
        row = player_row(player, team_name, opp_name, label, game_date, log, min_avg_toi, opp_id, team_id)
        if row is not None:
            rows.append(row)

    n_g = sum(1 for r in rows if r["Role"] == "goalie")
    _diag(f"build_slate({date_str}): {len(rows)} player(s) on the final slate "
          f"({len(rows) - n_g} skaters, {n_g} goalies; of {len(tasks)} roster slots checked)")
    return rows, meta
