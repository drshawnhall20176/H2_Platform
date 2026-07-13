"""
config_nfl.py — NFL sport configuration.

Single source of truth for:
  - Supported markets and their Odds API keys
  - Display name to Odds API market mapping (for betlog/closing-line capture)
  - Team info

Import this in Streamlit pages to avoid hard-coding sport/market details.
"""

# Sport identifier for The Odds API
SPORT = "americanfootball_nfl"

# Supported markets (Odds API keys)
SUPPORTED_MARKETS = [
    "quarterback_passing_yards",
    "player_rushing_yards",
    "player_receptions",
    "player_receiving_yards",
]

# Display name (as shown in UI/Bet Log) → Odds API market key
# Used by clv_capture.py to match bets to closing lines
MARKET_MAP = {
    "QB Passing Yards": "quarterback_passing_yards",
    "RB Rushing Yards": "player_rushing_yards",
    "WR Receptions": "player_receptions",
    "WR Receiving Yards": "player_receiving_yards",
}

# Reverse map (Odds API key → Display name)
MARKET_MAP_REVERSE = {v: k for k, v in MARKET_MAP.items()}

# NFL teams
NFL_TEAMS = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
]

# Position groups for filtering
POSITIONS = {
    "QB": "Quarterback",
    "RB": "Running Back",
    "WR": "Wide Receiver",
    "TE": "Tight End",
    "DEF": "Defense",
}

# Market to position mapping
MARKET_POSITIONS = {
    "quarterback_passing_yards": ["QB"],
    "player_rushing_yards": ["RB"],
    "player_receptions": ["WR", "TE", "RB"],
    "player_receiving_yards": ["WR", "TE", "RB"],
}

# Credibility filters for Edge Board
EV_CEILING = 10.0  # Don't show edges above this (often fake/sparse data)
ODDS_CAP = 50.0  # Only show odds within this decimal range
MIN_EV = 2.0  # Minimum EV% to display (noise floor)
MAX_EV_DISPLAY = 20.0  # Cap display EV% for visualization

# Kelly sizing defaults
KELLY_FRACTION = 0.25  # 1/4 Kelly (standard discipline)
BANKROLL_CAP_PCT = 0.05  # Max 5% of bankroll per bet

# Odds adjustment (early season, small sample adjustments)
# Users can override these per market
ADJUSTMENT_FACTORS = {
    "quarterback_passing_yards": 1.0,
    "player_rushing_yards": 1.0,
    "player_receptions": 1.0,
    "player_receiving_yards": 1.0,
}

# Data quality thresholds
MIN_GAMES_FOR_PROJECTION = 3  # Require at least this many games
MIN_SEASON_GAMES = 5  # For season averages, require at least this many games

# Season/date constants
CURRENT_SEASON = 2024
NFL_SEASON_START = "2024-09-05"
NFL_SEASON_END = "2025-02-06"
PRESEASON_MARKETS_DISABLED = True  # Don't build projections before season starts
