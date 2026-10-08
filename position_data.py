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
import position_pbp as PP

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


# =========================================================================== NFL game log (two seasons stacked)
def stack_nfl_pgames(weekly, season: int, before_order: Optional[int] = None) -> List[Dict]:
    """One season's weekly player stats -> player-game lines whose `order` is the composite season * 100 + week
    (so two seasons sort together), stopping short of `before_order` (exclusive). Playoff weeks are included."""
    out = []
    for p in nfl_pgames(weekly, 999):
        order = PP.season_order(season, p["order"])
        if before_order is not None and order >= before_order:
            continue
        out.append(dict(p, order=order, game=f"{order}-{p['team']}"))
    return out


def load_season_pbp(season: int):
    """One season of NFL play-by-play, trimmed to the columns the log needs (pandas), or raises."""
    import nflreadpy as nfl
    df = nfl.load_pbp([season])
    return df.select([c for c in PP.PBP_COLUMNS if c in df.columns]).to_pandas()


def load_season_snaps(season: int):
    """One season of NFL snap counts (pandas), or raises."""
    import nflreadpy as nfl
    return nfl.load_snap_counts([season]).to_pandas()


def chart_slots_by_game(chart_df, team_games: Dict[Tuple[int, str], str]) -> Dict[Tuple[int, str], Dict[str, Tuple]]:
    """Depth-chart snapshots + {(order, team): game date 'YYYY-MM-DD'} -> {(order, team): {slot: (player id, name)}}.

    For each team-game the newest snapshot dated STRICTLY BEFORE the game date is used (the chart as it stood the day
    before), read with football_depth_from_chart so QB / RB1-2 / WR1-3 / TE1 follow chart order. A team-game with no
    earlier snapshot is simply absent."""
    if chart_df is None or len(chart_df) == 0 or not team_games:
        return {}
    df = chart_df[chart_df["team"].notna()].copy()
    df["_day"] = df["dt"].astype(str).str[:10]
    df = df[~df["pos_grp"].astype(str).str.startswith(("Base", "Special"))]
    by_team = {t: g for t, g in df.groupby("team")}
    cache: Dict[Tuple[str, str], Dict] = {}
    out: Dict[Tuple[int, str], Dict[str, Tuple]] = {}
    for (order, team), day in team_games.items():
        tdf = by_team.get(team)
        if tdf is None or not day:
            continue
        earlier = tdf[tdf["_day"] < str(day)[:10]]
        if len(earlier) == 0:
            continue
        snap = earlier["_day"].max()
        if (team, snap) not in cache:
            slots = football_depth_from_chart(tdf[tdf["_day"] == snap].to_dict("records"))
            cache[(team, snap)] = {s: (lst[0].get("pid"), lst[0].get("name")) for s, lst in slots.items() if lst and lst[0].get("pid")}
        if cache[(team, snap)]:
            out[(order, team)] = cache[(team, snap)]
    return out


def load_season_charts(season: int):
    """One season of NFL depth-chart snapshots (pandas), or raises."""
    import nflreadpy as nfl
    return nfl.load_depth_charts([season]).to_pandas()


