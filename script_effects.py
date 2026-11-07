"""
script_effects.py — NBA game scripts: how likely each kind of game is, and what each does to a player's line (Nov 7).

Measured in research/blowout_study.py over 1,367 NBA games (2025-26 and 2026-27 to date) -- 1,111 with a pre-game
spread -- against each player's own average over his previous games:

  SHARES   how games finish, by the pre-game spread: favorite by 15+, within 6, underdog by 15+ (the rest: "middle")
  EFFECT   how much more (or less) often a player beats his own average, by role and by how his team's game went,
           relative to that role's overall rate. Starters = 26+ minutes a game; bench = 12-26 (deep reserves, under 12,
           aren't measured and get no adjustment).

Used by the Game Script page: each prop's chance is recomputed under each script -- the model's read, shifted by the
script's effect for that player's role and side of the result. The shifts are centered so that, averaged over how
likely each script is, a player's chance is the model's own: a script view re-splits the model's read, it never
invents an edge. A ticket's chance under scripts = sum over scripts of P(script) x the product of its legs' chances
in that script, which counts legs that win or lose together; multiplying the legs' plain chances doesn't.

CAVEAT (stated on the page): effects are measured against players' own averages, not prop lines, and on points; the
other markets get half the shift. The books know the spread too, so some of this may already be in the lines.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

SCRIPTS = ("fav_blowout", "middle", "close", "dog_blowout")
LABEL = {"fav_blowout": "Favorite blows it open (15+)", "middle": "Middle (7–14)", "close": "Close game (within 6)",
         "dog_blowout": "Underdog blows it open (15+)"}

# (spread from, to): (P favorite by 15+, P within 6, P underdog by 15+)  -- blowout_study.py, 1,111 games
SHARES = [((0.0, 3.5), (0.196, 0.323, 0.145)), ((3.5, 6.5), (0.215, 0.332, 0.097)), ((6.5, 9.5), (0.303, 0.291, 0.070)),
          ((9.5, 12.5), (0.315, 0.255, 0.034)), ((12.5, 99.0), (0.546, 0.160, 0.021))]

# beat-own-average rate by role and team outcome, minus the role's overall rate (starter 50.6%, bench 39.8%)
EFFECT = {
    "starter": {"close": 0.529 - 0.506, "mid": 0.528 - 0.506, "blow_win": 0.529 - 0.506, "blow_lose": 0.404 - 0.506},
    "bench": {"close": 0.368 - 0.398, "mid": 0.394 - 0.398, "blow_win": 0.456 - 0.398, "blow_lose": 0.383 - 0.398},
}
STARTER_MIN, BENCH_MIN = 26.0, 12.0
POINTS_MARKETS = {"Points", "PRA", "Pts+Reb", "Pts+Ast"}
OTHER_WEIGHT = 0.5                 # rebounds / assists / threes etc.: half the measured (points) shift


def shares(spread: Optional[float]) -> Dict[str, float]:
    """{script: probability} from the absolute pre-game spread."""
    s = abs(float(spread)) if spread is not None else 0.0
    fav, close, dog = SHARES[-1][1]
    for (lo, hi), v in SHARES:
        if lo <= s < hi:
            fav, close, dog = v
            break
    return {"fav_blowout": fav, "middle": max(0.0, 1 - fav - close - dog), "close": close, "dog_blowout": dog}


def role(avg_min: Optional[float]) -> Optional[str]:
    if avg_min is None:
        return None
    if avg_min >= STARTER_MIN:
        return "starter"
    if avg_min >= BENCH_MIN:
        return "bench"
    return None


def _state(script: str, is_fav: bool) -> str:
    if script == "close":
        return "close"
    if script == "middle":
        return "mid"
    won = (script == "fav_blowout") == is_fav
    return "blow_win" if won else "blow_lose"


def over_by_script(p_over: float, rl: Optional[str], is_fav: bool, market: str, sh: Dict[str, float]) -> Dict[str, float]:
    """{script: P(Over)} for one prop. Shifts are centered on the script mix so the weighted average is p_over."""
    if rl is None:
        return {s: p_over for s in SCRIPTS}
    w = 1.0 if market in POINTS_MARKETS else OTHER_WEIGHT
    raw = {s: w * EFFECT[rl][_state(s, is_fav)] for s in SCRIPTS}
    centre = sum(sh[s] * raw[s] for s in SCRIPTS)
    return {s: min(0.97, max(0.03, p_over + raw[s] - centre)) for s in SCRIPTS}


def side_chance(by_script: Dict[str, float], side: str) -> Dict[str, float]:
    return {s: (p if side == "Over" else 1 - p) for s, p in by_script.items()}


def ticket(legs: Sequence[Dict[str, float]], sh: Dict[str, float]) -> Tuple[float, float, Dict[str, float]]:
    """(chance counting scripts, chance multiplying the legs' plain chances, {script: chance in that script}).
    Each leg is {script: chance of the side taken}."""
    per = {}
    for s in SCRIPTS:
        p = 1.0
        for lg in legs:
            p *= lg[s]
        per[s] = p
    scripted = sum(sh[s] * per[s] for s in SCRIPTS)
    plain = 1.0
    for lg in legs:
        plain *= sum(sh[s] * lg[s] for s in SCRIPTS)
    return scripted, plain, per


def fair_american(p: float) -> Optional[int]:
    if p <= 0 or p >= 1:
        return None
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))
