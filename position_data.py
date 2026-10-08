"""
position_data.py — loads the data behind the Position Matchups page, per sport, and assembles one
game's bundle (both teams' depth vs the other's defense, plus team head-to-head).

The pure maths lives in position_matchups.py; this module is the I/O and the sport-specific column
mapping. Every loader fails soft: a source that can't be read yields empty data plus a plain-language
note, never an exception, so one missing feed degrades one section of the page instead of the page.

SOURCES
  NFL    nflreadpy weekly player stats (usage -> slots), nflreadpy depth charts (the real chart),
         nflreadpy injuries, nflreadpy schedules (head-to-head, three seasons).
  NCAAF  the cached CFBD per-game player stats + rosters (positions) + cached schedule. No depth-chart
         feed exists here, so depth is the usage ranking over recent games.
  NBA    ESPN scoreboard (finds the league's recent games) + CDN box scores (player lines by team) +
         rosters (positions). League-wide, so every defense can be ranked.
  NCAAMB the same ESPN feeds but ONLY the two teams' own recent games — Division I is 360 teams, far
         too many box scores to rank — so NCAAMB shows allowed-per-game by position without a rank.
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import position_matchups as PM

MIN_GAMES_FOR_RANK = PM.MIN_GAMES_FOR_RANK
MIN_TEAMS_FOR_RANK = PM.MIN_TEAMS_FOR_RANK
LEAGUE_WINDOW_DAYS = 28         # basketball: the league-wide look-back for the in-season sample
LEAGUE_GAMES_PER_TEAM = 7       # basketball: games kept per team in the league sample
H2H_BASKETBALL_DAYS = 400       # how far back a basketball head-to-head looks (about a year and a bit)


def _n(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(v) or math.isinf(v) else v


# =========================================================================== football: player-game lines
_NFL_COLS = {"pass_att": "attempts", "pass_yds": "passing_yards", "pass_td": "passing_tds",
             "pass_int": "passing_interceptions", "rush_att": "carries", "rush_yds": "rushing_yards",
             "rush_td": "rushing_tds", "tgt": "targets", "rec": "receptions", "rec_yds": "receiving_yards",
             "rec_td": "receiving_tds"}
_NCAAF_COLS = {"pass_att": "passing_ATT", "pass_yds": "passing_YDS", "pass_td": "passing_TD",
               "pass_int": "passing_INT", "rush_att": "rushing_CAR", "rush_yds": "rushing_YDS",
               "rush_td": "rushing_TD", "rec": "receiving_REC", "rec_yds": "receiving_YDS",
               "rec_td": "receiving_TD"}
_SKILL_POS = {"QB", "RB", "FB", "HB", "WR", "TE"}


def _has(x) -> bool:
    """A usable text value: not None, not NaN (pandas passes NaN through and NaN is truthy), not blank."""
    if x is None:
        return False
    text = str(x).strip()
    return bool(text) and text.lower() != "nan"


def nfl_pgames(weekly, before_week: int) -> List[Dict]:
    """nflreadpy's weekly player-stats table -> player-game lines for QB/RB/FB/WR/TE in weeks BEFORE
    `before_week` (strictly — the game being looked at must not leak into its own sample)."""
    if weekly is None or len(weekly) == 0:
        return []
    out: List[Dict] = []
    for r in weekly.to_dict("records"):
        pos = str(r.get("position") or "").upper()
        wk = r.get("week")
        if pos not in _SKILL_POS or wk is None or not (int(wk) < before_week):
            continue
        team, opp = r.get("team"), r.get("opponent_team")
        if not _has(team) or not _has(opp):
            continue
        out.append({"game": f"{int(wk)}-{team}", "order": int(wk), "team": team, "opp": opp,
                    "pid": r.get("player_id"), "name": r.get("player_display_name") or r.get("player_name"),
                    "pos": pos, "stats": {k: _n(r.get(c)) for k, c in _NFL_COLS.items()}})
    return out


def ncaaf_pgames(rows: Iterable[Dict], season: int, before_week: int, position_by_id: Dict[str, str]) -> List[Dict]:
    """The cached CFBD per-game rows -> player-game lines for `season`, weeks before `before_week`.
    The cache carries no position, so it comes from the roster by player id; a player with no listed
    position is left out (his usage can't be assigned a slot)."""
    out: List[Dict] = []
    for r in rows or []:
        wk, ssn = r.get("week"), r.get("season")
        if wk is None or ssn is None or int(ssn) != int(season) or not (int(wk) < before_week):
            continue
        team, opp, pid = r.get("team"), r.get("opponent_team"), r.get("player_id")
        if not _has(team) or not _has(opp) or pid is None:
            continue
        pos = str(position_by_id.get(str(pid)) or "").upper()
        if pos not in _SKILL_POS:
            continue
        out.append({"game": r.get("game_id") if r.get("game_id") is not None else f"{int(wk)}-{team}",
                    "order": int(wk), "team": team, "opp": opp, "pid": str(pid), "name": r.get("player"),
                    "pos": pos, "stats": {k: _n(r.get(c)) for k, c in _NCAAF_COLS.items()}})
    return out


def clean_status(x) -> Optional[str]:
    """An injury-report status as text, or None for a missing/NaN value (pandas hands NaN through)."""
    if x is None:
        return None
    s = str(x).strip()
    return None if not s or s.lower() in ("nan", "none") else s


def football_depth_from_chart(chart_rows: Iterable[Dict], injuries: Optional[Dict[str, str]] = None) -> Dict[str, List[Dict]]:
    """One team's published depth chart rows (nflreadpy shape: pos_abb, pos_rank, player_name, gsis_id)
    -> {slot: [{"pid","name","status"}]}. WRs fill WR1..WR3 in chart order and the rest ride along as
    depth; a back's backups fill RB2; the first TE is TE1. `injuries` is {player name: report status}."""
    injuries = injuries or {}
    by_pos: Dict[str, List[Dict]] = {}
    seen: set = set()
    for r in sorted(chart_rows or [], key=lambda r: (_n(r.get("pos_rank")) or 99)):
        pos = str(r.get("pos_abb") or "").upper()
        grp = "RB" if pos in ("RB", "HB") else pos
        if grp not in ("QB", "RB", "FB", "WR", "TE"):
            continue
        key = (grp, r.get("gsis_id") or r.get("player_name"))
        if key in seen:
            continue
        seen.add(key)
        by_pos.setdefault(grp, []).append({"pid": r.get("gsis_id"), "name": r.get("player_name"),
                                           "status": clean_status(injuries.get(r.get("player_name")))})
    out: Dict[str, List[Dict]] = {}
    if by_pos.get("QB"):
        out["QB"] = by_pos["QB"]
    rbs = by_pos.get("RB", [])
    if rbs:
        out["RB1"] = rbs[:1]
    if len(rbs) > 1:
        out["RB2"] = rbs[1:2]
    for i, slot in enumerate(("WR1", "WR2", "WR3")):
        if len(by_pos.get("WR", [])) > i:
            out[slot] = [by_pos["WR"][i]]
    if by_pos.get("TE"):
        out["TE1"] = by_pos["TE"][:2]
    return out


def latest_depth_chart_rows(df, team: str) -> List[Dict]:
    """The newest snapshot's OFFENSE rows for one team out of nflreadpy's depth-chart table (which holds
    a snapshot per day). Rows from the defensive/special-teams formations are dropped."""
    if df is None or len(df) == 0:
        return []
    mine = df[df["team"] == team]
    if len(mine) == 0:
        return []
    newest = mine["dt"].max()
    mine = mine[mine["dt"] == newest]
    mine = mine[~mine["pos_grp"].astype(str).str.startswith(("Base", "Special"))]
    return mine.to_dict("records")


# =========================================================================== basketball: box-score sample
def parse_scoreboard_events(events: Iterable[Dict], before_date: str, start_date: str,
                            keep_type: Callable[[Optional[int]], bool]) -> List[Dict]:
    """Scoreboard events -> completed games in [start_date, before_date) whose season type passes
    `keep_type`: [{"gid","date","home","away","type"}] (team ids as ints, None-safe)."""
    out: List[Dict] = []
    for ev in events or []:
        status = ((ev.get("status") or {}).get("type") or {})
        if not status.get("completed"):
            continue
        d = (ev.get("date") or "")[:10]
        if not d or d >= before_date or d < start_date:
            continue
        stype = (ev.get("season") or {}).get("type")
        if not keep_type(stype):
            continue
        comps = ev.get("competitions") or []
        if not comps or not ev.get("id"):
            continue
        sides: Dict[str, int] = {}
        for c in comps[0].get("competitors") or []:
            try:
                sides[c.get("homeAway") or f"x{len(sides)}"] = int((c.get("team") or {}).get("id"))
            except (TypeError, ValueError):
                continue
        ids = list(sides.values())
        if len(sides) != 2 or ids[0] == ids[1]:
            continue
        out.append({"gid": ev["id"], "date": ev.get("date") or d, "home": sides.get("home", ids[0]),
                    "away": sides.get("away", ids[1]), "type": stype})
    return out


def pick_recent_per_team(games: Iterable[Dict], per_team: int) -> Dict[str, Dict]:
    """Keep each team's `per_team` most recent games; the union is the sample. {gid: game}."""
    ordered = sorted(games, key=lambda g: g["date"], reverse=True)
    counts: Dict[int, int] = {}
    keep: Dict[str, Dict] = {}
    for g in ordered:
        take = False
        for t in (g["home"], g["away"]):
            if counts.get(t, 0) < per_team:
                take = True
        if not take:
            continue
        keep[g["gid"]] = g
        for t in (g["home"], g["away"]):
            counts[t] = counts.get(t, 0) + 1
    return keep


def teams_with_enough(games: Iterable[Dict], at_least: int) -> int:
    counts: Dict[int, int] = {}
    for g in games:
        for t in (g["home"], g["away"]):
            counts[t] = counts.get(t, 0) + 1
    return sum(1 for c in counts.values() if c >= at_least)


def basketball_pgames(game_lines: Dict[str, Dict], roster_pos: Dict[int, str]) -> List[Dict]:
    """{gid: {"date", "lines": {team_id: [player line]}}} -> player-game lines. Each game's two teams
    are each other's opponent. A player's position is the box score's own when it carried one, else the
    roster's (`roster_pos` {player id: abbreviation}); one with neither is left out of the slot maths."""
    out: List[Dict] = []
    for gid, g in game_lines.items():
        lines = g.get("lines") or {}
        teams = list(lines)
        if len(teams) != 2:
            continue
        for tid in teams:
            opp = teams[1] if tid == teams[0] else teams[0]
            for p in lines[tid]:
                pos = p.get("pos") or roster_pos.get(p["id"])
                out.append({"game": gid, "order": g.get("date"), "team": tid, "opp": opp, "pid": p["id"],
                            "name": p["name"], "pos": pos,
                            "stats": {"min": _n(p.get("min")), "pts": _n(p.get("pts")), "reb": _n(p.get("reb")),
                                      "ast": _n(p.get("ast")), "fg3m": _n(p.get("fg3m"))}})
    return out


# =========================================================================== assembling one game
def build_side(sport: str, offense: Any, defense: Any, depth: Dict[str, List[Dict]],
               allowed: Dict[str, List[Dict]], pgames: List[Dict]) -> Dict:
    """One direction of a game: `offense`'s depth vs `defense`'s record. `ranked` is how many defenses were
    ranked (the most at any slot) — 0 means no ranks could be given."""
    season_sum = PM.summarize(allowed, sport)
    recent_sum = PM.summarize(allowed, sport, n=PM.RECENT_N)
    rows = PM.matchup_rows(sport, depth, defense, season_sum, recent_sum, pgames)
    pool = PM.ranking_pool(season_sum)
    ranked = max((len(PM.rank_slot(pool, s)) for s in PM.SLOTS_BY_SPORT[sport]), default=0)
    return {"offense": offense, "defense": defense, "rows": rows, "ranked": ranked if ranked >= MIN_TEAMS_FOR_RANK else 0}


def fill_depth_from_usage(depth: Dict[str, List[Dict]], usage: Dict[str, List[Dict]], sport: str) -> Dict[str, List[Dict]]:
    """Slots the published chart didn't give (or all of them) filled from recent usage."""
    out = {slot: list(v) for slot, v in (depth or {}).items()}
    for slot in PM.SLOTS_BY_SPORT[sport]:
        if out.get(slot):
            continue
        if usage.get(slot):
            out[slot] = [{"pid": u["pid"], "name": u["name"], "status": None,
                          "note": (f"{u['avg_min']:.0f} min" if PM.FAMILY_BY_SPORT[sport] == "basketball"
                                   else f"held the slot in {u['games_in_slot']} of the last {PM.RECENT_N} games")}
                         for u in usage[slot]]
    return out


def build_bundle(sport: str, home: Any, away: Any, pgames: List[Dict], depth: Dict[Any, Dict[str, List[Dict]]],
                 h2h_games: List[Dict], names: Optional[Dict[Any, str]] = None, notes: Optional[List[str]] = None) -> Dict:
    """Everything the page renders for one game. `home`/`away` are the keys used in `pgames` (names or
    ids); `names` maps a key to its display name."""
    names = names or {}
    allowed = PM.allowed_by_slot(pgames, sport)
    bundle = {"sport": sport, "metric": PM.METRIC_LABEL[PM.FAMILY_BY_SPORT[sport]],
              "home": home, "away": away, "names": {home: names.get(home, home), away: names.get(away, away)},
              "notes": list(notes or [])}
    for side, off, de in (("home_off", home, away), ("away_off", away, home)):
        usage = PM.usage_depth(pgames, off, sport)
        dep = fill_depth_from_usage(depth.get(off) or {}, usage, sport)
        bundle[side] = build_side(sport, off, de, dep, allowed, pgames)
        if not bundle[side]["rows"] or all(not r["players"] for r in bundle[side]["rows"]):
            bundle["notes"].append(f"No depth chart or recent usage found for {names.get(off, off)}.")
    meetings = PM.h2h_meetings(h2h_games, home, away)
    summ = PM.h2h_summary(meetings, home, away)
    bundle["h2h"] = {"meetings": meetings, "summary": summ,
                     "sentence": PM.h2h_sentence(summ, names.get(home, home), names.get(away, away))}
    bundle["games_sampled"] = len(allowed.get(home, [])), len(allowed.get(away, []))
    return bundle


# =========================================================================== per-sport orchestration
def _safe(fn: Callable, default, notes: List[str], what: str):
    try:
        return fn()
    except Exception as exc:                                    # noqa: BLE001 — fail soft, say so
        notes.append(f"Couldn't load {what} ({type(exc).__name__}).")
        return default


def load_football(sport_key: str, date_str: str, home: str, away: str, use_previous_season: bool = False) -> Dict:
    """NFL or NCAAF bundle for one game. Football keys are team names/abbreviations on both sides."""
    import sports
    notes: List[str] = []
    eng = sports.get(sport_key).engine
    season = eng._infer_season(date_str)
    if season is None:
        return build_bundle(sport_key, home, away, [], {}, [], notes=["Couldn't work out the season for this date."])
    sched = _safe(lambda: eng.get_schedule(season), [], notes, "the schedule")
    week = eng._resolve_week(sched, date_str) or 1
    stats_season = season - 1 if use_previous_season else season
    before_week = 999 if use_previous_season else week
    if sport_key == "NFL":
        weekly = _safe(lambda: eng.load_season_weekly_stats(stats_season), None, notes, "NFL weekly stats")
        pgames = nfl_pgames(weekly, before_week)
    else:
        import ncaaf_data as ND
        roster = _safe(ND.load_rosters, [], notes, "the college roster cache")
        pos_by_id = {str(p.get("id")): p.get("position") for p in roster if p.get("id") is not None}
        rows = _safe(ND.load_player_game_stats, [], notes, "the college per-game cache")
        pgames = ncaaf_pgames(rows, stats_season, before_week, pos_by_id)
    if not pgames:
        notes.append(f"No {stats_season} player-game data on file yet — try the other season option.")
    elif not use_previous_season:
        notes.append(f"Based on {stats_season} games through week {week - 1}." if week > 1 else
                     f"The {stats_season} season hasn't produced games yet.")
    depth: Dict[Any, Dict[str, List[Dict]]] = {}
    if sport_key == "NFL":
        depth = _nfl_depths(eng, season, week, (home, away), notes)
    else:
        notes.append("College football has no published depth-chart feed here, so depth is the usage ranking "
                     f"over each team's last {PM.RECENT_N} games.")
    return build_bundle(sport_key, home, away, pgames, depth, _football_h2h_games(sport_key, eng, season), notes=notes)


def _nfl_depths(eng, season: int, week: int, teams: Tuple[str, str], notes: List[str]) -> Dict[str, Dict[str, List[Dict]]]:
    import nflreadpy as nfl
    try:
        df = nfl.load_depth_charts(min(season, nfl.get_current_season())).to_pandas()
    except Exception:                                           # noqa: BLE001
        notes.append("Couldn't load NFL depth charts; depth below is each team's recent usage.")
        return {}
    out: Dict[str, Dict[str, List[Dict]]] = {}
    for t in teams:
        inj = {i.get("player"): clean_status(i.get("status")) for i in _safe(lambda: eng.get_team_injuries(t, season, week), [], notes, "injuries")}
        out[t] = football_depth_from_chart(latest_depth_chart_rows(df, t), inj)
    return out


def _football_h2h_games(sport_key: str, eng, season: int) -> List[Dict]:
    out: List[Dict] = []
    if sport_key == "NFL":
        for s in (season, season - 1, season - 2):
            try:
                for g in eng.get_schedule(s):
                    out.append({"date": g.get("game_date"), "home": g.get("home_team"), "away": g.get("away_team"),
                                "home_score": g.get("home_score"), "away_score": g.get("away_score"), "season": s})
            except Exception:                                   # noqa: BLE001
                continue
        return out
    try:
        import ncaaf_data as ND
        for g in ND.load_schedule():
            out.append({"date": g.get("start_date"), "home": g.get("home_team"), "away": g.get("away_team"),
                        "home_score": g.get("home_points"), "away_score": g.get("away_points"), "season": g.get("season")})
    except Exception:                                           # noqa: BLE001
        pass
    return out


def basketball_h2h_games(eng, team_id: int, opp_id: int, date_str: str, a_name: str, b_name: str) -> List[Dict]:
    """A team's finished games against one opponent from the scoreboard window (exhibitions left out),
    as head-to-head game dicts keyed by the two teams' display names."""
    try:
        found = eng.get_team_recent_game_ids(team_id, date_str, 80, days_back=H2H_BASKETBALL_DAYS)
    except Exception:                                           # noqa: BLE001
        return []
    out = []
    for g in found:
        if str(g.get("opp_id")) != str(opp_id) or g.get("season_type") == 1:
            continue
        try:
            mine, theirs = float(g.get("score")), float(g.get("opp_score"))
        except (TypeError, ValueError):
            continue
        a_home = g.get("home_away") != "away"
        out.append({"date": g.get("date"), "home": a_name if a_home else b_name, "away": b_name if a_home else a_name,
                    "home_score": mine if a_home else theirs, "away_score": theirs if a_home else mine})
    return out


def _fetch_lines(eng, gids: List[str]) -> Dict[str, Dict[int, List[Dict]]]:
    import basketball_engine as BB
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda g: BB.get_game_player_lines(g, eng.CDN_API, eng._get_json_cached), gids))
    return dict(zip(gids, results))


