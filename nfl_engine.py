"""
nfl_engine.py — NFL data layer using nflreadpy.

LIBRARY CHOICE, CONFIRMED DURING SCOPING, NOT THE ORIGINAL DRAFT'S ASSUMPTION: this replaces an
earlier draft built on nfl_data_py. Checked directly against the source during this build:
nfl_data_py's own README now reads "nfl_data_py has been deprecated in favour of nflreadpy. All
future development will occur in nflreadpy and users are encouraged to switch immediately. No
further nfl_data_py maintenance or updates are planned." — the repo was archived Sep 25, 2025, last
release Sep 2024. Building new production code on an abandoned library was the wrong call, so this
is a full rewrite on nflreadpy (nflverse's own actively-maintained successor, v0.1.5 as of this
build, confirmed installable via `pip install nflreadpy` — a standard PyPI package, not a fragile
GitHub-only install). Honest caveat carried forward: nflreadpy's own lifecycle badge reads
"experimental," not stable 1.0 — the same "unofficial API, not guaranteed stable" posture this
platform already carries for ESPN's endpoints applies here too.

EVERY COLUMN NAME BELOW WAS CONFIRMED AGAINST REAL, LIVE DATA during this build (not just
documentation) — `nflreadpy` was actually installed and queried in the build sandbox:
load_schedules([2025]) returned 285 real rows (game_id like "2025_01_DAL_PHI", away_rest/home_rest
already computed, real scores); load_player_stats([2025], summary_level="week") returned 19,421
real rows with a real, verified Patrick Mahomes line (Week 1: 24/39, 258 yards, 1 TD); load_rosters
and load_injuries both confirmed live with real 2025 data. Column names throughout this module are
the CONFIRMED real ones, not guessed.

CRITICAL PERFORMANCE FIX vs. the original draft, not a style choice: the old code called
nfl.import_play_data([season]) — the FULL season's raw play-by-play (tens of thousands of rows) —
INSIDE player_game_log(), meaning it would reload the entire season's play-by-play from scratch
for EVERY SINGLE PLAYER on a slate. For a ~50-player week, that's ~50 redundant full-season loads.
nflreadpy's load_player_stats() returns PRE-AGGREGATED per-player-per-week rows directly — no
manual play-by-play aggregation needed at all — and this module loads it ONCE per build_slate()
call, then filters the single in-memory DataFrame per player, the same "load once per slate, not
once per player" discipline every other sport's engine in this platform already follows.

WEEKLY, NOT DAILY, SLATE STRUCTURE — the one genuine structural difference from every other sport
here: NFL games happen as a whole WEEK's slate (Thu-Mon), not on individual calendar dates the way
MLB/WNBA/NBA/NCAAMB do. Rather than redesign the shared layer's date-picker UI (every page in this
platform calls sport.engine.build_slate(date_str) and expects one calendar date in, one slate out),
build_slate(date_str) here RESOLVES the date to whichever NFL week it falls in (or the next
upcoming week, or the season's last week if the date is past it — see _resolve_week's own
docstring) and returns that WHOLE WEEK's games. Same interface the rest of the platform already
expects; NFL just looks like "a daily sport where a run of consecutive dates happens to share the
same slate," which is honestly what it is.

POSITION-AWARE, NOT ONE-SIZE-FITS-ALL, LIKE BASKETBALL'S CORE 4: a QB doesn't have receptions, a
WR doesn't have pass yards. player_row() only attaches the markets relevant to a player's own
position — see _MARKETS_FOR_POSITION below — rather than blindly projecting all four for everyone
the way basketball's Points/Rebounds/Assists/Threes apply to every rotation player regardless of
position.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

try:
    import nflreadpy as nfl
except ImportError:
    raise ImportError("Install nflreadpy: pip install nflreadpy")

import config_nfl as CFG

logger = logging.getLogger(__name__)


def _diag(msg: str) -> None:
    """Stage-by-stage visibility for the ONE failure mode logging.exception can't catch: every
    fetch succeeding while the parsing code quietly extracts nothing, because the real shape
    doesn't match what was coded against. print() (not the `logging` module) — Streamlit Cloud's
    log viewer reliably captures stdout, the same finding that shaped every other sport's engine
    in this platform."""
    print(f"[NFL] {msg}", flush=True)


# Per-position market applicability. A market only gets projected for positions that genuinely
# generate that stat — a RB with zero pass attempts doesn't get a "Pass Yards" row just because
# the market exists on the platform. QB's rushing yards deliberately excluded from v1: mobile QBs
# do carry meaningful rush volume, but folding a QB's rushing into the same "Rush Yards" market as
# RBs would mix two very different opportunity profiles under one line/market — worth a real,
# separate design decision later, not a quick addition here.
_MARKETS_FOR_POSITION: Dict[str, List[str]] = {
    "QB": ["player_pass_yds"],
    "RB": ["player_rush_yds", "player_receptions", "player_reception_yds"],
    "WR": ["player_receptions", "player_reception_yds"],
    "TE": ["player_receptions", "player_reception_yds"],
    "FB": ["player_rush_yds", "player_receptions", "player_reception_yds"],
}

# odds_market_key -> (weekly-stats column, display name, rotation-floor stat column, floor value).
# The rotation floor is checked against the SAME player's own average of the floor column — see
# player_row — not a fixed global threshold, since "enough volume to matter" means something
# different for a QB's attempts than a WR's targets.
_MARKET_SPEC: Dict[str, Tuple[str, str, str, float]] = {
    "player_pass_yds":     ("passing_yards",   "Pass Yards",     "attempts",  CFG.MIN_QB_ATTEMPTS),
    "player_rush_yds":     ("rushing_yards",   "Rush Yards",     "_touches",  CFG.MIN_RB_TOUCHES),
    "player_receptions":   ("receptions",      "Receptions",     "targets",   CFG.MIN_WR_TARGETS),
    "player_reception_yds": ("receiving_yards", "Receiving Yards", "targets", CFG.MIN_WR_TARGETS),
}


# --------------------------------------------------------------------------- schedule / weeks
def get_schedule(season: int) -> List[Dict[str, Any]]:
    """Full-season schedule: [{game_id, week, game_date, home_team, away_team, home_score,
    away_score, home_rest, away_rest}, ...]. away_rest/home_rest come DIRECTLY from nflreadpy's
    schedule data — confirmed live — so unlike every basketball engine in this platform, NFL
    doesn't need to compute rest days itself by scanning recent games; the schedule already has it."""
    try:
        df = nfl.load_schedules([season]).to_pandas()
    except Exception:
        logger.exception("NFL load_schedules failed for season %s", season)
        return []
    if df.empty:
        _diag(f"get_schedule({season}): load_schedules returned 0 rows")
        return []

    out = []
    for _, r in df.iterrows():
        try:
            out.append({
                "game_id": r["game_id"], "week": int(r["week"]), "game_date": r.get("gameday"),
                "home_team": r["home_team"], "away_team": r["away_team"],
                "home_score": r.get("home_score"), "away_score": r.get("away_score"),
                "home_rest": r.get("home_rest"), "away_rest": r.get("away_rest"),
            })
        except (KeyError, ValueError):
            continue
    _diag(f"get_schedule({season}): {len(out)} game(s)")
    return out


