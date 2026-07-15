"""
basketball_engine.py — league-agnostic basketball logic shared across ESPN-basketball-API sports
(WNBA today, NBA whenever that build starts).

SCOPE, DELIBERATELY NARROW: this holds exactly the pieces named as real duplication risk when this
extraction was scoped — pace/possession math, rest/back-to-back calc, and injury-report parsing —
plus their minimal direct plumbing (game-ids lookup, team-totals parsing, the stat-value helpers).
It does NOT hold schedule/roster fetching, player game-log assembly, or build_slate's orchestration.
Those are also basketball-generic in principle, but which parts of them need to diverge for NBA
isn't actually known yet — real endpoint quirks in wnba_engine.py (the CDN-vs-site-API boxscore
split, the made-attempted combo-key naming, the flat-vs-grouped roster shape) were only discovered
by building WNBA the hard way, not predictable in advance. Extracting those now would mean guessing
NBA's needs before NBA exists. The plan: write nba_engine.py as a copy-adapt of wnba_engine.py when
that build starts, and pull out whatever turns out to be genuinely identical then, with real
evidence instead of a guess — not speculatively now.

DEPENDENCY INJECTION, ON PURPOSE: every function here takes `fetch` (a _get_json-shaped callable)
and often `diag` (a _diag-shaped callable) as explicit parameters, rather than owning its own HTTP
client or print-logger. This is NOT abstraction for its own sake — it's what lets wnba_engine.py's
existing test suite (255 tests, many of which do `monkeypatch.setattr(E, "_get_json", ...)` or
`E._response_cache.clear()` directly against wnba_engine's own module state) keep working completely
unchanged. wnba_engine.py keeps owning its `_get_json`/`_get_json_cached`/`_diag`/`_response_cache`
exactly as before; its public functions become thin wrappers that pass those same objects in here.
A future nba_engine.py does the same with its own fetch/cache/diag — each sport module keeps an
independent cache lifecycle (cleared once per build_slate call), which also sidesteps any
cross-sport cache-collision question that a single shared cache dict would raise.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

FetchFn = Callable[..., Optional[Dict]]
DiagFn = Callable[[str], None]


def _noop_diag(msg: str) -> None:
    pass


# --------------------------------------------------------------------------- pure stat parsing
def parse_stat_value(raw, side: str = "left") -> float:
    """ESPN's boxscore stats are strings. Combo fields report made-attempted ('12-24'). Default
    side="left" returns the makes. side="right" returns the attempts instead — needed for the
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


def find_team_stat(stats_by_name: Dict[str, str], *candidates: str, side: str = "left") -> float:
    """Look up a team stat by trying each candidate name, exact match first, falling back to a
    prefix match. The prefix fallback exists because real CDN boxscore data can carry made-count
    stats under COMBO names ("threePointFieldGoalsMade-threePointFieldGoalsAttempted", not a bare
    "threePointFieldGoalsMade" key). parse_stat_value's "X-Y -> take X" logic handles the combo
    correctly once the right key is found; the fix here is finding it. side is forwarded to
    parse_stat_value unchanged. Returns 0.0 if nothing matches any candidate."""
    for c in candidates:
        if c in stats_by_name:
            return parse_stat_value(stats_by_name[c], side=side)
    for name, raw in stats_by_name.items():
        if any(name.startswith(c) for c in candidates):
            return parse_stat_value(raw, side=side)
    return 0.0


