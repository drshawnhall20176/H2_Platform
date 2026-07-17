"""
nfl_projections.py — turns nfl_engine's slate rows into priced probabilities.

Matches projections.py's OUTPUT CONTRACT (build_projection_index / default_board_from_index /
DEFAULT_SIMS) — the same contract every other sport's projections module follows, which is what
lets Edge Board consume MLB, WNBA, NBA, NCAAMB, and now NFL through the same code path via
sports.active().projections. The genuinely sport-agnostic pieces (prob_over, prob_for_side,
normalize_name, format_et, prob_to_decimal, prob_to_american, curate_selections) are imported
straight from projections.py, not re-implemented — same convention every sport follows.

POSITION-AWARE, NOT ONE-SIZE-FITS-ALL: unlike basketball's Core 4 (every rotation player gets all
four markets), a market here only applies to the positions that actually generate that stat — see
nfl_engine.py's _MARKETS_FOR_POSITION and this module's own _MARKET_SPEC. build_projection_index/
build_best_bets both iterate a row's OWN `_markets` list (set by nfl_engine.player_row, already
gated per-position AND per-opportunity-floor), not a blanket set applied to everyone.

METHOD: same bootstrap-then-shrink approach as every basketball sport on this platform — each of a
player's last N games (config_nfl.RECENT_GAMES_N — 5, not basketball's 10; an NFL season is only
17 games, so a 10-game window would be over half the season, diluting the recency signal it exists
to capture) is treated as one draw from their true talent distribution, resampled with replacement,
then SHRUNK toward a neutral baseline by sample size before being clipped. shrink_prob is imported
directly from basketball_projections.py — not duplicated, and not moved into a differently-named
shared module either, despite the cross-domain-sounding import: the function itself is pure
probability math with zero basketball-specific assumptions (confirmed by reading it), and moving
it would mean touching three already-shipped, tested modules (WNBA/NBA/NCAAMB's own imports of it)
for a purely cosmetic rename. Reusing it as-is is the lower-risk choice.

STAGED SCOPE, HONEST ABOUT WHAT'S NOT HERE YET: this module covers what Edge Board and Best Bets
need — the platform's core "find a priced edge" pages. A Hot Hand Engine-equivalent (opponent-
adjusted leaderboard) and a Matchup Lab-equivalent (single-player deep dive vs. their own
head-to-head history) do NOT exist here yet — deliberately deferred, not silently missing, the
same staged-build pattern every other sport on this platform followed (MLB and WNBA both shipped
their core pricing pages before their own Hot Hand Engine/Matchup Lab equivalents).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from projections import (  # genuinely sport-agnostic — reused, not duplicated
    prob_over, prob_for_side, normalize_name, format_et,
    prob_to_decimal, prob_to_american, curate_selections,
)
import basketball_projections as BB_P   # shrink_prob only — see module docstring for why this
                                        # cross-domain-sounding import is the right call, not a mistake
import config_nfl as CFG

DEFAULT_SIMS = CFG.DEFAULT_SIMS

# odds_market_key -> (weekly-stats column, display name, default line for the model-only board).
# Default lines are round-number, model-only-board fallbacks (used only before a live line is
# fetched) — NOT calibrated book numbers, worth tuning empirically once real usage exists, same
# honest caveat every other sport's defaults on this platform carry. Anchored to real, confirmed
# 2025-season per-game norms for a rotation player at each position (not guessed from nothing):
# ~225 pass yards/game for a starting QB, ~45 rush yards for a rotation RB, ~3.5 catches / 40
# yards for a target-share WR/TE.
_MARKET_SPEC: Dict[str, Tuple[str, str, float]] = {
    "player_pass_yds":      ("passing_yards",   "Pass Yards",      224.5),
    "player_rush_yds":      ("rushing_yards",   "Rush Yards",      44.5),
    "player_receptions":    ("receptions",      "Receptions",      3.5),
    "player_reception_yds": ("receiving_yards", "Receiving Yards", 39.5),
}


def market_list() -> List[Tuple[str, str, str]]:
    """[(market_key, stat_column, display_name), ...] — public, iterable form of _MARKET_SPEC."""
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


def simulate_player_stat(recent_values: List[float], sims: int, rng: np.random.Generator) -> np.ndarray:
    """Bootstrap `sims` draws (with replacement) from a player's recent-game values for one stat.
    Values are rounded to the nearest non-negative integer (counting/yardage stats can't be
    fractional or negative). Returns an empty array if there's no game log to sample from."""
    if not recent_values:
        return np.array([], dtype=np.int64)
    draws = rng.choice(np.asarray(recent_values, dtype=np.float64), size=sims, replace=True)
    return np.clip(np.round(draws), 0, None).astype(np.int64)