def _resolve_week(schedule: List[Dict], date_str: str) -> Optional[int]:
    """Which NFL week a calendar date belongs to, for build_slate(date_str)'s weekly-slate
    resolution (see module docstring for why this exists at all).

    Rule, in order:
      1. date_str falls within [that week's earliest game, that week's latest game + 1 day] for
         some week -> that week (the +1 day buffer covers a date picked the morning after a
         Monday-night game, still "that week" for grading/browsing purposes).
      2. Otherwise, the NEXT week whose earliest game is still in the future -> that week (picking
         a bye-week Tuesday should show the upcoming week's slate, not nothing).
      3. Otherwise (date is past the whole loaded season) -> the LAST week in the schedule, so an
         off-season date still resolves to something browsable (the most recently completed week)
         rather than silently returning empty.
      4. Empty schedule -> None."""
    if not schedule:
        return None
    by_week: Dict[int, List[str]] = {}
    for g in schedule:
        d = g.get("game_date")
        if d:
            by_week.setdefault(g["week"], []).append(d)

    ranges = {wk: (min(ds), max(ds)) for wk, ds in by_week.items()}
    for wk, (lo, hi) in sorted(ranges.items()):
        hi_buffered = (datetime.strptime(hi, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        if lo <= date_str <= hi_buffered:
            return wk
    upcoming = sorted(wk for wk, (lo, _hi) in ranges.items() if lo > date_str)
    if upcoming:
        return upcoming[0]
    return max(ranges) if ranges else None


def games_for_week(schedule: List[Dict], week: int) -> List[Dict]:
    return [g for g in schedule if g["week"] == week]


# --------------------------------------------------------------------------- rosters
def get_team_roster(team_abbr: str, season: int) -> List[Dict[str, Any]]:
    """A team's roster for a season: [{id, name, position}, ...]. id is the GSIS id (e.g.
    "00-0033873") — confirmed live to be the SAME id format load_player_stats uses, so the two
    join cleanly with no separate id-mapping step. Empty gsis_id rows (confirmed real: some
    recently-signed/practice-squad players have none yet) are skipped, not guessed at."""
    try:
        df = nfl.load_rosters([season]).to_pandas()
    except Exception:
        logger.exception("NFL load_rosters failed for season %s", season)
        return []
    team_df = df[df["team"] == team_abbr]
    if team_df.empty:
        _diag(f"get_team_roster({team_abbr}, {season}): 0 players found for this team")
        return []
    out = []
    for _, r in team_df.iterrows():
        gid = r.get("gsis_id")
        if not gid:
            continue
        out.append({"id": gid, "name": r.get("full_name"), "position": r.get("position")})
    return out


# --------------------------------------------------------------------------- weekly stats
def load_season_weekly_stats(season: int) -> pd.DataFrame:
    """The season's full weekly player-stats table, loaded ONCE — see module docstring for why
    this matters (the performance bug this replaces). Callers (build_slate) load this a single
    time per build and pass the DataFrame around; nothing in this module re-fetches per player."""
    try:
        df = nfl.load_player_stats([season], summary_level="week").to_pandas()
    except Exception:
        logger.exception("NFL load_player_stats failed for season %s", season)
        return pd.DataFrame()
    if df.empty:
        _diag(f"load_season_weekly_stats({season}): load_player_stats returned 0 rows")
    # NOT df.get("carries", 0).fillna(0): DataFrame.get() returns the literal default (an int,
    # not a Series) when the column is entirely absent from the response, and .fillna() on an int
    # crashes — a real pandas gotcha, not a hypothetical one (caught by this module's own test
    # suite). Ensuring the columns exist first, defaulting to 0, keeps this correct whether or not
    # a real nflreadpy response happens to include them.
    for col in ("carries", "targets"):
        if col not in df.columns:
            df[col] = 0
    df["_touches"] = df["carries"].fillna(0) + df["targets"].fillna(0)
    return df


def player_recent_games(weekly: pd.DataFrame, player_id: str, before_week: int,
                        n: int = CFG.RECENT_GAMES_N) -> List[Dict]:
    """This player's last n games STRICTLY BEFORE before_week this season, most recent first —
    same "strictly before" discipline as every other sport's engine (see basketball_engine.py's
    get_team_recent_game_ids docstring for the full lookahead-bias reasoning; identical concern
    applies here: grading a past week must not leak that week's own result into its own sample).

    HONEST V1 LIMITATION, not silently papered over: before_week=1 has no games before it AT ALL
    within the season, so week 1 of any season returns an empty slate for every player, even once
    real data exists — there's no within-season "recent form" yet at the very start. Deliberately
    NOT reaching into the PRIOR season to fill the gap: roster churn (trades, free agency, the
    draft) matters far more year-over-year in the NFL than within one season, so a player's LAST
    season's numbers on a DIFFERENT team could actively mislead rather than help. Worth a real,
    separate design decision later (e.g. a explicit "early-season, low-confidence" mode), not a
    rushed fix folded in here."""
    if weekly.empty:
        return []
    rows = weekly[(weekly["player_id"] == player_id) & (weekly["week"] < before_week)]
    rows = rows.sort_values("week", ascending=False).head(n)
    return rows.to_dict("records")


# --------------------------------------------------------------------------- injuries
def get_team_injuries(team_abbr: str, season: int, week: int) -> List[Dict[str, Any]]:
    """Team injury report for one team/week: [{"player", "status", "position", "return_date",
    "comment"}, ...] — same shape basketball_engine.get_team_injuries returns, so any shared
    display code works unchanged. return_date is always None here, honestly — NFL's real injury
    report data (confirmed live) has no return-date field the way ESPN's basketball injury
    endpoint does; reporting one anyway would mean inventing it. comment combines the primary and
    secondary reported injury (e.g. "Knee" or "Knee, Ankle"), the closest real analog to ESPN's
    shortComment field this data actually has."""
    try:
        df = nfl.load_injuries([season]).to_pandas()
    except Exception:
        logger.exception("NFL load_injuries failed for season %s", season)
        return []
    rows = df[(df["team"] == team_abbr) & (df["week"] == week)]
    if rows.empty:
        return []
    out = []
    for _, r in rows.iterrows():
        parts = [p for p in (r.get("report_primary_injury"), r.get("report_secondary_injury")) if p and str(p) != "nan"]
        out.append({
            "player": r.get("full_name"), "status": r.get("report_status"),
            "position": r.get("position"), "return_date": None,
            "comment": ", ".join(parts) if parts else None,
        })
    return out


# --------------------------------------------------------------------------- pure logic (no network)
def player_row(player: Dict, team: str, opp: str, game_label: str, game_date: Optional[str],
              recent_games: List[Dict], opp_id: Optional[str] = None,
              team_id: Optional[str] = None) -> Optional[Dict]:
    """Flat row for one player on the slate. None if the player doesn't clear ANY position-
    relevant rotation floor — filters no-real-role noise off the slate, same purpose as every
    other sport's min-minutes/min-avg-minutes filter, just keyed to opportunity stats instead of
    playing time (see config_nfl.py's own reasoning for why)."""
    position = (player.get("position") or "").upper()
    markets = _MARKETS_FOR_POSITION.get(position)
    if not markets or not recent_games:
        return None

    n = len(recent_games)

    def avg(col: str) -> float:
        return sum(float(g.get(col) or 0) for g in recent_games) / n

    cleared_markets = []
    for mkey in markets:
        _stat_col, _disp, floor_col, floor_val = _MARKET_SPEC[mkey]
        if avg(floor_col) >= floor_val:
            cleared_markets.append(mkey)
    if not cleared_markets:
        return None   # e.g. a WR who's barely played recently — real player, no real recent role

    row = {
        "Player": player.get("name"), "Team": team, "GameLabel": game_label, "Opp": opp,
        "Position": position,
        "PassYds": round(avg("passing_yards"), 1), "RushYds": round(avg("rushing_yards"), 1),
        "Receptions": round(avg("receptions"), 1), "RecYds": round(avg("receiving_yards"), 1),
        # private fields consumed by nfl_projections.py
        "_pid": player.get("id"), "_recent_games": recent_games, "_game_date": game_date,
        "_opp_id": opp_id, "_team_id": team_id, "_markets": cleared_markets,
    }
    return row


# --------------------------------------------------------------------------- orchestration
def _infer_season(date_str: str) -> Optional[int]:
    """Which NFL season a calendar date belongs to — NOT nflreadpy's get_current_season(), which
    (confirmed live during scoping) reports the LAST COMPLETED season during the off-season, not
    "the season currently being browsed." A January 2027 date should resolve to the 2026 season's
    playoff weeks, not have that silently coerced to whatever get_current_season() returns that
    day. Shared by build_slate and get_player_results — both need the identical rule, and having
    it in two places risked them quietly drifting apart."""
    try:
        season = int(date_str[:4])
        # NFL's season "year" runs Sep-Feb; a January/February date belongs to the PRIOR year's
        # season (e.g. "2027-01-16" is a 2026-season playoff game).
        if int(date_str[5:7]) <= 2:
            season -= 1
        return season
    except (ValueError, TypeError):
        return None


def get_player_results(date_str: str) -> Dict[str, Dict[str, float]]:
    """Actual per-player results for date_str's resolved WEEK, keyed by player id — same contract
    as mlb_engine.get_player_results/every basketball engine's own version, so retro.py's grading
    logic (grade_play/grade_slate) works identically for NFL without modification.

    RETURNS A WHOLE WEEK'S RESULTS, DELIBERATELY, NOT JUST GAMES ON THE LITERAL CALENDAR DATE —
    matches build_slate's own weekly resolution exactly, and has to: grading compares this
    function's output against a slate build_slate(date_str) already produced for a WHOLE WEEK, so
    returning only the literal date's games would silently show "no result" for most of that
    week's players whose games happened to fall on a different day within it (Thursday/Monday
    games in particular, which are common and NOT edge cases).

    Empty for weeks that haven't been played yet — the weekly-stats fetch simply won't have those
    rows (nflverse hasn't published them), which reads to grading code as "no results yet", the
    same honest degradation every other sport's get_player_results already has for future dates."""
    season = _infer_season(date_str)
    if season is None:
        _diag(f"get_player_results({date_str}): could not infer season from date_str")
        return {}
    schedule = get_schedule(season)
    week = _resolve_week(schedule, date_str)
    if week is None:
        return {}
    weekly = load_season_weekly_stats(season)
    if weekly.empty:
        return {}

    rows = weekly[weekly["week"] == week]
    out: Dict[str, Dict[str, float]] = {}
    for _, r in rows.iterrows():
        pid = r.get("player_id")
        if not pid:
            continue
        out[pid] = {
            "passing_yards": float(r.get("passing_yards") or 0),
            "rushing_yards": float(r.get("rushing_yards") or 0),
            "receptions": float(r.get("receptions") or 0),
            "receiving_yards": float(r.get("receiving_yards") or 0),
        }
    _diag(f"get_player_results({date_str}): season {season} week {week}, {len(out)} player result(s)")
    return out


def build_slate(date_str: str, season: Optional[int] = None) -> Tuple[List[Dict], List[Dict]]:
    """Fetch and assemble the full NFL slate for whichever week date_str resolves into (see
    _resolve_week's own docstring for the resolution rule).

    Returns (rows, meta), matching every other sport's engine contract — Edge Board/Best Bets/
    Hot Hand Engine/Matchup Lab don't need to know NFL's slate is weekly under the hood.

    season defaults to _infer_season(date_str) — see that function's own docstring for why this
    is NOT nflreadpy's get_current_season()."""
    if season is None:
        season = _infer_season(date_str)
        if season is None:
            _diag(f"build_slate({date_str}): could not infer season from date_str, aborting")
            return [], []

    schedule = get_schedule(season)
    week = _resolve_week(schedule, date_str)
    if week is None:
        _diag(f"build_slate({date_str}): no schedule data for season {season} -> nothing to build")
        return [], []

    games = games_for_week(schedule, week)
    if not games:
        _diag(f"build_slate({date_str}): resolved to week {week} but 0 games found")
        return [], []

    weekly = load_season_weekly_stats(season)
    if weekly.empty:
        _diag(f"build_slate({date_str}): resolved to week {week}, but weekly stats fetch failed/empty")
        return [], []

    meta: List[Dict] = []
    rows: List[Dict] = []
    roster_cache: Dict[str, List[Dict]] = {}
    for g in games:
        label = f"{g['away_team']} @ {g['home_team']}"
        meta.append({"label": label, "away_name": g["away_team"], "home_name": g["home_team"],
                    "game_date": g.get("game_date"), "week": week,
                    "home_id": g["home_team"], "away_id": g["away_team"],
                    "home_rest": g.get("home_rest"), "away_rest": g.get("away_rest")})
        for team, opp in ((g["home_team"], g["away_team"]), (g["away_team"], g["home_team"])):
            if team not in roster_cache:
                roster_cache[team] = get_team_roster(team, season)
            for player in roster_cache[team]:
                recent = player_recent_games(weekly, player["id"], week)
                row = player_row(player, team, opp, label, g.get("game_date"), recent,
                                 opp_id=opp, team_id=team)
                if row is not None:
                    rows.append(row)

    _diag(f"build_slate({date_str}): season {season} week {week}, {len(games)} game(s) -> "
         f"{len(rows)} player(s) cleared a rotation floor")
    return rows, meta


# --------------------------------------------------------------------------- Matchup Lab support
def team_abbrs_from_meta(meta: List[Dict]) -> Dict[str, str]:
    """{team_id: abbreviation} for every team on the slate — trivial for NFL, since the team_id
    build_slate already uses IS the ESPN/nflverse abbreviation ("KC", "LAC", ...), unlike ESPN
    basketball's numeric team ids needing a real lookup. Kept as its own function anyway, not
    inlined at call sites — same interface every sport-dispatching page expects
    (basketball_engine.py's own team_abbrs_from_meta plays the identical role there)."""
    out: Dict[str, str] = {}
    for g in meta:
        out[g["home_id"]] = g["home_id"]
        out[g["away_id"]] = g["away_id"]
    return out


def get_player_season_games(player_id: str, before_date: str, max_games: int = 25) -> List[Dict]:
    """This player's full game log for the season so far (any opponent), most recent first —
    the baseline Matchup Lab compares a head-to-head sample against. max_games=25 comfortably
    covers a full 17-game regular season plus a playoff run, without needing basketball's
    days_back windowing (NFL has no equivalent "how far back to scan" concern — weeks are
    globally sequential within a season, see _resolve_week's own docstring)."""
    season = _infer_season(before_date)
    if season is None:
        return []
    schedule = get_schedule(season)
    week = _resolve_week(schedule, before_date)
    if week is None:
        return []
    weekly = load_season_weekly_stats(season)
    return player_recent_games(weekly, player_id, before_week=week, n=max_games)


def get_player_history_vs_opponent(player_id: str, opp_abbr: str, before_date: str,
                                   max_games: int = 10) -> List[Dict]:
    """This player's stats in every game THIS SEASON their team has played against one specific
    opponent, most recent first. Genuinely likely to come back EMPTY more often than not — most
    NFL opponents meet exactly once a season (division rivals meet twice, home and away), unlike
    a sport with a balanced round-robin schedule. That's the honest, common case here, not the
    exception — reported honestly rather than padded with a guess or reaching into a prior
    season (a team's roster the year before tells you less than nothing reliable about how a
    reshuffled roster plays this year)."""
    season = _infer_season(before_date)
    if season is None:
        return []
    schedule = get_schedule(season)
    week = _resolve_week(schedule, before_date)
    if week is None:
        return []
    weekly = load_season_weekly_stats(season)
    if weekly.empty:
        return []
    rows = weekly[(weekly["player_id"] == player_id) & (weekly["week"] < week) &
                 (weekly["opponent_team"] == opp_abbr)]
    rows = rows.sort_values("week", ascending=False).head(max_games)
    return rows.to_dict("records")


def get_team_allowed_stats(team_abbr: str, before_date: str, n: Optional[int] = None) -> Dict[str, float]:
    """Average PassYds/RushYds/Receptions/RecYds ALLOWED by this team's defense — n=None for the
    whole season so far, n=int for just their last n games. Computed by grouping the league-wide
    weekly-stats table (already loaded once per Matchup Lab pageview, not re-fetched per call) by
    week, summing every opposing player's stat line for games against this team (equivalent to
    that game's TEAM total against them), then averaging across games. The recent/season split
    lets Matchup Lab show whether a defense has been trending looser or tighter lately than their
    own season norm — same signal WNBA/NBA/NCAAMB's Matchup Lab already surfaces, built on NFL's
    own real data shape rather than a basketball-style pace/possession normalization (NFL doesn't
    have an equivalent "possessions" concept the way basketball's per-100 adjustment needs)."""
    season = _infer_season(before_date)
    if season is None:
        return {}
    schedule = get_schedule(season)
    week = _resolve_week(schedule, before_date)
    if week is None:
        return {}
    weekly = load_season_weekly_stats(season)
    if weekly.empty:
        return {}
    rows = weekly[(weekly["opponent_team"] == team_abbr) & (weekly["week"] < week)]
    if rows.empty:
        return {}
    stat_cols = ["passing_yards", "rushing_yards", "receptions", "receiving_yards"]
    by_week = rows.groupby("week")[stat_cols].sum()
    if n is not None:
        by_week = by_week.sort_index(ascending=False).head(n)
    if by_week.empty:
        return {}
    avg = by_week.mean()
    return {col: float(avg[col]) for col in stat_cols}


def _get_team_stat_sum_allowed(team_abbr: str, before_date: str, stat_cols: List[str],
                               n: Optional[int] = None) -> float:
    """Shared helper: average of stat_cols SUMMED per game then averaged across games, allowed by
    this team's defense — the same grouped-by-game-then-averaged construction get_team_allowed_
    stats uses, generalized to an arbitrary set of columns so get_team_tds_allowed/get_team_
    passing_tds_allowed/get_team_rushing_tds_allowed don't each duplicate this logic separately.
    Private — not part of this module's public contract, just the shared implementation the three
    public *_allowed functions above call."""
    season = _infer_season(before_date)
    if season is None:
        return 0.0
    schedule = get_schedule(season)
    week = _resolve_week(schedule, before_date)
    if week is None:
        return 0.0
    weekly = load_season_weekly_stats(season)
    if weekly.empty:
        return 0.0
    rows = weekly[(weekly["opponent_team"] == team_abbr) & (weekly["week"] < week)].copy()
    if rows.empty:
        return 0.0
    # Same pandas gotcha fixed in load_season_weekly_stats's _touches computation: DataFrame.get()
    # returns the literal default (an int) when a column is entirely absent, not a Series of that
    # default, and .fillna() on an int crashes. Ensuring every needed column exists first.
    for col in stat_cols:
        if col not in rows.columns:
            rows[col] = 0
    rows["_sum"] = sum(rows[col].fillna(0) for col in stat_cols)
    by_week = rows.groupby("week")["_sum"].sum()
    if n is not None:
        by_week = by_week.sort_index(ascending=False).head(n)
    if by_week.empty:
        return 0.0
    return float(by_week.mean())


def get_team_tds_allowed(team_abbr: str, before_date: str, n: Optional[int] = None) -> float:
    """Average TOTAL touchdowns (rushing + receiving combined) ALLOWED by this team's defense per
    game — n=None for the whole season so far, n=int for just their last n games. Kept as its OWN
    function rather than folded into get_team_allowed_stats's return dict: touchdowns is a
    fundamentally different kind of stat from the four yardage markets there (a low, often
    zero-inflated count, not a continuous yardage total), and Matchup Lab's Touchdowns row needs a
    single number, not a dict of four unrelated stats a caller would have to reach into."""
    return _get_team_stat_sum_allowed(team_abbr, before_date, ["rushing_tds", "receiving_tds"], n)


def get_team_passing_tds_allowed(team_abbr: str, before_date: str, n: Optional[int] = None) -> float:
    """Average PASSING touchdowns ALLOWED by this team's PASS defense per game — the opponent
    context for QB Lab's/Matchup Lab's Passing TDs row, kept separate from get_team_tds_allowed
    (rushing + receiving) since a QB's passing TDs and a defense's pass-defense performance are a
    genuinely different signal than how many rushing/receiving TDs that same defense allows."""
    return _get_team_stat_sum_allowed(team_abbr, before_date, ["passing_tds"], n)


def get_team_rushing_tds_allowed(team_abbr: str, before_date: str, n: Optional[int] = None) -> float:
    """Average RUSHING touchdowns ALLOWED by this team's run defense per game — the opponent
    context for Matchup Lab's QB-specific Rushing TDs row. Kept separate from get_team_tds_
    allowed (which combines rushing + receiving) since a QB's rushing TDs specifically compares
    most honestly against rushing TDs allowed, not a number that's partly about receiving TDs
    allowed to totally different positions."""
    return _get_team_stat_sum_allowed(team_abbr, before_date, ["rushing_tds"], n)


def get_team_rest_info(team_abbr: str, before_date: str) -> Dict[str, Any]:
    """Rest context for a team heading into before_date: days since their last completed game,
    and whether they're on a short week (a real NFL concept, unlike basketball's back-to-back —
    no NFL team plays on consecutive days; a "short week" is a Thursday game after a Sunday one,
    ~4 days rest instead of the standard 7). Sourced directly from the schedule's own home_rest/
    away_rest fields (confirmed live during scoping — nflreadpy computes these already), not
    derived by scanning games the way every basketball engine in this platform has to."""
    empty = {"rest_days": None, "is_short_week": False, "last_game_date": None, "last_opp_name": None}
    season = _infer_season(before_date)
    if season is None:
        return empty
    schedule = get_schedule(season)
    week = _resolve_week(schedule, before_date)
    if week is None:
        return empty
    team_games = [g for g in schedule if g["week"] < week and
                 (g["home_team"] == team_abbr or g["away_team"] == team_abbr)]
    if not team_games:
        return empty
    last = max(team_games, key=lambda g: g["week"])
    is_home = last["home_team"] == team_abbr
    rest = last["home_rest"] if is_home else last["away_rest"]
    opp = last["away_team"] if is_home else last["home_team"]
    try:
        rest_val = int(rest) if rest is not None else None
    except (TypeError, ValueError):
        rest_val = None
    return {"rest_days": rest_val, "is_short_week": rest_val is not None and rest_val <= 4,
           "last_game_date": last.get("game_date"), "last_opp_name": opp}


# --------------------------------------------------------------------------- QB Lab support
def _get_league_average_allowed(before_date: str, stat_col: str) -> float:
    """Shared helper: league-wide average of stat_col allowed per team-game, SEASON-WIDE ONLY (no
    recent-N-games version, deliberately) — the baseline QB Lab's matchup-adjusted projections
    compare one opponent's own allowed rate against. A "recent league average" doesn't translate
    as cleanly as a single team's own recent-vs-season split does: different teams have played a
    different number of games by any given week, so "the league's last N games" is genuinely
    ambiguous in a way "this ONE team's last N games" isn't. Season-wide is also the more
    defensible choice for a matchup BASELINE specifically — a stable comparison point, not a
    moving target that would make the same opponent look tougher or easier depending only on when
    you happened to check, the same reasoning Pitching Lab's own matchup adjustment leans on a
    full-season opposing-lineup sample rather than that lineup's own last-10-games form. Private —
    get_league_average_pass_yards_allowed/get_league_average_rush_yards_allowed both call this
    rather than duplicating the same grouped-by-real-game construction separately."""
    season = _infer_season(before_date)
    if season is None:
        return 0.0
    schedule = get_schedule(season)
    week = _resolve_week(schedule, before_date)
    if week is None:
        return 0.0
    weekly = load_season_weekly_stats(season)
    if weekly.empty:
        return 0.0
    rows = weekly[weekly["week"] < week]
    if rows.empty:
        return 0.0
    # Group by (opponent_team, week) = one row per real game, from the DEFENSE's perspective —
    # same "sum per game, then average across games" construction as get_team_allowed_stats,
    # just not restricted to one team first.
    by_game = rows.groupby(["opponent_team", "week"])[stat_col].sum()
    if by_game.empty:
        return 0.0
    return float(by_game.mean())


def get_league_average_pass_yards_allowed(before_date: str) -> float:
    """League-wide average pass yards allowed per team-game — see _get_league_average_allowed's
    own docstring for the full reasoning (season-wide only, not a recent-N-games version)."""
    return _get_league_average_allowed(before_date, "passing_yards")


def get_league_average_rush_yards_allowed(before_date: str) -> float:
    """League-wide average rush yards allowed per team-game — the baseline QB Lab's matchup-
    adjusted Rush Yards projection compares one opponent's own allowed rate against, same role
    get_league_average_pass_yards_allowed plays for the Pass Yards projection."""
    return _get_league_average_allowed(before_date, "rushing_yards")