# --------------------------------------------------------------------------- schedule scanning
def get_team_recent_game_ids(team_id: int, before_date: str, site_api: str,
                             fetch: FetchFn, diag: DiagFn = _noop_diag,
                             n: int = 10, days_back: int = 45,
                             diag_seen: Optional[set] = None) -> List[Dict[str, Any]]:
    """A team's last n COMPLETED games STRICTLY BEFORE before_date (YYYY-MM-DD), most recent
    first: [{"gameId", "date", "opp_id", "opp_name"}, ...]. Found by scanning the scoreboard
    across a trailing window and filtering to games where this team appears as a competitor.

    days_back defaults to 45 (comfortably covers n=10 games at a several-games/week pace — the
    "recent form" use case). Callers needing head-to-head or season-wide history pass a much
    wider days_back (~200) and a large n, then filter the result themselves.

    "Strictly before" (not "at or before") matters beyond a live board: called for tonight's date,
    the game being projected is still STATUS_SCHEDULED anyway, but this function is also reused
    for retrospective grading of a PAST date, called AFTER that date's games have finished — at
    that point they're "completed" too, and without an explicit date cutoff they'd leak into their
    own pre-game sample (a real lookahead-bias bug, not just a hypothetical one)."""
    end = datetime.strptime(before_date, "%Y-%m-%d")
    start = end - timedelta(days=days_back)
    date_range = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"
    # limit=500: a full-season window can hold hundreds of league games across every team, and a
    # truncated result here would silently under-count a head-to-head history rather than error.
    data = fetch(f"{site_api}/scoreboard", params={"dates": date_range, "limit": 500})
    seen = diag_seen if diag_seen is not None else set()
    diag_key = (team_id, before_date, days_back)
    if not data:
        if diag_key not in seen:
            diag(f"get_team_recent_game_ids(team={team_id}): trailing-window scoreboard fetch returned nothing")
            seen.add(diag_key)
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
    if diag_key not in seen:
        diag(f"get_team_recent_game_ids(team={team_id}, before={before_date}, days_back={days_back}): "
            f"{len(result)} completed game(s) found ({len(data.get('events', []))} raw events scanned)")
        seen.add(diag_key)
    return result