def load_basketball(sport_key: str, date_str: str, home_id: int, away_id: int, home_name: str, away_name: str,
                    home_abbr: Optional[str] = None, away_abbr: Optional[str] = None) -> Dict:
    """NBA or NCAAMB bundle for one game (teams keyed by ESPN team id)."""
    import basketball_engine as BB
    import sports
    eng = sports.get(sport_key).engine
    notes: List[str] = []
    games: Dict[str, Dict] = {}
    if sport_key == "NBA":
        games, src_note = _nba_league_sample(eng, date_str, notes)
        if src_note:
            notes.append(src_note)
    else:
        for tid in (home_id, away_id):
            for g in _safe(lambda: eng.get_team_recent_game_ids(tid, date_str, 10), [], notes, "recent games"):
                if g.get("season_type") == 1:
                    continue
                games.setdefault(g["gameId"], {"date": g.get("date") or "", "home": tid, "away": g.get("opp_id")})
        notes.append("College basketball has 360 teams, so only these two teams' own recent games are used: "
                     "allowed-per-game by position is shown, with no league rank.")
    lines = _fetch_lines(eng, list(games))
    game_lines = {gid: {"date": games[gid].get("date"), "lines": lines.get(gid) or {}} for gid in games}
    roster_pos = _roster_positions(eng, game_lines, notes)
    pgames = basketball_pgames(game_lines, roster_pos)
    if not pgames:
        notes.append("No box-score data found for this window yet.")
    depth: Dict[Any, Dict[str, List[Dict]]] = {}
    for tid, abbr in ((home_id, home_abbr), (away_id, away_abbr)):
        inj = _injury_map(eng, abbr)
        usage = PM.usage_depth(pgames, tid, sport_key, last_n=LEAGUE_GAMES_PER_TEAM)
        depth[tid] = {slot: [dict(u, status=inj.get(u["name"]), note=f"{u['avg_min']:.0f} min") for u in lst]
                      for slot, lst in usage.items()}
    h2h = basketball_h2h_games(eng, home_id, away_id, date_str, home_name, away_name)
    bundle = build_bundle(sport_key, home_id, away_id, pgames, depth, [], names={home_id: home_name, away_id: away_name},
                          notes=notes)
    meetings = PM.h2h_meetings(h2h, home_name, away_name)
    summ = PM.h2h_summary(meetings, home_name, away_name)
    bundle["h2h"] = {"meetings": meetings, "summary": summ, "sentence": PM.h2h_sentence(summ, home_name, away_name)}
    return bundle