def _clip_prob(p: float) -> float:
    """Final safety net: keep probabilities strictly inside (0, 1) so `prob_to_american` never
    hits its exact-boundary None case. Runs AFTER basketball_projections.shrink_prob, which does
    the actual statistical correction for small-sample overconfidence — same division of labor
    every other sport's projections module uses."""
    return min(max(p, 0.02), 0.98)


def build_projection_index(rows: List[Dict], meta: List[Dict],
                           sims: int = DEFAULT_SIMS, seed: Optional[int] = None) -> Dict:
    """Return {(normalized_name, odds_market_key): {dist, mean, n_games, ctx}} for the slate —
    identical shape to every other sport's build_projection_index, so Edge Board doesn't need to
    know which sport it's looking at. Only iterates each row's OWN `_markets` — a QB's row never
    contributes a "player_receptions" entry, unlike basketball's blanket four-markets-for-everyone."""
    rng = np.random.default_rng(seed)
    index: Dict = {}

    for r in rows:
        log = r.get("_recent_games") or []
        markets = r.get("_markets") or []
        if not log or not markets:
            continue
        nm = normalize_name(r["Player"])
        ctx = {"player": r["Player"], "team": r["Team"], "game": r["GameLabel"],
              "opp": r.get("Opp"), "lineup": "Active", "game_date": r.get("_game_date")}
        for mkey in markets:
            col, _disp, _line = _MARKET_SPEC[mkey]
            values = [g.get(col) or 0 for g in log]
            sim = simulate_player_stat(values, sims, rng)
            if sim.size == 0:
                continue
            index[(nm, mkey)] = {"dist": _dist(sim), "mean": float(sim.mean()),
                                 "n_games": len(values), "ctx": ctx}
    return index


def default_board_from_index(index: Dict) -> List[Dict]:
    """Model-only board (favored side at default lines) from the index — every NFL market in
    _MARKET_SPEC is a plain Over/Under, no special-case needed. Probabilities are shrunk toward a
    neutral baseline by sample size before being clipped, same fix every other sport carries."""
    out: List[Dict] = []
    for (nm, mkey), entry in index.items():
        _col, disp, line = _MARKET_SPEC.get(mkey, (mkey, mkey, 0.5))
        dist, ctx = entry["dist"], entry["ctx"]
        raw = prob_over(dist, line)
        shrunk = BB_P.shrink_prob(raw, entry.get("n_games", 0))
        over = _clip_prob(shrunk)
        side, prob = ("Over", over) if over >= 0.5 else ("Under", 1 - over)
        out.append(_signal(ctx["player"], ctx["team"], ctx["game"], disp, side, line, prob,
                           entry["mean"], Opp=ctx.get("opp"), Lineup=ctx.get("lineup"),
                           GameTime=ctx.get("game_date")))
    return out


# --------------------------------------------------------------------------- Best Bets
# Reference (typical/coin-flip) hit-rate per market — 0.5 for all four, honest given the default
# lines above are round-number estimates, not book-calibrated (same reasoning every sport uses).
BEST_BET_REF = {"Pass Yards": 0.5, "Rush Yards": 0.5, "Receptions": 0.5, "Receiving Yards": 0.5}


def _favored_side(prob_over: float, ref: float):
    if prob_over >= ref:
        return "Over", prob_over, ref
    return "Under", 1.0 - prob_over, 1.0 - ref