# --------------------------------------------------------------------------- pace / possessions
def get_game_team_totals(game_id: str, cdn_api: str, fetch: FetchFn,
                         diag: DiagFn = _noop_diag,
                         diag_seen: Optional[set] = None) -> Dict[int, Dict[str, float]]:
    """{team_id: {pts, reb, ast, fg3m, poss}} TEAM-level totals for a game, from a CDN boxscore
    response's `boxscore.teams[]`. This is the foundation for "stats allowed" (an opponent-
    adjustment signal): a team's defensive profile is just the OTHER team's totals in each of
    their recent games.

    poss is an ESTIMATED POSSESSION count for that team's own box score in this game, using the
    standard formula FGA - OREB + TOV + 0.44*FTA (the same estimate used throughout basketball
    analytics for games without official play-by-play possession tracking). This exists to fix a
    real conflation in the "allowed" signal: "this team allows a lot" and "this team just plays
    fast, so everyone accumulates more against them" look identical in raw per-game allowed
    totals. Dividing an allowed stat by poss turns it into a per-possession rate, which isn't
    fooled by pace.

    Field-name matching is defensive (see find_team_stat) because the exact naming convention for
    team-level boxscore stats isn't guaranteed identical across every ESPN basketball property —
    pts/reb/ast/fg3m names were confirmed live for WNBA; FGA/FTA/OREB/TOV field names are an
    educated guess based on ESPN's other documented naming conventions. The diagnostic dump below
    fires if poss comes back 0 despite the team block being present — the safety net for a wrong
    guess to surface loudly instead of silently reverting to neutral factors everywhere."""
    data = fetch(cdn_api, params={"xhr": "1", "gameId": game_id})
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
        fga = find_team_stat(stats_by_name, "fieldGoalsMade-fieldGoalsAttempted",
                             "fieldGoalsAttempted", side="right")
        fta = find_team_stat(stats_by_name, "freeThrowsMade-freeThrowsAttempted",
                             "freeThrowsAttempted", side="right")
        oreb = find_team_stat(stats_by_name, "offensiveRebounds")
        tov = find_team_stat(stats_by_name, "totalTurnovers", "turnovers")
        poss = fga - oreb + tov + 0.44 * fta
        # "pts" fallback: a live NBA sample (a different ESPN endpoint, not this exact CDN one,
        # but showing the same team-level statistics[] shape) had NO "points" entry in
        # statistics[] at all — team score can live as a sibling "score" field on the team block
        # itself instead. Try the stats lookup first (this IS confirmed live for WNBA), fall back
        # to team_block["score"] rather than silently reporting 0.0 if the stats-based path comes
        # up empty despite the team block being present.
        pts = find_team_stat(stats_by_name, "points")
        if pts == 0.0:
            try:
                pts = float(team_block.get("score", 0) or 0)
            except (TypeError, ValueError):
                pts = 0.0
        out[tid] = {
            "pts": pts,
            "reb": find_team_stat(stats_by_name, "totalRebounds", "rebounds"),
            "ast": find_team_stat(stats_by_name, "assists"),
            "fg3m": find_team_stat(stats_by_name, "threePointFieldGoalsMade"),
            "poss": poss if poss > 0 else 0.0,
        }

    seen = diag_seen if diag_seen is not None else set()
    dump_key = f"_team_totals_shape_dump:{game_id}"
    all_core_zero = teams and all(
        v["pts"] == 0.0 and v["reb"] == 0.0 and v["ast"] == 0.0 and v["fg3m"] == 0.0
        for v in out.values()
    )
    # Catches a PARTIAL failure too — e.g. only "pts" silently wrong while reb/ast/fg3m parse
    # fine — not just the case where every field fails at once. A single bad field name would
    # otherwise produce a wrong number with zero diagnostic signal, the exact gap a live NBA
    # sample surfaced during verification (points wasn't found in statistics[] there, but the
    # other three fields were) — this fires the same safety net for that case, not just total
    # failure.
    any_core_zero = teams and any(
        v["pts"] == 0.0 or v["reb"] == 0.0 or v["ast"] == 0.0 or v["fg3m"] == 0.0
        for v in out.values()
    )
    any_poss_zero = teams and any(v["poss"] == 0.0 for v in out.values())
    if (all_core_zero or any_core_zero or any_poss_zero) and dump_key not in seen:
        seen.add(dump_key)
        tb0 = teams[0]
        diag(f"get_game_team_totals({game_id}) shape dump: team_block keys = {list(tb0.keys())}")
        stat_names = [s.get("name") for s in tb0.get("statistics", [])]
        diag(f"get_game_team_totals({game_id}) shape dump: statistics[].name values = {stat_names}")
        if any_core_zero and not all_core_zero:
            zero_fields = sorted({k for v in out.values() for k in ("pts", "reb", "ast", "fg3m") if v[k] == 0.0})
            diag(f"get_game_team_totals({game_id}): PARTIAL failure — {zero_fields} came back 0 while "
                f"other core fields parsed fine — those specific candidate field names are likely wrong")
        if any_poss_zero and not all_core_zero:
            diag(f"get_game_team_totals({game_id}): poss=0 while pts/reb/ast/fg3m parsed fine — "
                f"FGA/FTA/OREB/TOV candidate field names likely wrong, see values above")
    return out


def get_team_recent_allowed_stats(team_id: int, before_date: str, site_api: str, cdn_api: str,
                                  fetch: FetchFn, diag: DiagFn = _noop_diag,
                                  n: int = 10, days_back: int = 45,
                                  diag_seen: Optional[set] = None) -> Dict[str, float]:
    """Average PTS/REB/AST/FG3M this team has ALLOWED over their last n completed games — i.e.,
    their opponents' team totals in those same games. Also averages "poss" — the opponent's own
    estimated possessions in each of those same games. This is what turns a raw "allowed" total
    into a pace-adjusted rate downstream — without it, a fast-paced team looks like a bad defense
    simply because there were more possessions to allow stats in."""
    games = get_team_recent_game_ids(team_id, before_date, site_api, fetch, diag, n,
                                     days_back=days_back, diag_seen=diag_seen)
    totals = {"pts": [], "reb": [], "ast": [], "fg3m": [], "poss": []}
    for g in games:
        opp_id = g.get("opp_id")
        if opp_id is None:
            continue
        try:
            opp_id = int(opp_id)
        except (TypeError, ValueError):
            continue
        game_totals = get_game_team_totals(g["gameId"], cdn_api, fetch, diag, diag_seen=diag_seen)
        opp_totals = game_totals.get(opp_id)
        if opp_totals:
            for k in totals:
                totals[k].append(opp_totals.get(k, 0.0))
    return {k: (sum(v) / len(v) if v else 0.0) for k, v in totals.items()}