def _injury_map(eng, abbr: Optional[str]) -> Dict[str, str]:
    if not abbr:
        return {}
    try:
        return {i.get("player"): clean_status(i.get("status")) for i in eng.get_team_injuries(abbr)}
    except Exception:                                           # noqa: BLE001
        return {}


def _nba_league_sample(eng, date_str: str, notes: List[str]) -> Tuple[Dict[str, Dict], Optional[str]]:
    """League-wide recent games for the NBA: this season's last LEAGUE_WINDOW_DAYS (exhibitions out); when too
    few teams have 3 games (opening weeks, preseason), the end of LAST regular season instead."""
    import basketball_engine as BB
    end = datetime.strptime(date_str, "%Y-%m-%d")

    def collect(cutoff: datetime, days: int, keep) -> List[Dict]:
        start = cutoff - timedelta(days=days)
        ev = BB.scoreboard_events_in_window(eng.SITE_API, eng._get_json_cached, start.date(), cutoff.date())
        return parse_scoreboard_events(ev or [], cutoff.strftime("%Y-%m-%d"), start.strftime("%Y-%m-%d"), keep)

    try:
        current = collect(end, LEAGUE_WINDOW_DAYS, lambda t: t != 1)
    except Exception:                                           # noqa: BLE001
        current = []
    if teams_with_enough(current, MIN_GAMES_FOR_RANK) >= 20:
        return pick_recent_per_team(current, LEAGUE_GAMES_PER_TEAM), None
    try:
        opener = datetime.strptime(eng.SEASON_START, "%Y-%m-%d")
        prior = collect(min(end, opener), eng.PRIOR_LOOKBACK_DAYS, lambda t: t == 2)
    except Exception:                                           # noqa: BLE001
        prior = []
    if prior:
        return pick_recent_per_team(prior, LEAGUE_GAMES_PER_TEAM), \
            "The new season hasn't played enough games to rank defenses, so this uses the end of last regular season."
    return pick_recent_per_team(current, LEAGUE_GAMES_PER_TEAM), None