def _nfl_team_info(notes: List[str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """({abbr: full team name}, {abbr: ESPN logo url}) from nflreadpy's team table; empty on failure."""
    def go():
        import nflreadpy as nfl
        t = nfl.load_teams().to_pandas()
        return ({r["team_abbr"]: r["team_name"] for r in t.to_dict("records")},
                {r["team_abbr"]: r.get("team_logo_espn") for r in t.to_dict("records") if r.get("team_logo_espn")})
    return _safe(go, ({}, {}), notes, "team names and logos")


def load_nfl_log(date_str: str) -> Dict:
    """Everything the NFL game log needs for the week `date_str` falls in — league-wide, so it is loaded once per
    date and shared by every game on the slate. TWO seasons are stacked (the previous full season plus this season's
    weeks before the game), because a defense's last ten games usually straddle the season boundary.

    {"allowed": {defense: [game entries, each with per-period stat lines attached]}, "meta": {(order, defense,
    offense): date / venue / result / primetime / roof / role}, "all_names": {abbr: team name}, "logos", "headshots":
    {player id: url}, "absences": {(order, team): [defenders who sat]}, "regulars": {team: [defenders]}, "notes",
    "season", "week", "has_pbp"}. Every source fails soft: a missing one empties its feature and adds a note."""
    import sports
    notes: List[str] = []
    eng = sports.get("NFL").engine
    season = eng._infer_season(date_str)
    empty = {"allowed": {}, "allowed_chart": {}, "meta": {}, "all_names": {}, "logos": {}, "headshots": {}, "absences": {}, "regulars": {},
             "notes": notes, "season": season, "week": None, "has_pbp": False}
    if season is None:
        notes.append("Couldn't work out the season for this date.")
        return empty
    sched = {season: _safe(lambda: eng.get_schedule(season), [], notes, "this season's schedule")}
    week = eng._resolve_week(sched[season], date_str) or 1
    before = PP.season_order(season, week)
    seasons = (season - 1, season)
    sched[season - 1] = _safe(lambda: eng.get_schedule(season - 1), [], notes, "last season's schedule")
    pgames: List[Dict] = []
    headshots: Dict[str, str] = {}
    for s_ in seasons:
        weekly = _safe(lambda s_=s_: eng.load_season_weekly_stats(s_), None, notes, f"{s_} weekly stats")
        pgames += stack_nfl_pgames(weekly, s_, before)
        if weekly is not None and len(weekly) and "headshot_url" in weekly.columns:
            for r in weekly[["player_id", "headshot_url"]].dropna().drop_duplicates("player_id").to_dict("records"):
                headshots[r["player_id"]] = r["headshot_url"]
    meta_games = [g for s_ in seasons for g in football_meta_games("NFL", sched[s_], s_)]
    allowed = PM.allowed_by_slot(pgames, "NFL")
    if not pgames:
        notes.append("No player-game data on file yet for the game log.")
    pbp_frames = [f for f in (_safe(lambda s_=s_: load_season_pbp(s_), None, notes, f"{s_} play-by-play") for s_ in seasons)
                  if f is not None and len(f)]
    lookup: Dict = {}
    if pbp_frames:
        import pandas as pd
        lookup = _safe(lambda: PP.period_lines(pd.concat(pbp_frames, ignore_index=True), before), {}, notes, "play-by-play lines")
    has_pbp = bool(lookup) and PM.attach_periods(allowed, lookup) > 0
    if not has_pbp:
        notes.append("Play-by-play wasn't available, so longest plays, shares and half / quarter splits are turned off "
                     "(full-game totals still work).")
    snap_frames = [f for f in (_safe(lambda s_=s_: load_season_snaps(s_), None, notes, f"{s_} snap counts") for s_ in seasons)
                   if f is not None and len(f)]
    absences, regulars = {}, {}
    if snap_frames:
        import pandas as pd
        absences, regulars = _safe(lambda: PP.defense_absences(pd.concat(snap_frames, ignore_index=True)), ({}, {}), notes,
                                   "snap counts")
    allowed_chart = {}
    if has_pbp:
        chart_frames = [f for f in (_safe(lambda s_=s_: load_season_charts(s_), None, notes, f"{s_} depth charts") for s_ in seasons)
                        if f is not None and len(f)]
        if chart_frames:
            import pandas as pd
            team_games = {}
            for (order, dfn, off), m in PM.build_game_meta(meta_games).items():
                if m.get("date"):
                    team_games[(order, dfn)] = team_games[(order, off)] = m["date"]
            charts = _safe(lambda: chart_slots_by_game(pd.concat(chart_frames, ignore_index=True), team_games), {}, notes,
                           "depth charts")
            if charts:
                allowed_chart = PM.chart_allowed(allowed, charts, lookup)
    names, logos = _nfl_team_info(notes)
    teams = set(allowed) | {g["offense"] for lst in allowed.values() for g in lst}
    return {"allowed": allowed, "allowed_chart": allowed_chart, "meta": PM.build_game_meta(meta_games), "all_names": {t: names.get(t, t) for t in teams},
            "logos": logos, "headshots": headshots, "absences": absences, "regulars": regulars, "notes": notes,
            "season": season, "week": week, "has_pbp": has_pbp}


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
        info: Dict[str, Dict] = {}
        for c in comps[0].get("competitors") or []:
            try:
                side = c.get("homeAway") or f"x{len(sides)}"
                sides[side] = int((c.get("team") or {}).get("id"))
            except (TypeError, ValueError):
                continue
            info[side] = {"name": (c.get("team") or {}).get("displayName"), "score": c.get("score")}
        ids = list(sides.values())
        if len(sides) != 2 or ids[0] == ids[1]:
            continue
        h_key, a_key = ("home" if "home" in sides else list(sides)[0]), ("away" if "away" in sides else list(sides)[1])
        out.append({"gid": ev["id"], "date": ev.get("date") or d, "home": sides.get("home", ids[0]),
                    "away": sides.get("away", ids[1]), "type": stype,
                    "home_name": info[h_key]["name"], "away_name": info[a_key]["name"],
                    "home_score": info[h_key]["score"], "away_score": info[a_key]["score"]})
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
                 h2h_games: List[Dict], names: Optional[Dict[Any, str]] = None, notes: Optional[List[str]] = None,
                 meta_games: Optional[List[Dict]] = None) -> Dict:
    """Everything the page renders for one game. `home`/`away` are the keys used in `pgames` (names or
    ids); `names` maps a key to its display name (every team in the sample, not just these two — the game
    log's defense dropdown shows them all). `meta_games` is the schedule rows behind the game log's date /
    venue / result columns (see PM.build_game_meta)."""
    names = names or {}
    allowed = PM.allowed_by_slot(pgames, sport)
    bundle = {"sport": sport, "metric": PM.METRIC_LABEL[PM.FAMILY_BY_SPORT[sport]],
              "home": home, "away": away, "names": {home: names.get(home, home), away: names.get(away, away)},
              "notes": list(notes or []),
              "allowed": allowed, "meta": PM.build_game_meta(meta_games),
              "all_names": {t: names.get(t, t) for t in allowed}}
    bundle["all_names"].update(names)                    # opponents who only appear as an offense still get their name in the log
    bundle["all_names"].update(bundle["names"])
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
    meta_sched = sched if not use_previous_season else _safe(lambda: eng.get_schedule(stats_season), [], notes, "last season's schedule")
    return build_bundle(sport_key, home, away, pgames, depth, _football_h2h_games(sport_key, eng, season), notes=notes,
                        meta_games=football_meta_games(sport_key, meta_sched))


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


def football_meta_games(sport_key: str, sched: Iterable[Dict], season: Optional[int] = None) -> List[Dict]:
    """A football schedule -> the rows PM.build_game_meta wants. `order` is the week (matching the rank tables'
    player-game lines) — or, with `season`, the composite season * 100 + week the stacked NFL log uses. NFL and CFBD
    name their date and score fields differently; the NFL rows also carry kickoff time, spread, total and roof for the
    log's Primetime / Indoors / Favorite filters."""
    out = []
    for g in sched or []:
        if g.get("week") is None:
            continue
        order = int(g["week"]) if season is None else PP.season_order(season, int(g["week"]))
        if sport_key == "NFL":
            out.append({"order": order, "date": g.get("game_date"), "home": g.get("home_team"), "away": g.get("away_team"),
                        "home_score": g.get("home_score"), "away_score": g.get("away_score"), "time": g.get("game_time"),
                        "spread": g.get("spread_line"), "total": g.get("total_line"), "roof": g.get("roof")})
        else:
            out.append({"order": order, "date": g.get("start_date"), "home": g.get("home_team"), "away": g.get("away_team"),
                        "home_score": g.get("home_points"), "away_score": g.get("away_points")})
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
        team_names = {home_id: home_name, away_id: away_name}
        for tid in (home_id, away_id):
            for g in _safe(lambda: eng.get_team_recent_game_ids(tid, date_str, 10), [], notes, "recent games"):
                if g.get("season_type") == 1:
                    continue
                at_home = g.get("home_away") != "away"
                opp_id, opp_name = _int_or(g.get("opp_id")), g.get("opp_name")
                mine, theirs = g.get("score"), g.get("opp_score")
                games.setdefault(g["gameId"], {
                    "date": g.get("date") or "",
                    "home": tid if at_home else opp_id, "away": opp_id if at_home else tid,
                    "home_name": team_names[tid] if at_home else opp_name, "away_name": opp_name if at_home else team_names[tid],
                    "home_score": mine if at_home else theirs, "away_score": theirs if at_home else mine})
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
    names = {home_id: home_name, away_id: away_name}
    for g in games.values():
        for side in ("home", "away"):
            if g.get(side) is not None and g.get(f"{side}_name"):
                names.setdefault(g[side], g[f"{side}_name"])
    meta_games = [{"order": g.get("date"), "date": g.get("date"), "home": g.get("home"), "away": g.get("away"),
                   "home_score": g.get("home_score"), "away_score": g.get("away_score")} for g in games.values()]
    bundle = build_bundle(sport_key, home_id, away_id, pgames, depth, [], names=names, notes=notes, meta_games=meta_games)
    meetings = PM.h2h_meetings(h2h, home_name, away_name)
    summ = PM.h2h_summary(meetings, home_name, away_name)
    bundle["h2h"] = {"meetings": meetings, "summary": summ, "sentence": PM.h2h_sentence(summ, home_name, away_name)}
    return bundle


def _int_or(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return x


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
