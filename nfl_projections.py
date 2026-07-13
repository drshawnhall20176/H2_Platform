"""
nfl_projections.py — NFL projection model using usage-first approach with heavy shrinkage.

The key insight: football is volume × efficiency, not one-on-one matchups.
- Model USAGE (targets, carries, pass attempts) with heavy regression toward league baseline.
- Model EFFICIENCY (yards per target, etc.) separately with shrinkage.
- Combine for outcome distribution.

With only 17 games, shrinkage is critical. We use empirical Bayes (Stein-like) to pull
individual estimates toward the prior, weighted by sample size uncertainty.

Markets:
  - QB Passing Yards (attempts × yards per attempt)
  - RB Rushing Yards (carries × yards per carry)
  - WR Receptions (targets × catch rate)
  - WR Receiving Yards (receptions × yards per reception)
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm, lognorm

import nfl_engine as engine

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS & PRIORS
# ============================================================================

# League baseline priors (2023-2024 data, tuned from real NFL stats)
LEAGUE_PRIORS = {
    "qb_pass_yards": {
        "attempts_per_game": 38.0,
        "yards_per_attempt": 7.2,
    },
    "rb_rush_yards": {
        "carries_per_game": 15.0,
        "yards_per_carry": 4.2,
    },
    "wr_receptions": {
        "targets_per_game": 8.0,
        "catch_rate": 0.68,
    },
    "wr_rec_yards": {
        "targets_per_game": 8.0,
        "yards_per_target": 9.5,
    },
}

# Uncertainty in priors (standard deviation) — games played is the shrinkage scale
PRIOR_STD = {
    "qb_pass_yards": {"attempts": 8.0, "efficiency": 0.8},
    "rb_rush_yards": {"usage": 4.0, "efficiency": 0.5},
    "wr_receptions": {"usage": 3.0, "efficiency": 0.15},
    "wr_rec_yards": {"usage": 3.0, "efficiency": 1.2},
}


# ============================================================================
# NAME NORMALIZATION
# ============================================================================
def normalize_name(name: str) -> str:
    """Normalize player name to match rosters.
    
    Handles: "Josh Allen" → "josh allen", removes punctuation, etc.
    """
    if not name:
        return ""
    # Lowercase, remove leading/trailing space
    s = name.strip().lower()
    # Remove punctuation except apostrophes
    s = re.sub(r"[^\w\s']", "", s)
    # Collapse multiple spaces
    s = re.sub(r"\s+", " ", s)
    return s


def _shrink_mean(observed: float, prior: float, n_samples: int, prior_std: float) -> float:
    """Stein-like shrinkage: pull observed toward prior based on sample size.
    
    The idea: with few samples, the observed mean is noisy. We shrink it toward
    the prior (league baseline) with weight proportional to uncertainty.
    
    Formula: shrunk = observed * w + prior * (1 - w)
    where w = n_samples / (n_samples + (prior_std)^2)
    
    Args:
        observed: Observed mean from player's recent games.
        prior: League baseline prior.
        n_samples: Number of games observed.
        prior_std: Prior standard deviation (uncertainty in the prior).
    
    Returns:
        Shrunken estimate.
    """
    if n_samples <= 0:
        return prior
    # Weight toward observed increases with sample size
    weight = n_samples / (n_samples + prior_std ** 2)
    return observed * weight + prior * (1.0 - weight)


def _build_usage_efficiency(player_id: str, season: int, market: str, rosters: Dict) -> Tuple[float, float, int]:
    """Extract usage and efficiency for a player in a market.
    
    Returns (usage_mean, efficiency_mean, n_games) where:
      - usage_mean: expected targets/carries/attempts per game
      - efficiency_mean: expected yards per target/carry/attempt
      - n_games: games observed
    
    Args:
        player_id: nflverse player_id.
        season: NFL season.
        market: One of {qb_pass_yards, rb_rush_yards, wr_receptions, wr_rec_yards}.
        rosters: Roster dict to identify position.
    
    Returns:
        (usage, efficiency, games) or (0, 0, 0) if insufficient data.
    """
    games = engine.player_game_log(player_id, season, rosters)
    if not games or len(games) < 3:  # Require at least 3 games
        logger.debug(f"Player {player_id} has < 3 games for {market}")
        return 0.0, 0.0, 0
    
    df = pd.DataFrame(games)
    n_games = len(df)
    
    # Extract usage and efficiency by market
    if market == "qb_pass_yards":
        usage = df["pass_attempts"].mean()  # attempts per game
        ypa = df[df["pass_attempts"] > 0]["pass_yards"].sum() / max(df["pass_attempts"].sum(), 1)
        efficiency = ypa
    elif market == "rb_rush_yards":
        usage = df["carries"].mean()  # carries per game
        ypc = df[df["carries"] > 0]["rush_yards"].sum() / max(df["carries"].sum(), 1)
        efficiency = ypc
    elif market == "wr_receptions":
        usage = df["targets"].mean()  # targets per game
        catch_rate = df[df["targets"] > 0]["receptions"].sum() / max(df["targets"].sum(), 1)
        efficiency = catch_rate
    elif market == "wr_rec_yards":
        usage = df["targets"].mean()  # targets per game
        ypt = df[df["targets"] > 0]["rec_yards"].sum() / max(df["targets"].sum(), 1)
        efficiency = ypt
    else:
        return 0.0, 0.0, 0
    
    return float(usage), float(efficiency), int(n_games)


def _fit_lognormal_distribution(mean: float, std: float) -> Tuple[float, float]:
    """Fit a lognormal distribution to a mean and std.
    
    For counts (targets, carries) and yards, lognormal fits better than normal.
    Given E[X] and Var[X], solve for mu and sigma of ln(X).
    
    Args:
        mean: Expected value.
        std: Standard deviation.
    
    Returns:
        (mu, sigma) for scipy.stats.lognorm(s=sigma, scale=exp(mu)).
    """
    if mean <= 0 or std < 0:
        return 0.0, 0.1
    cv = std / mean if mean > 0 else 0.1  # coefficient of variation
    sigma = np.sqrt(np.log(cv ** 2 + 1))
    mu = np.log(mean) - 0.5 * sigma ** 2
    return float(mu), float(sigma)


# ============================================================================
# PROJECTION INDEX
# ============================================================================
def proj_index(date_str: str, season: int = 2024, week: Optional[int] = None) -> Dict:
    """Build projection index for a slate date.
    
    Returns dict keyed by (normalized_player_name, market):
      {(name, market): {
         dist: scipy.stats distribution,
         mean: float,
         std: float,
         usage: float,
         efficiency: float,
         ctx: {player_id, player_name, team, position, game_id, opponent, ...}
      }, ...}
    
    This index is consumed by odds_api.compute_edges() to compute edge metrics.
    
    Args:
        date_str: Date in YYYY-MM-DD format.
        season: NFL season.
        week: Optional week override. If None, inferred from date and schedule.
    
    Returns:
        Projection index. Empty dict if no games or data issues.
    """
    try:
        rosters = engine.load_rosters(season)
        schedule = engine.load_schedule(season)
        
        if not rosters or not schedule:
            logger.error("Failed to load rosters or schedule")
            return {}
        
        # Get games on this date
        games_today = engine.games_on_date(schedule, date_str)
        if not games_today:
            logger.warning(f"No games on {date_str}")
            return {}
        
        index = {}
        
        for game in games_today:
            game_id = game.get("game_id")
            week_num = game.get("week")
            home_team = game.get("home_team")
            away_team = game.get("away_team")
            
            # Process both teams' rosters
            for team in [home_team, away_team]:
                opponent = away_team if team == home_team else home_team
                
                # Find QBs, RBs, WRs on this team
                team_players = [p for pid, p in rosters.items() if p.get("team") == team]
                
                for player in team_players:
                    pid = player.get("player_id")
                    pname = player.get("name", "")
                    pos = player.get("position", "")
                    
                    if not pid or not pname:
                        continue
                    
                    markets_for_pos = []
                    if pos == "QB":
                        markets_for_pos = ["qb_pass_yards"]
                    elif pos == "RB":
                        markets_for_pos = ["rb_rush_yards"]
                    elif pos == "WR" or pos == "TE":
                        markets_for_pos = ["wr_receptions", "wr_rec_yards"]
                    
                    for market in markets_for_pos:
                        # Build projection
                        usage, efficiency, n_games = _build_usage_efficiency(
                            pid, season, market, rosters
                        )
                        
                        if n_games < 3:
                            # Not enough data — skip
                            continue
                        
                        # Shrink toward priors
                        prior = LEAGUE_PRIORS.get(market, {})
                        prior_std_usage = PRIOR_STD.get(market, {}).get("usage", 3.0)
                        prior_std_eff = PRIOR_STD.get(market, {}).get("efficiency", 0.5)
                        
                        if market == "qb_pass_yards":
                            prior_usage = prior.get("attempts_per_game", 38.0)
                            prior_eff = prior.get("yards_per_attempt", 7.2)
                        elif market == "rb_rush_yards":
                            prior_usage = prior.get("carries_per_game", 15.0)
                            prior_eff = prior.get("yards_per_carry", 4.2)
                        elif market == "wr_receptions":
                            prior_usage = prior.get("targets_per_game", 8.0)
                            prior_eff = prior.get("catch_rate", 0.68)
                        else:  # wr_rec_yards
                            prior_usage = prior.get("targets_per_game", 8.0)
                            prior_eff = prior.get("yards_per_target", 9.5)
                        
                        # Shrink usage and efficiency
                        shrunk_usage = _shrink_mean(usage, prior_usage, n_games, prior_std_usage)
                        shrunk_eff = _shrink_mean(efficiency, prior_eff, n_games, prior_std_eff)
                        
                        # Compute final outcome mean and std
                        if market == "wr_receptions":
                            # Receptions = targets × catch_rate
                            outcome_mean = shrunk_usage * shrunk_eff
                            # Std is binomial-like
                            outcome_std = np.sqrt(shrunk_usage * shrunk_eff * (1 - shrunk_eff))
                        else:
                            # Yards = usage × efficiency
                            outcome_mean = shrunk_usage * shrunk_eff
                            # Std is empirical; assume 15% of mean
                            outcome_std = max(outcome_mean * 0.15, 2.0)
                        
                        # Fit lognormal distribution
                        mu, sigma = _fit_lognormal_distribution(outcome_mean, outcome_std)
                        dist = lognorm(s=sigma, scale=np.exp(mu))
                        
                        # Build context
                        ctx = {
                            "player_id": pid,
                            "player": pname,
                            "team": team,
                            "position": pos,
                            "opponent": opponent,
                            "game_id": game_id,
                            "is_home": team == home_team,
                            "usage_mean": round(usage, 2),
                            "efficiency_mean": round(efficiency, 4),
                            "usage_games": n_games,
                        }
                        
                        key = (normalize_name(pname), market)
                        index[key] = {
                            "dist": dist,
                            "mean": round(outcome_mean, 2),
                            "std": round(outcome_std, 2),
                            "usage": round(shrunk_usage, 2),
                            "efficiency": round(shrunk_eff, 4),
                            "ctx": ctx,
                        }
        
        logger.info(f"Built projection index for {date_str}: {len(index)} entries")
        return index
    
    except Exception as e:
        logger.error(f"Error building projection index: {e}")
        return {}


# ============================================================================
# PROBABILITY COMPUTATION (for Edge Board)
# ============================================================================
def prob_for_side(dist, point: float, side: str) -> float:
    """Compute P(outcome > line) or P(outcome < line) for a distribution.
    
    Args:
        dist: scipy.stats distribution (e.g., lognorm).
        point: The line (e.g., 250.5 for passing yards).
        side: "Over" or "Under".
    
    Returns:
        Probability. Clipped to [0.01, 0.99].
    """
    try:
        if side.lower().startswith("o"):
            # P(X > point)
            prob = dist.sf(point)
        else:
            # P(X < point)
            prob = dist.cdf(point)
        return float(np.clip(prob, 0.01, 0.99))
    except Exception as e:
        logger.warning(f"Error computing prob_for_side: {e}")
        return 0.5


# ============================================================================
# UTILITIES FOR TESTING
# ============================================================================
def sample_distribution(dist, n: int = 10000) -> np.ndarray:
    """Draw samples from a distribution for testing/visualization.
    
    Args:
        dist: scipy.stats distribution.
        n: Number of samples.
    
    Returns:
        Array of samples.
    """
    return dist.rvs(size=n)


def distribution_summary(dist) -> Dict:
    """Summarize a distribution's key statistics.
    
    Args:
        dist: scipy.stats distribution.
    
    Returns:
        Dict with mean, std, percentiles, etc.
    """
    samples = sample_distribution(dist, 10000)
    return {
        "mean": float(np.mean(samples)),
        "std": float(np.std(samples)),
        "p10": float(np.percentile(samples, 10)),
        "p25": float(np.percentile(samples, 25)),
        "median": float(np.median(samples)),
        "p75": float(np.percentile(samples, 75)),
        "p90": float(np.percentile(samples, 90)),
    }
