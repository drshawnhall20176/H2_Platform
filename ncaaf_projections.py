"""
ncaaf_projections.py — turns ncaaf_engine's slate rows into priced probabilities.

Matches projections.py's OUTPUT CONTRACT (build_projection_index / default_board_from_index /
DEFAULT_SIMS) — the same contract every other sport's projections module follows, which is what
lets Edge Board consume MLB/WNBA/NBA/NCAAMB/NFL and now NCAAF through the same code path via
sports.active().projections.

A REAL METHODOLOGICAL DIFFERENCE FROM EVERY OTHER SPORT HERE, NOT HIDDEN: every other sport's
simulate_player_stat BOOTSTRAPS from a player's real recent-game log (resample with replacement,
build an empirical distribution). NCAAF genuinely has no per-game log to bootstrap from — see
ncaaf_engine.py's own docstring: CFBD's cached season stats are SEASON TOTALS, not per-game
rows. This module instead draws from a PARAMETRIC (Normal) distribution centered on the row's
own season-average per-game rate (already computed by ncaaf_engine.player_row), with a fixed,
explicitly UNVALIDATED coefficient of variation as its spread (_RATE_CV below) — there's no real
game-to-game variance to calibrate against yet. This is worth remembering when reading any NCAAF
probability this module produces: the MEAN is a real, CFBD-sourced season average; the SPREAD
around it is an assumption, not measured. Upgradable once ncaaf_engine.py adds real per-game
logs (via CFBD's get_game_player_stats, at the extra API-call cost documented there).

STAGED SCOPE, HONEST ABOUT WHAT'S NOT HERE YET, same pattern nfl_projections.py's own docstring
uses: this covers what Edge Board and Best Bets need. A Hot Hand Engine-equivalent, Matchup
Lab-equivalent, anytime-TD board, and QB efficiency table do NOT exist here yet — deliberately
deferred, not silently missing.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from projections import (  # genuinely sport-agnostic — reused, not duplicated
    prob_over, normalize_name, prob_to_decimal, prob_to_american, curate_selections,
)
import basketball_projections as BB_P   # shrink_prob only — pure probability math, zero
                                        # basketball-specific assumptions, same reuse nfl_
                                        # projections.py's own docstring already justifies
import config_ncaaf as CFG

DEFAULT_SIMS = CFG.DEFAULT_SIMS

# The unvalidated spread assumption this module's own docstring is explicit about — see there
# for why. 0.45 is a middle-of-the-road guess for football-stat game-to-game noisiness, not a
# measured value; the first priority once real per-game logs exist is replacing this constant
# with an empirical estimate, not tuning it further as a guess.
_RATE_CV = 0.45
_MIN_SCALE = 0.5   # floor on the Normal's scale so a very small rate doesn't collapse to a
                   # near-deterministic (zero-variance) distribution

# odds_market_key -> (slate-row field, display name, default line for the model-only board).
# Row field names match ncaaf_engine.player_row's own output exactly (PassYds/RushYds/
# Receptions/RecYds — already season-average PER-GAME rates, not totals). Default lines are
# round-number, model-only-board fallbacks (used only before a live line is fetched) — rough
# placeholders informed by general football norms, NOT calibrated against confirmed real NCAAF
# season averages the way NFL's own defaults were — worth tightening once real usage exists.
_MARKET_SPEC: Dict[str, Tuple[str, str, float]] = {
    "player_pass_yds":      ("PassYds",    "Pass Yards",      219.5),
    "player_rush_yds":      ("RushYds",    "Rush Yards",      49.5),
    "player_receptions":    ("Receptions", "Receptions",      4.5),
    "player_reception_yds": ("RecYds",     "Receiving Yards", 54.5),
}


def market_list() -> List[Tuple[str, str, str]]:
    """[(market_key, row_field, display_name), ...] — public, iterable form of _MARKET_SPEC."""
    return [(mkey, col, disp) for mkey, (col, disp, _line) in _MARKET_SPEC.items()]


def default_line(market_key: str) -> Optional[float]:
    spec = _MARKET_SPEC.get(market_key)
    return spec[2] if spec else None


def _dist(samples: np.ndarray) -> np.ndarray:
    """Normalized histogram: index i -> P(outcome == i). Same shape/semantics as
    projections._dist, so odds_api.compute_edges works identically for every sport."""
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


def simulate_player_stat(rate: float, sims: int, rng: np.random.Generator) -> np.ndarray:
    """PARAMETRIC simulation from a season-average per-game RATE — see this module's own
    docstring for why NCAAF can't bootstrap from real game logs the way every other sport here
    does. Draws from Normal(rate, max(rate * _RATE_CV, _MIN_SCALE)), clipped to non-negative
    integers (counting/yardage stats can't be fractional or negative). Returns an empty array
    for a non-positive rate — no meaningful distribution to build around zero or negative
    usage."""
    if rate is None or rate <= 0:
        return np.array([], dtype=np.int64)
    scale = max(rate * _RATE_CV, _MIN_SCALE)
    draws = rng.normal(loc=rate, scale=scale, size=sims)
    return np.clip(np.round(draws), 0, None).astype(np.int64)


def _clip_prob(p: float) -> float:
    """Final safety net: keep probabilities strictly inside (0, 1) so prob_to_american never
    hits its exact-boundary None case — runs AFTER shrink_prob's actual statistical correction,
    same division of labor every other sport's projections module uses."""
    return min(max(p, 0.02), 0.98)


def build_projection_index(rows: List[Dict], meta: List[Dict],
                           sims: int = DEFAULT_SIMS, seed: Optional[int] = None) -> Dict:
    """Return {(normalized_name, odds_market_key): {dist, mean, n_games, ctx}} for the slate —
    identical shape to every other sport's build_projection_index, so Edge Board doesn't need to
    know which sport it's looking at. `n_games` here is the TEAM's games-played count used as
    the per-game-rate denominator (ncaaf_engine._team_games_played_for_stats_season), reused as
    shrink_prob's own sample-size input — a team with only 2-3 games played so far genuinely
    deserves more shrinkage toward a neutral baseline than one with a full season's data behind
    its rate, same reasoning shrink_prob already applies everywhere else, just fed a team-level
    game count here instead of an individual player's own game count."""
    rng = np.random.default_rng(seed)
    index: Dict = {}

    for r in rows:
        markets = r.get("_markets") or []
        n_games = r.get("_team_games_played") or 0
        if not markets or n_games <= 0:
            continue
        nm = normalize_name(r["Player"])
        ctx = {"player": r["Player"], "team": r["Team"], "game": r["GameLabel"],
              "opp": r.get("Opp"), "lineup": "Active", "game_date": r.get("_game_date"),
              "position": r.get("Position", "")}
        for mkey in markets:
            col, _disp, _line = _MARKET_SPEC[mkey]
            rate = r.get(col)
            sim = simulate_player_stat(rate, sims, rng)
            if sim.size == 0:
                continue
            index[(nm, mkey)] = {"dist": _dist(sim), "mean": float(sim.mean()),
                                 "n_games": n_games, "ctx": ctx}
    return index


def default_board_from_index(index: Dict,
                             real_lines: Optional[Dict] = None) -> List[Dict]:
    """Model-only board (favored side at real or default lines) from the index — every NCAAF
    market in _MARKET_SPEC is a plain Over/Under, no special-case needed. Probabilities are
    shrunk toward a neutral baseline by (team) sample size before being clipped, same fix every
    other sport carries.

    real_lines: same shape as build_best_bets -- when supplied, uses the real book line for each
    player/market where available, falling back to _MARKET_SPEC defaults otherwise."""
    out: List[Dict] = []
    for (nm, mkey), entry in index.items():
        _col, disp, default_ln = _MARKET_SPEC.get(mkey, (mkey, mkey, 0.5))
        dist, ctx = entry["dist"], entry["ctx"]
        line, line_src = real_line_or_default_ncaaf(disp, ctx["player"], real_lines, default_ln)
        raw = prob_over(dist, line)
        shrunk = BB_P.shrink_prob(raw, entry.get("n_games", 0))
        over = _clip_prob(shrunk)
        side, prob = ("Over", over) if over >= 0.5 else ("Under", 1 - over)
        out.append(_signal(ctx["player"], ctx["team"], ctx["game"], disp, side, line, prob,
                           entry["mean"], Opp=ctx.get("opp"), Lineup=ctx.get("lineup"),
                           GameTime=ctx.get("game_date"), LineSource=line_src))
    return out


# --------------------------------------------------------------------------- Best Bets
BEST_BET_REF = {"Pass Yards": 0.5, "Rush Yards": 0.5, "Receptions": 0.5, "Receiving Yards": 0.5}

# NCAAF display market name -> Odds API market key. MUST STAY IN SYNC with sports.py's own
# NCAAF market_map AND odds_api's NCAAF market list, same as NFL_MARKET_TO_ODDS_KEY.
NCAAF_MARKET_TO_ODDS_KEY: Dict[str, str] = {
    "Pass Yards":      "player_pass_yds",
    "Rush Yards":      "player_rush_yds",
    "Receptions":      "player_receptions",
    "Receiving Yards": "player_reception_yds",
}


def real_line_or_default_ncaaf(
        market_display: str,
        player_name: str,
        real_lines: Optional[Dict],
        default: float) -> Tuple[float, str]:
    """The one shared decision point for every NCAAF market's line -- real, live sportsbook line
    when available, this platform's own _MARKET_SPEC placeholder otherwise. Mirrors
    nfl_projections.real_line_or_default_nfl exactly. Returns (line, source), source is 'book'
    or 'default'."""
    if real_lines is not None:
        odds_key = NCAAF_MARKET_TO_ODDS_KEY.get(market_display)
        if odds_key is not None:
            real = real_lines.get((normalize_name(player_name), odds_key))
            if real is not None:
                return float(real), "book"
    return default, "default"


def _favored_side(prob_over: float, ref: float):
    if prob_over >= ref:
        return "Over", prob_over, ref
    return "Under", 1.0 - prob_over, 1.0 - ref


def _player_reasons(rate: float, n_games: int, line: float, side: str, mean_display: str) -> str:
    """'Why' text built from the player's own season-average rate — no real game-to-game log
    exists to describe a trend from (see this module's own docstring), so this states the
    season-average basis plainly rather than fabricating a recency narrative the data can't
    support."""
    if n_games <= 0 or rate is None:
        return "no season stat data available"
    return (f"averaging {rate:.1f} {mean_display.lower()}/game over {n_games} team game(s) "
           f"this season (parametric model, not a per-game bootstrap — see module notes)")


def explain_miss(row: Optional[Dict], market: str = "Pass Yards") -> str:
    """NCAAF equivalent of every other sport's explain_miss role for Retrospective. `row` is a
    build_slate row looked up by player id; None means the player wasn't on the projected slate
    at all. Deliberately does NOT attempt a per-game trend explanation (no per-game log exists,
    see this module's own docstring) — states that honestly rather than fabricating one."""
    if not row:
        return ("Not on the projected slate (didn't clear a rotation floor, or a late roster "
                "addition) — the model never saw this player.")
    col = next((c for c, disp, _l in _MARKET_SPEC.values() if disp == market), None)
    if not col or not row.get(col):
        return "No season stat data available for this player/market."
    return (f"Season-average model ({row[col]:.1f}/game over {row.get('_team_games_played', 0)} "
           "team games) — no per-game log exists yet to say whether this specific result was a "
           "trend or an outlier; see module notes on this sport's current parametric-only scope.")


def build_best_bets(rows: List[Dict], sims: int = DEFAULT_SIMS,
                    seed: Optional[int] = None,
                    real_lines: Optional[Dict] = None) -> List[Dict]:
    """Rank candidate plays across every position-relevant market by conviction (model prob vs
    the reference prob for that market) — same output schema every sport's build_best_bets uses.
    Probabilities are shrunk toward a neutral baseline by (team) sample size before being
    clipped, same fix every other sport carries.

    real_lines: {(normalized_player_name, odds_api_market_key): point} from
    odds_api.market_lines_for_slate -- when supplied, each play's Line is the real book line for
    that specific player, not the _MARKET_SPEC placeholder. None (the default) preserves the
    always-placeholder behavior."""
    rng = np.random.default_rng(seed)
    plays: List[Dict] = []

    for r in rows:
        markets = r.get("_markets") or []
        n_games = r.get("_team_games_played") or 0
        if not markets or n_games <= 0:
            continue
        for mkey in markets:
            col, disp, default_ln = _MARKET_SPEC[mkey]
            rate = r.get(col)
            line, line_src = real_line_or_default_ncaaf(disp, r["Player"], real_lines, default_ln)
            sim = simulate_player_stat(rate, sims, rng)
            if sim.size == 0:
                continue
            raw = prob_over(_dist(sim), line)
            shrunk = BB_P.shrink_prob(raw, n_games)
            over = _clip_prob(shrunk)
            side, sp, ref_s = _favored_side(over, BEST_BET_REF.get(disp, 0.5))
            plays.append({
                "Player": r["Player"], "PlayerId": r.get("_pid"), "Team": r["Team"],
                "Game": r["GameLabel"], "Opp": r.get("Opp"), "Versus": r.get("Opp"),
                "Market": disp, "Side": side, "Line": line, "LineSource": line_src,
                "ModelProb": round(sp, 4), "Fair": prob_to_american(sp),
                "Conviction": round(sp / ref_s, 2) if ref_s > 0 else 0.0,
                "_ceiling": round(1.0 / ref_s, 2) if ref_s > 0 else None,
                "Why": _player_reasons(rate, n_games, line, side, disp),
                "_stat_key": col, "_team_games_played": n_games,
            })

    plays.sort(key=lambda x: x["Conviction"], reverse=True)
    return plays
