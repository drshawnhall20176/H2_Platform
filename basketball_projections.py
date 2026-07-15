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
