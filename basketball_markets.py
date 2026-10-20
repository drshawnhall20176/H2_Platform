"""
basketball_markets.py — the markets beyond Points / Rebounds / Assists / Threes Made, shared by NBA, WNBA and NCAAMB.

Added in build 246 at the owner's request: the NBA board had no combo props (Points+Rebounds+Assists, Points+Rebounds,
Points+Assists, Rebounds+Assists), steals, blocks, blocks+steals, turnovers or threes attempted — and combos are among the
most-played NBA props.

DESIGN
  * Every market is just a stat key on a game-log line. The box score parsers (nba/wnba/ncaamb_engine.get_game_boxscore)
    now record stl, blk, tov and fg3a next to pts, reb, ast, fg3m, and `add_derived` adds the combo keys (pr, pa, ra, pra,
    bs) to the same dict. So a player's bootstrap draws a WHOLE game's points+rebounds+assists, which keeps the correlation
    between the parts instead of pretending they are independent.
  * Logs from before this build (or a feed that omitted a stat) simply lack the key: `game_value` returns None and
    `values_for` drops that game, so a missing stat never reads as a false zero.
  * Threes Attempted has NO sportsbook market on The Odds API (checked against its published market list), so it is
    MODEL-ONLY: it appears on the boards at a placeholder line, never requests odds, and is left out of the default
    selections. Everything else maps to a real Odds API market key.

Each league's projections module adds these to its own `_MARKET_SPEC` with league-scale placeholder lines.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# Box-score stats recorded per game (pts/reb/ast/fg3m/min were always there).
BASE_KEYS = ("pts", "reb", "ast", "fg3m", "stl", "blk", "tov", "fg3a")

# Combo stat key -> the base stats it sums.
COMBOS: Dict[str, Tuple[str, ...]] = {
    "pr": ("pts", "reb"),
    "pa": ("pts", "ast"),
    "ra": ("reb", "ast"),
    "pra": ("pts", "reb", "ast"),
    "bs": ("blk", "stl"),
}

# (Odds API market key, row column, display name, stat key). Order = the order they list on the boards.
EXTRA_MARKETS: List[Tuple[str, str, str, str]] = [
    ("player_points_rebounds_assists", "PRA", "Pts+Reb+Ast", "pra"),
    ("player_points_rebounds", "PR", "Pts+Reb", "pr"),
    ("player_points_assists", "PA", "Pts+Ast", "pa"),
    ("player_rebounds_assists", "RA", "Reb+Ast", "ra"),
    ("player_steals", "STL", "Steals", "stl"),
    ("player_blocks", "BLK", "Blocks", "blk"),
    ("player_blocks_steals", "BLKSTL", "Blocks+Steals", "bs"),
    ("player_turnovers", "TOV", "Turnovers", "tov"),
    ("player_threes_attempted", "FG3A", "Threes Attempted", "fg3a"),
]

# Not a real Odds API market: there is no threes-attempted prop to request. Never sent to the odds fetch.
MODEL_ONLY = {"player_threes_attempted"}

EXTRA_STAT_KEY: Dict[str, str] = {col: stat for _k, col, _d, stat in EXTRA_MARKETS}
EXTRA_DISPLAY_TO_STAT: Dict[str, str] = {disp: stat for _k, _c, disp, stat in EXTRA_MARKETS}
EXTRA_DISPLAY_TO_ODDS_KEY: Dict[str, str] = {disp: k for k, _c, disp, _s in EXTRA_MARKETS if k not in MODEL_ONLY}
EXTRA_ODDS_KEYS: List[str] = [k for k, _c, _d, _s in EXTRA_MARKETS if k not in MODEL_ONLY]
EXTRA_DISPLAY: List[str] = [disp for _k, _c, disp, _s in EXTRA_MARKETS]
COMBO_DISPLAY = {"Pts+Reb+Ast", "Pts+Reb", "Pts+Ast", "Reb+Ast", "Blocks+Steals"}
MODEL_ONLY_DISPLAY = {disp for k, _c, disp, _s in EXTRA_MARKETS if k in MODEL_ONLY}


def game_value(game: Dict, stat_key: str) -> Optional[float]:
    """One game's value for a stat key (base or combo). None when the game line lacks a needed stat — an old cached log,
    or a feed that did not report it — so callers can leave the game out rather than count a missing stat as zero."""
    try:
        if stat_key in COMBOS:
            total = 0.0
            for part in COMBOS[stat_key]:
                v = game.get(part)
                if v is None:
                    return None
                total += float(v)
            return total
        v = game.get(stat_key)
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def values_for(log: Iterable[Dict], stat_key: str) -> List[float]:
    """The stat's value in each game of a log (most-recent-first order kept), skipping games that lack it."""
    out: List[float] = []
    for g in log or []:
        v = game_value(g, stat_key)
        if v is not None:
            out.append(v)
    return out


def average_for(log: Sequence[Dict], stat_key: str) -> Optional[float]:
    """Mean of values_for, or None when no game has the stat."""
    vals = values_for(log, stat_key)
    return sum(vals) / len(vals) if vals else None


def add_derived(line: Dict[str, float]) -> Dict[str, float]:
    """Add every combo whose parts are all present (in place; returns the dict). Called by the box score parsers."""
    for key in COMBOS:
        v = game_value(line, key)
        if v is not None:
            line[key] = v
    return line


def parse_attempts(raw) -> Optional[float]:
    """Attempts from a "made-attempted" box-score string ("3-7" -> 7.0). None when the string has no attempts part."""
    if raw is None:
        return None
    s = str(raw).strip()
    if "-" not in s or s.startswith("-"):
        return None
    try:
        return float(s.split("-", 1)[1])
    except (TypeError, ValueError):
        return None