def _roster_positions(eng, game_lines: Dict[str, Dict], notes: List[str]) -> Dict[int, str]:
    """{player id: position abbr} for every player in the sample whose box score didn't say; one roster
    fetch per team that needs it."""
    need_teams = set()
    for g in game_lines.values():
        for tid, plist in (g.get("lines") or {}).items():
            if any(not p.get("pos") for p in plist):
                need_teams.add(tid)
    pos: Dict[int, str] = {}
    if not need_teams:
        return pos
    teams = sorted(need_teams)
    with ThreadPoolExecutor(max_workers=8) as ex:
        for roster in ex.map(lambda t: _safe(lambda: eng.get_team_roster(t), [], notes, "a roster"), teams):
            for p in roster:
                if p.get("pos"):
                    pos[p["id"]] = p["pos"]
    if not pos:
        notes.append("Player positions weren't available from ESPN, so position groups can't be built.")
    return pos


# =========================================================================== the game list
def list_games(sport_key: str, date_str: str) -> List[Dict]:
    """The games the page offers for `date_str`, chronological, each
    {"label","home","away","home_id","away_id","home_abbr","away_abbr","game_date"} ("home"/"away" are
    the names used as football keys). Football is a WEEKLY slate (the week the date falls in); basketball
    is that day's scoreboard. Light on purpose — schedule data only, never a full slate build."""
    import sports
    eng = sports.get(sport_key).engine
    out: List[Dict] = []
    if sport_key in ("NFL", "NCAAF"):
        season = eng._infer_season(date_str)
        if season is None:
            return []
        sched = eng.get_schedule(season)
        week = eng._resolve_week(sched, date_str)
        if week is None:
            return []
        for g in eng.games_for_week(sched, week):
            if sport_key == "NFL":
                iso = eng.kickoff_utc_iso(g.get("game_date"), g.get("game_time")) or g.get("game_date")
                home, away = g.get("home_team"), g.get("away_team")
            else:
                iso, home, away = g.get("start_date"), g.get("home_team"), g.get("away_team")
            if not home or not away:
                continue
            out.append({"label": f"{away} @ {home}", "home": home, "away": away, "home_id": home, "away_id": away,
                        "home_abbr": home, "away_abbr": away, "game_date": iso, "week": week})
    else:
        for g in eng.get_schedule(date_str):
            out.append({"label": f"{g['away_name']} @ {g['home_name']}", "home": g["home_name"], "away": g["away_name"],
                        "home_id": g["home_id"], "away_id": g["away_id"], "home_abbr": g.get("home_abbr"),
                        "away_abbr": g.get("away_abbr"), "game_date": g.get("game_date")})
    out.sort(key=lambda g: g.get("game_date") or "~")
    return out


def load_bundle(sport_key: str, date_str: str, game: Dict, use_previous_season: bool = False) -> Dict:
    """One call for the page: the bundle for one game from list_games()."""
    if PM.FAMILY_BY_SPORT[sport_key] == "football":
        return load_football(sport_key, date_str, game["home"], game["away"], use_previous_season)
    return load_basketball(sport_key, date_str, game["home_id"], game["away_id"], game["home"], game["away"],
                           game.get("home_abbr"), game.get("away_abbr"))
