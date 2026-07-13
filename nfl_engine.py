"""
nfl_engine.py — NFL data layer using nflverse/nfl_data_py.

Provides:
  - load_schedule() → game calendar
  - load_rosters() → player roster with IDs, positions, teams
  - player_game_log() → per-player weekly stats (targets, carries, completions, yards)
  - player_season_log() → season-to-date aggregates and rolling averages
  - parse_boxscore() → box-score grading (final stats per player for settled bets)

All functions are cacheable; use @st.cache_resource in Streamlit or a simple dict-level cache here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

try:
    import nfl_data_py as nfl
except ImportError:
    raise ImportError("Install nfl_data_py: pip install nfl-data-py")

logger = logging.getLogger(__name__)

# Season constants
CURRENT_SEASON = 2024
NFL_SEASON_LENGTH = 17  # 2021 onward


# ============================================================================
# SCHEDULE
# ============================================================================
def load_schedule(season: int = CURRENT_SEASON) -> List[Dict]:
    """Load NFL schedule for a season.
    
    Returns list of dicts:
      {game_id, season, week, game_date, kickoff_time, 
       home_team, away_team, home_score, away_score, ...}
    
    Args:
        season: NFL season year (e.g., 2024).
    
    Returns:
        List of game dicts. Empty if fetch fails.
    """
    try:
        df = nfl.import_schedules([season])
        if df is None or df.empty:
            logger.warning(f"No schedule found for season {season}")
            return []
        
        # Normalize column names (nflverse uses various conventions)
        df = df.rename(columns={
            "game_id": "game_id",
            "season": "season",
            "week": "week",
            "gameday": "game_date",
            "gametime": "kickoff_time",
            "home_team": "home_team",
            "away_team": "away_team",
            "home_score": "home_score",
            "away_score": "away_score",
        })
        
        # Filter to relevant columns
        cols = ["game_id", "season", "week", "game_date", "kickoff_time",
                "home_team", "away_team", "home_score", "away_score"]
        df = df[[c for c in cols if c in df.columns]]
        
        return df.to_dict("records")
    except Exception as e:
        logger.error(f"Error loading schedule: {e}")
        return []


def games_on_date(schedule: List[Dict], date_str: str) -> List[Dict]:
    """Filter schedule to games on a specific date (YYYY-MM-DD).
    
    Args:
        schedule: Output of load_schedule().
        date_str: Date string in YYYY-MM-DD format.
    
    Returns:
        List of games with matching date.
    """
    games = []
    for g in schedule:
        game_date = (g.get("game_date") or "")[:10]
        if game_date == date_str:
            games.append(g)
    return games


# ============================================================================
# ROSTERS
# ============================================================================
def load_rosters(season: int = CURRENT_SEASON) -> Dict[str, Dict]:
    """Load NFL rosters for a season.
    
    Returns dict keyed by player_id:
      {player_id: {name, team, position, nflverse_id, ...}, ...}
    
    Args:
        season: NFL season year.
    
    Returns:
        Dict of player records. Empty dict if fetch fails.
    """
    try:
        df = nfl.import_rosters([season])
        if df is None or df.empty:
            logger.warning(f"No rosters found for season {season}")
            return {}
        
        # nflverse uses 'player_id' as primary key; normalize columns
        df = df.rename(columns={
            "player_id": "player_id",
            "player_name": "name",
            "team": "team",
            "position": "position",
        })
        
        # Keep relevant columns
        cols = ["player_id", "name", "team", "position"]
        df = df[[c for c in cols if c in df.columns]]
        
        out = {}
        for _, row in df.iterrows():
            pid = row.get("player_id")
            if pid:
                out[pid] = row.to_dict()
        return out
    except Exception as e:
        logger.error(f"Error loading rosters: {e}")
        return {}


def find_player_by_name(rosters: Dict, name: str, team: Optional[str] = None) -> Optional[str]:
    """Find a player_id by name (and optionally team).
    
    Simple linear search; for production, build a name-index.
    
    Args:
        rosters: Output of load_rosters().
        name: Player name or normalized variant.
        team: Optional team code to narrow results.
    
    Returns:
        player_id if found, else None.
    """
    for pid, player in rosters.items():
        if (player.get("name") or "").lower() == name.lower():
            if team is None or (player.get("team") or "").upper() == team.upper():
                return pid
    return None


# ============================================================================
# PLAYER GAME LOGS (per-game weekly stats)
# ============================================================================
def player_game_log(player_id: str, season: int = CURRENT_SEASON, 
                    rosters: Optional[Dict] = None) -> List[Dict]:
    """Load per-game stats for a player in a season.
    
    Aggregates play-by-play data to return per-game:
      {week, game_id, team, opponent, targets, receptions, rec_yards, 
       carries, rush_yards, pass_attempts, completions, pass_yards, ...}
    
    Args:
        player_id: The nflverse player_id.
        season: NFL season year.
        rosters: Optional roster dict to look up position. If None, doesn't filter by position.
    
    Returns:
        List of per-game dicts. Empty if player not found or no plays.
    """
    try:
        # Import play-by-play for the season
        pbp = nfl.import_play_data([season])
        if pbp is None or pbp.empty:
            logger.warning(f"No play data for season {season}")
            return []
        
        # Filter plays involving this player
        # Check receiver_id, rusher_id, passer_id columns
        player_plays = pbp[
            (pbp.get("receiver_id") == player_id) |
            (pbp.get("rusher_id") == player_id) |
            (pbp.get("passer_id") == player_id)
        ].copy()
        
        if player_plays.empty:
            logger.debug(f"No plays found for player {player_id}")
            return []
        
        # Group by (game_id, week) and aggregate stats
        logs = []
        for (gid, wk), group in player_plays.groupby(["game_id", "week"]):
            stats = {
                "game_id": gid,
                "week": wk,
                "season": season,
                "player_id": player_id,
                # Receiving
                "targets": (group["receiver_id"] == player_id).sum(),
                "receptions": ((group["receiver_id"] == player_id) & (group["complete_pass"] == 1)).sum(),
                "rec_yards": group[group["receiver_id"] == player_id]["air_yards"].fillna(0).sum() +
                            group[group["receiver_id"] == player_id]["yards_after_catch"].fillna(0).sum(),
                "rec_td": ((group["receiver_id"] == player_id) & (group["pass_touchdown"] == 1)).sum(),
                # Rushing
                "carries": (group["rusher_id"] == player_id).sum(),
                "rush_yards": group[group["rusher_id"] == player_id]["rushing_yards"].fillna(0).sum(),
                "rush_td": ((group["rusher_id"] == player_id) & (group["rushing_touchdown"] == 1)).sum(),
                # Passing (QB only)
                "pass_attempts": (group["passer_id"] == player_id).sum(),
                "completions": ((group["passer_id"] == player_id) & (group["complete_pass"] == 1)).sum(),
                "pass_yards": group[group["passer_id"] == player_id]["passing_yards"].fillna(0).sum(),
                "pass_td": ((group["passer_id"] == player_id) & (group["pass_touchdown"] == 1)).sum(),
                "interceptions": ((group["passer_id"] == player_id) & (group["interception"] == 1)).sum(),
            }
            logs.append(stats)
        
        return sorted(logs, key=lambda x: x["week"])
    except Exception as e:
        logger.error(f"Error loading game log for {player_id}: {e}")
        return []


def player_season_log(player_id: str, season: int = CURRENT_SEASON) -> Dict:
    """Aggregate game log to season totals and rolling averages.
    
    Returns:
      {
        season_stats: {targets: X, receptions: Y, ...},
        last_n_avg: {last_4: {targets: ..., yards: ...}, last_8: {...}},
        current_week: int,  # most recent week with data
      }
    
    Args:
        player_id: The nflverse player_id.
        season: NFL season year.
    
    Returns:
        Dict with aggregates. Empty dict if player has no data.
    """
    games = player_game_log(player_id, season)
    if not games:
        return {}
    
    df = pd.DataFrame(games)
    
    # Season totals
    season_stats = {
        "targets": int(df["targets"].sum()),
        "receptions": int(df["receptions"].sum()),
        "rec_yards": float(df["rec_yards"].sum()),
        "carries": int(df["carries"].sum()),
        "rush_yards": float(df["rush_yards"].sum()),
        "pass_attempts": int(df["pass_attempts"].sum()),
        "completions": int(df["completions"].sum()),
        "pass_yards": float(df["pass_yards"].sum()),
        "games_played": len(df),
    }
    
    # Rolling averages
    last_n_avg = {}
    for n in [4, 8]:
        recent = df.tail(n)
        if len(recent) > 0:
            last_n_avg[f"last_{n}"] = {
                "targets_per_game": round(recent["targets"].mean(), 2),
                "rec_yards_per_game": round(recent["rec_yards"].mean(), 2),
                "receptions_per_game": round(recent["receptions"].mean(), 2),
                "carries_per_game": round(recent["carries"].mean(), 2),
                "rush_yards_per_game": round(recent["rush_yards"].mean(), 2),
                "pass_yards_per_game": round(recent["pass_yards"].mean(), 2),
                "games": len(recent),
            }
    
    return {
        "player_id": player_id,
        "season": season,
        "season_stats": season_stats,
        "last_n_avg": last_n_avg,
        "current_week": int(df["week"].max()) if not df.empty else 0,
    }


# ============================================================================
# BOX SCORE PARSING (for grading settled bets)
# ============================================================================
def parse_boxscore(game_id: str, season: int = CURRENT_SEASON) -> Dict[str, Dict]:
    """Parse a game's final box score (from play-by-play).
    
    Returns dict keyed by player_id:
      {player_id: {player_name, team, position, targets, receptions, 
                   rec_yards, carries, rush_yards, pass_yards, ...}, ...}
    
    This is used to grade settled bets against final stats.
    
    Args:
        game_id: The nflverse game_id (e.g., "2024_01_PHI_NYG").
        season: NFL season year.
    
    Returns:
        Dict of player stats. Empty if game not found.
    """
    try:
        pbp = nfl.import_play_data([season])
        if pbp is None or pbp.empty:
            return {}
        
        game_pbp = pbp[pbp["game_id"] == game_id]
        if game_pbp.empty:
            logger.warning(f"Game {game_id} not found")
            return {}
        
        rosters = load_rosters(season)
        
        # Collect all players involved in the game
        player_ids = set()
        for col in ["receiver_id", "rusher_id", "passer_id"]:
            player_ids.update(game_pbp[col].dropna().unique())
        
        out = {}
        for pid in player_ids:
            if pd.isna(pid) or not pid:
                continue
            
            logs = player_game_log(pid, season, rosters)
            # For this game
            game_log = [l for l in logs if l.get("game_id") == game_id]
            if game_log:
                stats = game_log[0].copy()
                if pid in rosters:
                    stats["player_name"] = rosters[pid].get("name")
                    stats["team"] = rosters[pid].get("team")
                    stats["position"] = rosters[pid].get("position")
                out[pid] = stats
        
        return out
    except Exception as e:
        logger.error(f"Error parsing boxscore for {game_id}: {e}")
        return {}


# ============================================================================
# UTILITIES
# ============================================================================
def team_opponent_on_date(schedule: List[Dict], team: str, date_str: str) -> Optional[str]:
    """Get opponent for a team on a given date.
    
    Args:
        schedule: Output of load_schedule().
        team: Team code (e.g., "KC").
        date_str: Date string (YYYY-MM-DD).
    
    Returns:
        Opponent team code, or None.
    """
    for g in schedule:
        if g.get("game_date", "")[:10] != date_str:
            continue
        if g.get("home_team") == team:
            return g.get("away_team")
        if g.get("away_team") == team:
            return g.get("home_team")
    return None


def is_home_game(schedule: List[Dict], team: str, game_id: str) -> Optional[bool]:
    """Check if a team is home in a game.
    
    Args:
        schedule: Output of load_schedule().
        team: Team code.
        game_id: Game ID.
    
    Returns:
        True if home, False if away, None if not found.
    """
    for g in schedule:
        if g.get("game_id") == game_id:
            if g.get("home_team") == team:
                return True
            if g.get("away_team") == team:
                return False
    return None