# --------------------------------------------------------------------------- rest / back-to-back
def get_team_rest_info(team_id: int, before_date: str, site_api: str,
                       fetch: FetchFn, diag: DiagFn = _noop_diag,
                       days_back: int = 10, diag_seen: Optional[set] = None) -> Dict[str, Any]:
    """Rest context for a team heading into `before_date`: how many days since their last
    completed game, and whether tonight is the second night of a back-to-back. days_back defaults
    to a short 10 days (not the 45-day "recent form" window) — rest only cares about the
    IMMEDIATELY prior game, so a short scan is both cheap and sufficient. A team with no completed
    game in the last 10 days (start of season, All-Star break) reports rest_days=None rather than
    a fabricated "well-rested" guess — an honest unknown, not a default.

    Returns {"rest_days": int|None, "is_back_to_back": bool, "last_game_date": str|None,
    "last_opp_name": str|None}. is_back_to_back is True when rest_days <= 1."""
    games = get_team_recent_game_ids(team_id, before_date, site_api, fetch, diag, n=1,
                                     days_back=days_back, diag_seen=diag_seen)
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


# --------------------------------------------------------------------------- injuries
def get_team_injuries(team_abbr: str, site_api: str, fetch: FetchFn,
                      diag: DiagFn = _noop_diag, diag_seen: Optional[set] = None) -> List[Dict[str, Any]]:
    """Team injury report for one team, by ESPN abbreviation (e.g. "ATL") — NOT team_id, since
    this endpoint keys by abbreviation. Confirmed live: site.api.espn.com/apis/site/v2/sports/
    basketball/nba/injuries?team=ATL returns real, current per-player injury records, sourced from
    Rotowire; espn.com/wnba/injuries confirmed live and current for the 2026 WNBA season the same
    scoping pass. Both NBA and WNBA follow the identical site.api.espn.com/apis/site/v2/sports/
    basketball/{league} pattern this module relies on — just the league slug differs.

    Returns [{"player", "status", "position", "return_date", "comment"}, ...] — one entry per
    currently-listed injury. An empty list is a team with no news reported, treated as healthy —
    there's no reliable way to distinguish "confirmed healthy" from "fetch problem" from this
    endpoint alone, and treating silence as good news is the honest default here.

    "status" (e.g. "Out", "Day-To-Day", "Questionable") is intentionally left as the raw text
    ESPN/Rotowire assigned, not translated into a boolean playing/not-playing call — collapsing
    "Day-To-Day" into a hard out wouldn't be honest. Informational display only — does NOT feed
    into any computed signal; quantifying an "opportunity boost" for teammates when a key player
    sits is a genuinely separate, harder modeling decision, deferred rather than guessed at here."""
    if not team_abbr:
        return []
    data = fetch(f"{site_api}/injuries", params={"team": team_abbr})
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

    seen = diag_seen if diag_seen is not None else set()
    dump_key = f"_injuries_shape_dump:{team_abbr}"
    if data.get("injuries") and not any(o["player"] for o in out) and dump_key not in seen:
        seen.add(dump_key)
        diag(f"get_team_injuries({team_abbr}) shape dump: first injury item keys = "
            f"{list(data['injuries'][0].keys())}")
    return out