def player_stats_from_box(names: Sequence[str], stats: Sequence) -> Dict[str, float]:
    """steals / blocks / turnovers / threes attempted from one athlete's box-score stat list, for the stats present.
    (pts/reb/ast/fg3m/min are still parsed by each engine as before.)"""
    from basketball_engine import parse_stat_value
    by_name = {n: v for n, v in zip(names, stats)}
    out: Dict[str, float] = {}
    for src, key in (("STL", "stl"), ("BLK", "blk"), ("TO", "tov")):
        if src in by_name:
            out[key] = parse_stat_value(by_name[src])
    if "3PT" in by_name:
        a = parse_attempts(by_name["3PT"])
        if a is not None:
            out["fg3a"] = a
    return out


def row_columns(game_log: Sequence[Dict]) -> Dict[str, Optional[float]]:
    """Per-game averages for the new row columns (STL, BLK, TOV, FG3A, PRA, PR, PA, RA, BLKSTL), rounded like PTS/REB/AST.
    None for a stat no game in the log has."""
    out: Dict[str, Optional[float]] = {}
    for _k, col, _d, stat in EXTRA_MARKETS:
        avg = average_for(game_log, stat)
        out[col] = round(avg, 1) if avg is not None else None
    return out


def extend_team_totals(stats_by_name: Dict[str, str], totals: Dict[str, float], find_team_stat) -> Dict[str, float]:
    """Add team-level steals, blocks, turnovers and threes attempted to a game_team_totals entry, plus the combos built from
    the team's pts/reb/ast. Reported only when the feed named the stat (a 0 from a missing name would read as 'allows none')."""
    def has(*names: str) -> bool:
        return any(n in stats_by_name or any(k.startswith(n) for k in stats_by_name) for n in names)
    if has("steals"):
        totals["stl"] = find_team_stat(stats_by_name, "steals")
    if has("blocks"):
        totals["blk"] = find_team_stat(stats_by_name, "blocks")
    if has("totalTurnovers", "turnovers"):
        totals["tov"] = find_team_stat(stats_by_name, "totalTurnovers", "turnovers")
    if has("threePointFieldGoalsMade-threePointFieldGoalsAttempted", "threePointFieldGoalsAttempted"):
        totals["fg3a"] = find_team_stat(stats_by_name, "threePointFieldGoalsMade-threePointFieldGoalsAttempted",
                                        "threePointFieldGoalsAttempted", side="right")
    return add_derived(totals)


# --- team-level aggregation (what a defense allows / a team scores), used by the Hot Hand board and Matchup Lab ---------
_CORE_TEAM_KEYS = ("pts", "reb", "ast", "fg3m", "poss")
TEAM_TOTAL_KEYS = _CORE_TEAM_KEYS + ("stl", "blk", "tov", "fg3a") + tuple(COMBOS)


def empty_team_totals() -> Dict[str, List[float]]:
    """The accumulator the allowed/scored stat functions fill, one list per tracked team stat."""
    return {k: [] for k in TEAM_TOTAL_KEYS}


def accumulate_team_totals(totals: Dict[str, List[float]], game_team_totals: Dict[str, float]) -> None:
    """Append one game's team totals. The original five stats keep their old behaviour (a missing one counts as 0.0); the
    newer ones (steals, blocks, turnovers, threes attempted, combos) are added only when the feed reported them, so a feed
    that omits one yields 'no data' (0.0 average -> a neutral matchup factor), not a defence that 'allows nothing'."""
    for k in totals:
        if k in _CORE_TEAM_KEYS:
            totals[k].append(game_team_totals.get(k, 0.0))
        elif k in game_team_totals:
            totals[k].append(game_team_totals[k])


# --- league-scale placeholder lines (used only for the model-only board before a real book line is fetched) -------------
DEFAULT_LINES = {
    "NBA":    {"PRA": 35.5, "PR": 29.5, "PA": 27.5, "RA": 12.5, "STL": 1.5, "BLK": 1.5, "BLKSTL": 2.5, "TOV": 2.5, "FG3A": 6.5},
    "WNBA":   {"PRA": 21.5, "PR": 17.5, "PA": 15.5, "RA": 8.5, "STL": 1.5, "BLK": 0.5, "BLKSTL": 2.5, "TOV": 2.5, "FG3A": 3.5},
    "NCAAMB": {"PRA": 21.5, "PR": 17.5, "PA": 15.5, "RA": 8.5, "STL": 1.5, "BLK": 0.5, "BLKSTL": 2.5, "TOV": 2.5, "FG3A": 3.5},
}


def extend_spec(spec: Dict, stat_key: Dict, league: str) -> None:
    """Add EXTRA_MARKETS to a projections module's _MARKET_SPEC / _STAT_KEY (in place), at `league`'s placeholder lines."""
    lines = DEFAULT_LINES[league]
    for okey, col, disp, stat in EXTRA_MARKETS:
        spec[okey] = (col, disp, lines[col])
        stat_key[col] = stat


CORE_STATS = frozenset({"pts", "reb", "ast", "fg3m"})


def window_average(log: Sequence[Dict], stat_key: str, n: int) -> Optional[float]:
    """Average of the newest n games, only when the log has n games and every one of them has the stat (else None — an honest
    'not enough games yet', never padded or counted as zero)."""
    window = list(log or [])[:n]
    vals = values_for(window, stat_key)
    return (sum(vals) / n) if len(window) == n and len(vals) == n else None
