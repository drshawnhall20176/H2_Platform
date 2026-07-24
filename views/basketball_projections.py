"""
basketball_projections.py — league-agnostic basketball projection logic shared across ESPN-
basketball-API sports (WNBA today, NBA whenever that build starts).

SCOPE, DELIBERATELY NARROW — same reasoning as basketball_engine.py: this holds blowout_risk_tag,
a pure threshold function with zero WNBA-specific dependency. build_hot_hand_board itself stays in
wnba_projections.py (not moved here) because it iterates WNBA's own _MARKET_SPEC, whose DEFAULT
LINE values (12.5 pts, 5.5 reb, ...) are WNBA-scale tuning constants, not basketball-generic ones —
NBA's would be meaningfully different (longer games, faster pace, higher counting stats), and
guessing at a shared default-line table before NBA's own build exists would be the same kind of
premature abstraction basketball_engine.py's docstring argues against.
"""

from __future__ import annotations

from typing import Optional


def shrink_prob(raw_prob: float, n_games: int, prior_strength: float = 4.0,
                reference: float = 0.5) -> float:
    """Empirical-Bayes-style shrinkage of a bootstrap-estimated probability toward `reference`
    (a neutral 50/50 baseline, matching BEST_BET_REF's own convention), weighted by how many real
    recent games actually back the estimate — not resample draws, actual games in the log.

    THE PROBLEM THIS FIXES: a bootstrap resample of a player's last N recent games estimates
    P(stat > line) as, in the large-`sims` limit, just the empirical fraction of those N real
    games that cleared it. With a short recent-game log — as few as 4-10 games, common early
    season or for a new callup — that fraction can land on a literal 0/N or N/N: 0% or 100%.
    `_clip_prob` (in wnba_projections.py/nba_projections.py) caps the DISPLAYED number at
    2%/98%, but that's a display-layer fix, not a statistical one: a 4-game perfect streak and a
    10-game perfect streak both clip to the exact same 98%, and since Best Bets' Conviction is a
    direct function of ModelProb, they also tie on Conviction — collapsing the ranking among them
    into an arbitrary sort order instead of a real one. Found live: a Best Bets board where many
    different players/markets all showed identical 98% / -4900 fair odds / 1.96x conviction
    simultaneously, purely because they'd all independently hit the same clip ceiling.

    THE FIX is the same conceptual shrinkage projections.py already uses for MLB's small-sample
    rates (pulling an observed rate toward a league baseline, weighted by how much data backs it
    — see that module's own "Small samples lie" comment), adapted here from "rate per plate
    appearance" to "rate per recent game." `prior_strength` is `reference`'s weight in virtual
    games: a 4-game sample gets pulled hard toward 50/50, a 40-game sample barely moves at all —
    the correction fades out on its own as real evidence accumulates, instead of every sample
    size hitting the same flat ceiling regardless of how much (or little) actually backs it.

    `prior_strength=4.0` is a reasonable starting constant (roughly 40% of RECENT_GAMES_N's
    default 10 games) — NOT backtested, worth tuning empirically once there's a real track record
    to check calibration against, same honest caveat every other tuning constant on this platform
    carries (BLOWOUT_THRESHOLD, MIN_AVG_MINUTES, etc.). Meant to run BEFORE `_clip_prob`, not
    replace it — clipping still matters afterward as a final safety net against the exact 0.0/1.0
    boundary (which `prob_to_american` can't format), even though shrinkage makes hitting that
    exact boundary far less likely than before."""
    if n_games <= 0:
        return reference
    return (raw_prob * n_games + prior_strength * reference) / (n_games + prior_strength)


def blowout_risk_tag(spread: Optional[float], threshold: float = 10.0) -> str:
    """Simple heuristic label for game-competitiveness risk from a team's point spread (negative
    = favorite, positive = underdog — the Odds API's own convention). NOT a calibrated model —
    just a threshold on a number that's already available once spreads are fetched. |spread| >=
    threshold flags elevated blowout risk: the favorite's stars risk reduced 4th-quarter minutes,
    the underdog's bench risks extended run. This tag intentionally doesn't try to say WHICH
    player role is affected (that needs a starter/bench classification this data doesn't cleanly
    support) — just that the game itself carries that risk, for the trader to weigh against who
    they're actually looking at. threshold defaults to 10 points: a reasonable WNBA-scale
    starting point (40-minute games, lower-scoring than the NBA, so a double-digit spread is
    already a real edge), not a backtested cutoff — worth tuning empirically over time, and worth
    reconsidering entirely for NBA's higher-scoring games when that build happens. Returns "—"
    (not a fabricated "competitive") when spread is None — no data, not a claim."""
    if spread is None:
        return "—"
    return "⚠️ Blowout risk" if abs(spread) >= threshold else "Competitive"
