"""
wnba_projections.py — turns wnba_engine's slate rows into priced probabilities.

Matches projections.py's OUTPUT CONTRACT exactly (build_projection_index / default_board_from_index
/ DEFAULT_SIMS), which is what lets Edge Board consume MLB and WNBA through the same code path via
sports.active().projections — see sports.py and views/3_..._Edge_Board.py. The genuinely
sport-agnostic pieces of that contract (prob_over, prob_for_side, normalize_name, format_et,
prob_to_decimal, prob_to_american — pure math on probabilities/integer count arrays, nothing
baseball-specific) are imported straight from projections.py rather than re-implemented here.

METHOD (deliberately simple — a v1, documented as such): each of a player's last N games
(config_wnba.RECENT_GAMES_N) for Points/Rebounds/Assists/Threes Made is treated as one draw from
their true talent distribution. The projection is an empirical bootstrap: resample those games
with replacement `sims` times and use the resulting distribution directly, the same "simulate many
outcomes, read probabilities off the distribution" idea as MLB's Monte Carlo, adapted to basketball
count stats using the player's own recent games as the empirical distribution instead of a
per-plate-appearance model. Known limitation: with a short game log (early season, new team), the
bootstrap can't see tail outcomes the player hasn't produced yet in that sample — it will
undersample volatility for players with fewer than ~5-6 games logged. Opponent defensive strength
and pace are NOT yet incorporated (v1 scope); a natural next step once this is live.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from projections import (  # genuinely sport-agnostic — reused, not duplicated
    prob_over, prob_for_side, normalize_name, format_et,
    prob_to_decimal, prob_to_american,
)

DEFAULT_SIMS = 10000

# Odds-API-market-key -> (row column, display name, default line for the model-only board).
_MARKET_SPEC = {
    "player_points":   ("PTS",  "Points",      12.5),
    "player_rebounds": ("REB",  "Rebounds",    5.5),
    "player_assists":  ("AST",  "Assists",     3.5),
    "player_threes":   ("FG3M", "Threes Made", 1.5),
}
_STAT_KEY = {"PTS": "pts", "REB": "reb", "AST": "ast", "FG3M": "fg3m"}


def _dist(samples: np.ndarray) -> np.ndarray:
    """Normalized histogram: index i -> P(outcome == i). Same shape/semantics as
    projections._dist, so odds_api.compute_edges works identically for either sport."""
    counts = np.bincount(samples.astype(np.int64)).astype(np.float64)
    total = counts.sum()
    return counts / total if total > 0 else counts


def _signal(player, team, game, market, side, line, prob, projection, **extra) -> Dict:
    prob = float(round(prob, 4))
    sig = {
        "Player": player, "Team": team, "Game": game, "Market": market,
        "Side": side, "Line": line, "ModelProb": prob, "Projection": round(float(projection), 2),
        "FairDec": prob_to_decimal(prob), "FairAm": prob_to_american(prob),
        "BookOdds": None, "Implied": None, "EdgePct": None,
    }
    sig.update(extra)
    return sig


def simulate_player_stat(recent_values: List[float], sims: int, rng: np.random.Generator) -> np.ndarray:
    """Bootstrap `sims` draws (with replacement) from a player's recent-game values for one stat.
    Values are rounded to the nearest non-negative integer (counting stats can't be fractional or
    negative). Returns an empty array if there's no game log to sample from."""
    if not recent_values:
        return np.array([], dtype=np.int64)
    draws = rng.choice(np.asarray(recent_values, dtype=np.float64), size=sims, replace=True)
    return np.clip(np.round(draws), 0, None).astype(np.int64)


def build_projection_index(rows: List[Dict], meta: List[Dict],
                           sims: int = DEFAULT_SIMS, seed: Optional[int] = None) -> Dict:
    """Return {(normalized_name, odds_market_key): {dist, mean, ctx}} for the slate — identical
    shape to projections.build_projection_index, so downstream code (Edge Board, odds_api.compute_
    edges) doesn't need to know which sport it's looking at."""
    rng = np.random.default_rng(seed)
    index: Dict = {}

    for r in rows:
        log = r.get("_game_log") or []
        if not log:
            continue
        nm = normalize_name(r["Player"])
        ctx = {"player": r["Player"], "team": r["Team"], "game": r["GameLabel"],
              "opp": r.get("Opp"), "lineup": "Active", "game_date": r.get("_game_date")}
        for mkey, (col, _disp, _line) in _MARKET_SPEC.items():
            values = [g[_STAT_KEY[col]] for g in log]
            sim = simulate_player_stat(values, sims, rng)
            if sim.size == 0:
                continue
            index[(nm, mkey)] = {"dist": _dist(sim), "mean": float(sim.mean()), "ctx": ctx}

    return index


def default_board_from_index(index: Dict) -> List[Dict]:
    """Model-only board (favored side at default lines) from the index — identical shape/logic
    to projections.default_board_from_index (no MLB-style Yes/No special case needed here; every
    WNBA market in _MARKET_SPEC is a plain Over/Under)."""
    out: List[Dict] = []
    for (nm, mkey), entry in index.items():
        _col, disp, line = _MARKET_SPEC.get(mkey, (mkey, mkey, 0.5))
        dist, ctx = entry["dist"], entry["ctx"]
        over = prob_over(dist, line)
        side, prob = ("Over", over) if over >= 0.5 else ("Under", 1 - over)
        out.append(_signal(ctx["player"], ctx["team"], ctx["game"], disp, side, line, prob,
                           entry["mean"], Opp=ctx.get("opp"), Lineup=ctx.get("lineup"),
                           GameTime=ctx.get("game_date")))
    return out