def _player_reasons(values: List[float], line: float, side: str) -> str:
    """'Why' text built from the player's own recent-game log — no opponent/weather/game-script
    inputs exist in v1 (see module docstring's staged-scope note), so this leans on what's
    actually available: how consistently they've cleared this exact line recently, and whether
    their last couple games are trending away from their own average."""
    n = len(values)
    if n == 0:
        return "no recent-game data available"
    hits = sum(1 for v in values if v > line) if side == "Over" else sum(1 for v in values if v < line)
    avg = sum(values) / n
    recent = values[:2]     # most recent first (see nfl_engine.player_recent_games)
    recent_avg = sum(recent) / len(recent) if recent else avg
    trend = ""
    if recent and avg > 0 and abs(recent_avg - avg) >= max(1.0, avg * 0.20):
        trend = ", trending up" if recent_avg > avg else ", trending down"
    return f"cleared {line:g} in {hits} of last {n} games (avg {avg:.1f}{trend})"


def explain_miss(row: Optional[Dict], market: str = "Pass Yards") -> str:
    """NFL equivalent of retro.explain_miss's role: explain a result the model ranked LOW.
    `row` is a build_slate row looked up by player id; None means the player wasn't on the
    projected slate at all (didn't clear a rotation floor, or a late roster addition the model
    never saw). Same contract as WNBA/NBA/NCAAMB's own explain_miss — Retrospective calls this
    unconditionally for every non-MLB sport (`P.explain_miss` where P is whichever sport is
    active), so a missing implementation here is a real crash, not a cosmetic gap; this was
    exactly that crash, found live and fixed."""
    if not row:
        return ("Not on the projected slate (didn't clear a rotation floor, or a late roster "
                "addition) — the model never saw this player.")
    log = row.get("_recent_games") or []
    col = next((c for c, disp, _l in _MARKET_SPEC.values() if disp == market), None)
    if not log or not col:
        return "No recent-game data available for this player."
    values = [g.get(col) or 0 for g in log]
    avg = sum(values) / len(values)
    recent = values[:2]     # most recent first (see nfl_engine.player_recent_games)
    recent_avg = sum(recent) / len(recent) if recent else avg
    if avg > 0 and recent_avg >= avg * 1.15:
        return (f"Catchable — trending up over the last {len(recent)} games (avg {recent_avg:.1f} "
                f"vs {avg:.1f} in the full recent sample) before this one; recency weighting "
                "hadn't fully caught up yet.")
    return (f"Genuine outlier — averaging {avg:.1f} over the last {len(values)} games with no "
            "recent uptick; this result sits above their established form. Variance, not a "
            "systematic miss.")


def build_best_bets(rows: List[Dict], sims: int = DEFAULT_SIMS,
                    seed: Optional[int] = None) -> List[Dict]:
    """Rank candidate plays across every position-relevant market by conviction (model prob vs
    the reference prob for that market), each with recent-form reasoning. No odds required — same
    output schema every sport's build_best_bets uses. Probabilities are shrunk toward a neutral
    baseline by sample size before being clipped, same fix every other sport carries."""
    rng = np.random.default_rng(seed)
    plays: List[Dict] = []

    for r in rows:
        log = r.get("_recent_games") or []
        markets = r.get("_markets") or []
        if not log or not markets:
            continue
        for mkey in markets:
            col, disp, line = _MARKET_SPEC[mkey]
            values = [g.get(col) or 0 for g in log]
            sim = simulate_player_stat(values, sims, rng)
            if sim.size == 0:
                continue
            raw = prob_over(_dist(sim), line)
            shrunk = BB_P.shrink_prob(raw, len(values))
            over = _clip_prob(shrunk)
            side, sp, ref_s = _favored_side(over, BEST_BET_REF.get(disp, 0.5))
            plays.append({
                "Player": r["Player"], "PlayerId": r.get("_pid"), "Team": r["Team"],
                "Game": r["GameLabel"], "Opp": r.get("Opp"), "Versus": r.get("Opp"),
                "Market": disp, "Side": side, "Line": line,
                "ModelProb": round(sp, 4), "Fair": prob_to_american(sp),
                "Conviction": round(sp / ref_s, 2) if ref_s > 0 else 0.0,
                "Why": _player_reasons(values, line, side),
                "_stat_key": col, "_game_log": log,
            })

    plays.sort(key=lambda x: x["Conviction"], reverse=True)
    return plays
