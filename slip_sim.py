"""
slip_sim.py — pressure-test a betting slip by simulation. Pure logic (numpy only): no Streamlit,
no network, fully unit-tested, so the Slip Lab page is a thin layer over numbers that are checked.

WHAT "PRESSURE TEST" MEANS HERE. A slip's headline numbers (combined probability, EV) come from
each leg's model probability treated as exactly right and the legs treated as independent. Both
are assumptions. This module attacks each one:

  1. CORRELATION. Legs from the same game (or the same player) are not independent. Outcomes are
     drawn from a Gaussian copula whose correlation matrix is built from who-plays-with-whom and
     the sign of each leg's side, so "two Overs from one game" hit together a bit more often than
     the independent product says (and an Over with an Under, a bit less).
  2. MODEL UNCERTAINTY. Every leg probability is an estimate from ~10 games. Each simulated
     "world" draws each leg's TRUE probability from a Beta distribution centred on the model's
     number, with a spread set by how many games' worth of evidence backs it (n_eff), so the result
     is a range, not a point. Small samples give wide ranges.
  3. MODEL OVERCONFIDENCE. A haircut scenario subtracts N percentage points from every leg (the
     model being systematically too bullish is the most common way a +EV slip turns out not to be).
  4. "THE BOOK IS RIGHT." A scenario that swaps every leg's probability for the book's own no-vig
     price: if the slip is still +EV when the market is right, the edge is structural, not just
     the model disagreeing with the market.
  5. LEG WEAKNESS. Each leg is dropped in turn to show which one is carrying (or sinking) the slip.
  6. REPEAT PLAY. The same slip run N times from a fixed bankroll fraction, across the model-
     uncertainty worlds: probability of being ahead, the spread of outcomes, and drawdown risk.

COMMON RANDOM NUMBERS: one set of correlated normal draws is shared by every scenario, so scenario
differences are the scenarios, not simulation noise.

Payouts are expressed as a RETURN MULTIPLE of the total amount staked (0 = lose everything, 1 =
push / money back, 3 = the 3x of a 2-pick Power Play). That single convention lets a sportsbook
parlay, a pick'em Power/Flex entry and a set of straight singles all flow through the same metrics.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

# --------------------------------------------------------------------------- payout tables
# PrizePicks standard multipliers (prizepicks.com/resources/prizepicks-payouts for Power Play and
# the all-correct Flex tiers; partial Flex tiers per propellerpicks.com's published chart), as
# checked 2026-09-21. PrizePicks changes these by promotion, league and state, and lineups with
# Goblin/Demon picks pay differently — every table here is a STARTING POINT the page lets the user
# overwrite with whatever their app actually shows for the entry.
POWER_PLAY: Dict[int, Dict[int, float]] = {
    2: {2: 3.0}, 3: {3: 6.0}, 4: {4: 10.0}, 5: {5: 20.0}, 6: {6: 37.5},
}
FLEX_PLAY: Dict[int, Dict[int, float]] = {
    2: {2: 2.0, 1: 0.5},
    3: {3: 3.0, 2: 1.0},
    4: {4: 6.0, 3: 1.5},
    5: {5: 10.0, 4: 2.0, 3: 0.4},
    6: {6: 25.0, 5: 2.0, 4: 0.4},
}
# DraftKings Pick6: only the BASE payout is modelled (all picks correct). DraftKings also pays
# "Extra Winnings" from a pool that depends on the rest of the field, which cannot be known ahead
# of time — ignoring it makes the EV here conservative, not optimistic. Only the 3-pick (6x) and
# 4-pick (10x) bases are confirmed from DraftKings' own examples; the rest are placeholders the
# page tells the user to replace with the multiplier on the DraftKings entry screen.
PICK6_BASE: Dict[int, Dict[int, float]] = {
    2: {2: 3.0}, 3: {3: 6.0}, 4: {4: 10.0}, 5: {5: 20.0}, 6: {6: 37.5},
}

PAYOUT_TABLES: Dict[str, Dict[int, Dict[int, float]]] = {
    "power": POWER_PLAY, "flex": FLEX_PLAY, "pick6": PICK6_BASE,
}


def return_multiple(mode: str, n_legs: int, n_hits, *, decimal_odds: Optional[float] = None,
                    table: Optional[Dict[int, float]] = None):
    """Total return per $1 staked for an entry with `n_legs` legs of which `n_hits` won.

    n_hits may be a numpy array (vectorized). mode:
      "parlay" — all-or-nothing at `decimal_odds` (the sportsbook's combined decimal price)
      "table"  — look up `table` {hits: multiple} (PrizePicks Power/Flex, Pick6 base); a hit count
                 not in the table pays 0
    """
    hits = np.asarray(n_hits)
    if mode == "parlay":
        d = float(decimal_odds or 1.0)
        return np.where(hits >= n_legs, d, 0.0)
    if mode == "table":
        tbl = table or {}
        out = np.zeros(hits.shape, dtype=float)
        for k, mult in tbl.items():
            out = np.where(hits == int(k), float(mult), out)
        return out
    raise ValueError(f"unknown payout mode {mode!r}")


def parlay_decimal(decimals: Sequence[float]) -> float:
    d = 1.0
    for x in decimals:
        d *= float(x)
    return d


# --------------------------------------------------------------------------- normal helpers
def ndtri(p) -> np.ndarray:
    """Inverse standard-normal CDF (Acklam's rational approximation, |error| < 1.2e-9), vectorized.
    Implemented here so the module needs numpy only."""
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    out = np.empty_like(p)

    lo = p < plow
    if lo.any():
        q = np.sqrt(-2 * np.log(p[lo]))
        out[lo] = (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
                  ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
    hi = p > phigh
    if hi.any():
        q = np.sqrt(-2 * np.log(1 - p[hi]))
        out[hi] = -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
                   ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
    mid = ~(lo | hi)
    if mid.any():
        q = p[mid] - 0.5
        r = q * q
        out[mid] = (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) * q / \
                   (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1)
    return out


# --------------------------------------------------------------------------- correlation
def _side_sign(leg: Dict) -> int:
    return -1 if str(leg.get("side", "Over")).lower().startswith("u") else 1


# Leg "kinds" beyond a player prop, from the full book menu (Slip Lab). A leg with no "kind" (every
# board leg, every hand-typed leg) is a player prop and is treated EXACTLY as before.
MARGIN_KINDS = ("moneyline", "spread")          # "team T wins / covers" — leg["team"] is T
TOTAL_KINDS = ("total", "team_total")           # over/under on points; team_total also has leg["team"]

# Correlation between a team/game-level leg and another leg in the SAME game. These are fixed,
# deliberately rounded rules of thumb (documented in the Slip Lab page), not fitted numbers —
# what they capture is the direction and rough size of the link, so a same-game parlay is not
# treated as independent legs. Only same-game pairs are ever correlated.
RHO_SAME_MARGIN = 0.85      # ML + spread, same team (or the two teams' sides: negative)
RHO_TOTAL_TOTAL = 0.90      # game total vs game total (alt lines of the same over/under)
RHO_TOTAL_TEAMTOT = 0.60    # game total vs a team total
RHO_TEAMTOT_SAME = 0.90     # two totals on the same team
RHO_TEAMTOT_OPP = 0.30      # totals on the two opposing teams (a shootout lifts both)
RHO_MARGIN_TEAMTOT = 0.25   # team wins/covers vs that team's own total (opponent's: negative)
RHO_TOTAL_PLAYER = 0.20     # game / team total vs a player prop in that game
RHO_MARGIN_PLAYER = 0.15    # team wins/covers vs its own player's prop (opponent's: 0.7x, negative)


def _kind(leg: Dict) -> str:
    return str(leg.get("kind") or "player")


def _same_team(a: Dict, b: Dict) -> Optional[bool]:
    """True/False when both legs name a team, None when either doesn't (then no team rule applies)."""
    ta, tb = a.get("team"), b.get("team")
    if not ta or not tb:
        return None
    return str(ta) == str(tb)


def _team_kind_rho(a: Dict, b: Dict) -> float:
    """Correlation for a same-game pair where at least one leg is a team/game-level kind."""
    ka, kb = _kind(a), _kind(b)
    sa, sb = _side_sign(a), _side_sign(b)
    same = _same_team(a, b)
    a_margin, b_margin = ka in MARGIN_KINDS, kb in MARGIN_KINDS
    if a_margin and b_margin:
        if same is None:
            return 0.0
        return RHO_SAME_MARGIN if same else -RHO_SAME_MARGIN
    if a_margin or b_margin:
        m, o = (a, b) if a_margin else (b, a)
        ko, so = _kind(o), _side_sign(o)
        if ko == "total":
            return 0.0                                  # who wins says little about the total
        if same is None:
            return 0.0
        if ko == "team_total":
            return so * (RHO_MARGIN_TEAMTOT if same else -RHO_MARGIN_TEAMTOT * 0.6)
        return so * (RHO_MARGIN_PLAYER if same else -RHO_MARGIN_PLAYER * 0.7)   # a player prop
    # no margin leg: totals and player props
    if ka == "total" and kb == "total":
        return RHO_TOTAL_TOTAL * sa * sb
    if "total" in (ka, kb):
        other = kb if ka == "total" else ka
        return (RHO_TOTAL_TEAMTOT if other == "team_total" else RHO_TOTAL_PLAYER) * sa * sb
    if ka == "team_total" and kb == "team_total":
        if same is None:
            return 0.0
        return (RHO_TEAMTOT_SAME if same else RHO_TEAMTOT_OPP) * sa * sb
    # team_total vs a player prop
    return (RHO_TOTAL_PLAYER if same in (True, None) else RHO_TOTAL_PLAYER * 0.25) * sa * sb


def correlation_matrix(legs: List[Dict], rho_player: float = 0.30, rho_game: float = 0.08) -> np.ndarray:
    """Correlation between legs' outcomes, as a positive-semidefinite k x k matrix.

    Two legs on the SAME PLAYER (different markets: points and assists) get rho_player; two legs
    in the SAME GAME but different players get rho_game. Either is multiplied by the product of
    the two legs' side signs (Over=+1, Under=-1): an Over and an Under from the same game move
    against each other, two Overs move together. Legs in different games are independent. The
    raw matrix is repaired to the nearest valid correlation matrix if the chosen values make it
    indefinite (possible when many same-game legs are stacked with mixed signs).

    Team- and game-level legs (moneyline, spread, game total, team total — leg["kind"]) use the
    fixed rules above instead; a slip with only player props behaves exactly as it always did.
    """
    k = len(legs)
    R = np.eye(k)
    for i in range(k):
        for j in range(i + 1, k):
            a, b = legs[i], legs[j]
            same_game = bool(a.get("game")) and a.get("game") == b.get("game")
            if not same_game:
                continue
            if _kind(a) != "player" or _kind(b) != "player":
                R[i, j] = R[j, i] = float(np.clip(_team_kind_rho(a, b), -0.95, 0.95))
                continue
            same_player = bool(a.get("player")) and a.get("player") == b.get("player")
            rho = rho_player if same_player else rho_game
            R[i, j] = R[j, i] = rho * _side_sign(a) * _side_sign(b)
    return _nearest_psd_correlation(R)


def _nearest_psd_correlation(R: np.ndarray) -> np.ndarray:
    vals, vecs = np.linalg.eigh(R)
    if vals.min() >= 1e-8:
        return R
    vals = np.clip(vals, 1e-6, None)
    fixed = vecs @ np.diag(vals) @ vecs.T
    d = np.sqrt(np.diag(fixed))
    fixed = fixed / np.outer(d, d)
    np.fill_diagonal(fixed, 1.0)
    return fixed


def draw_normals(R: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """n x k correlated standard-normal draws for correlation matrix R."""
    k = R.shape[0]
    L = np.linalg.cholesky(R + 1e-10 * np.eye(k))
    return rng.standard_normal((n, k)) @ L.T


# --------------------------------------------------------------------------- scenario engine
def _clip(p) -> np.ndarray:
    return np.clip(np.asarray(p, dtype=float), 0.005, 0.995)


def sample_worlds(p: np.ndarray, n_eff: np.ndarray, n_worlds: int, rng: np.random.Generator,
                  uncertainty: bool = True) -> np.ndarray:
    """(n_worlds x k) TRUE leg probabilities: Beta draws centred on p with concentration n_eff
    (the number of games' worth of evidence behind each estimate). uncertainty=False returns p
    repeated (every world identical)."""
    p = _clip(p)
    if not uncertainty:
        return np.tile(p, (n_worlds, 1))
    nu = np.clip(np.asarray(n_eff, dtype=float), 3.0, 500.0)
    return _clip(rng.beta(p * nu, (1 - p) * nu, size=(n_worlds, len(p))))


def _returns(hits: np.ndarray, payout: Dict) -> np.ndarray:
    """Return multiple per draw for a hits array (..., k) under `payout`:
      {"mode": "parlay", "decimal": d}                 all-or-nothing
      {"mode": "table",  "table": {hits: multiple}}    Power / Flex / Pick6
      {"mode": "singles", "decimals": [...], "stakes": [...]}   independent straight bets
    """
    k = hits.shape[-1]
    mode = payout["mode"]
    if mode == "singles":
        dec = np.asarray(payout["decimals"], dtype=float)
        stk = np.asarray(payout["stakes"], dtype=float)
        total = stk.sum()
        if total <= 0:
            return np.ones(hits.shape[:-1])
        gross = (hits * (dec * stk)).sum(axis=-1)   # stake returned + winnings for the winners
        return gross / total
    n_hits = hits.sum(axis=-1)
    return return_multiple(mode, k, n_hits, decimal_odds=payout.get("decimal"), table=payout.get("table"))


def _summ(R: np.ndarray) -> Dict[str, float]:
    return {"ev": float(R.mean() - 1.0), "p_profit": float((R > 1.0 + 1e-9).mean()),
            "p_total_loss": float((R <= 1e-9).mean()), "mean_return": float(R.mean())}


def evaluate(legs: List[Dict], payout: Dict, *, rho_player: float = 0.30, rho_game: float = 0.08,
             n_sims: int = 20000, n_worlds: int = 200, seed: Optional[int] = None,
             haircut: float = 0.0, prob_key: str = "p", uncertainty: bool = True,
             _Z: Optional[np.ndarray] = None, _worlds: Optional[np.ndarray] = None) -> Dict:
    """Simulate one slip under one scenario.

    legs: dicts with prob_key (default "p", the leg probability), "n_eff" (games of evidence,
          default 10), "game", "player", "side".
    Returns per-leg means, hit-count distribution, the independent-product joint probability, and
    return-multiple metrics — both the pooled ("predictive") result and the spread of the EV
    across model-uncertainty worlds (5th/50th/95th percentile), plus the raw return array `R`
    (worlds x sims) for downstream use.
    """
    k = len(legs)
    rng = np.random.default_rng(seed)
    p = np.array([float(l.get(prob_key) if l.get(prob_key) is not None else l["p"]) for l in legs])
    p = _clip(p - haircut)
    n_eff = np.array([float(l.get("n_eff") or 10.0) for l in legs])
    R_corr = correlation_matrix(legs, rho_player, rho_game)
    Z = _Z if _Z is not None else draw_normals(R_corr, n_sims, rng)
    worlds = _worlds if _worlds is not None else sample_worlds(p, n_eff, n_worlds, rng, uncertainty)
    if _worlds is not None:                       # shared uncertainty draws: apply the haircut on top
        worlds = _clip(worlds - haircut) if haircut else worlds
    thresholds = ndtri(worlds)                    # (W x k)

    W = thresholds.shape[0]
    R_all = np.empty((W, Z.shape[0]))
    hit_counts = np.zeros(k + 1)
    leg_hits = np.zeros(k)
    for w in range(W):
        hits = Z < thresholds[w]                  # (n x k) bool
        R_all[w] = _returns(hits, payout)
        hit_counts += np.bincount(hits.sum(axis=1), minlength=k + 1)
        leg_hits += hits.mean(axis=0)
    hit_dist = hit_counts / hit_counts.sum()
    per_world_ev = R_all.mean(axis=1) - 1.0

    out = _summ(R_all)
    out.update({
        "k": k, "p_leg": p.tolist(), "leg_hit_rate": (leg_hits / W).tolist(),
        "hit_dist": hit_dist.tolist(),
        "p_all": float(hit_dist[k]), "p_all_independent": float(np.prod(p)),
        "ev_p05": float(np.percentile(per_world_ev, 5)), "ev_p50": float(np.percentile(per_world_ev, 50)),
        "ev_p95": float(np.percentile(per_world_ev, 95)),
        "p_ev_positive": float((per_world_ev > 0).mean()),
        "R": R_all, "Z": Z, "worlds": worlds, "corr": R_corr,
    })
    return out


def stress_scenarios(legs: List[Dict], payout: Dict, *, haircuts: Sequence[float] = (0.03, 0.05, 0.08),
                     rho_player: float = 0.30, rho_game: float = 0.08, n_sims: int = 20000,
                     n_worlds: int = 200, seed: Optional[int] = 7) -> List[Dict]:
    """Baseline plus overconfidence haircuts plus the 'book is right' scenario, all on the SAME
    random draws. One row per scenario: name, ev, p_profit, p_all, ev_p05/p95."""
    base = evaluate(legs, payout, rho_player=rho_player, rho_game=rho_game, n_sims=n_sims,
                    n_worlds=n_worlds, seed=seed)
    rows = [_scenario_row("Model as-is", base)]
    for h in haircuts:
        r = evaluate(legs, payout, rho_player=rho_player, rho_game=rho_game, n_sims=n_sims,
                     n_worlds=n_worlds, seed=seed, haircut=h, _Z=base["Z"], _worlds=base["worlds"])
        rows.append(_scenario_row(f"Model {h*100:.0f} pts too bullish", r))
    if all(l.get("p_mkt") is not None for l in legs):
        r = evaluate(legs, payout, rho_player=rho_player, rho_game=rho_game, n_sims=n_sims,
                     n_worlds=n_worlds, seed=seed, prob_key="p_mkt", uncertainty=False, _Z=base["Z"])
        rows.append(_scenario_row("If the book's no-vig price is right", r))
    return rows


def _scenario_row(name: str, r: Dict) -> Dict:
    return {"scenario": name, "ev": r["ev"], "p_profit": r["p_profit"], "p_all": r["p_all"],
            "ev_p05": r["ev_p05"], "ev_p95": r["ev_p95"], "p_ev_positive": r["p_ev_positive"]}


def leg_drop_table(legs: List[Dict], payout_for_subset, *, rho_player: float = 0.30,
                   rho_game: float = 0.08, n_sims: int = 20000, n_worlds: int = 100,
                   seed: Optional[int] = 7) -> List[Dict]:
    """For each leg, the slip's EV and P(profit) WITHOUT that leg, against the full slip.

    payout_for_subset(legs_subset) -> payout dict for that smaller slip (a parlay's price is the
    product of the remaining legs' prices; a Power/Flex table is looked up for the smaller size).
    Returns one row per leg: leg label, ev_without, p_profit_without, delta_ev (full minus
    without — positive means the leg is helping, negative means it is dragging the slip down)."""
    full = evaluate(legs, payout_for_subset(legs), rho_player=rho_player, rho_game=rho_game,
                    n_sims=n_sims, n_worlds=n_worlds, seed=seed)
    rows = []
    for i, leg in enumerate(legs):
        rest = legs[:i] + legs[i + 1:]
        label = leg.get("label") or f"{leg.get('player')} {leg.get('market')} {leg.get('side')} {leg.get('line')}"
        if len(rest) < 1:
            rows.append({"leg": label, "ev_without": None, "p_profit_without": None, "delta_ev": None})
            continue
        try:
            payout = payout_for_subset(rest)
        except (KeyError, ValueError):
            rows.append({"leg": label, "ev_without": None, "p_profit_without": None, "delta_ev": None})
            continue
        r = evaluate(rest, payout, rho_player=rho_player, rho_game=rho_game, n_sims=n_sims,
                     n_worlds=n_worlds, seed=seed)
        rows.append({"leg": label, "ev_without": r["ev"], "p_profit_without": r["p_profit"],
                     "delta_ev": full["ev"] - r["ev"]})
    return rows


def repeat_play(R: np.ndarray, *, stake_fraction: float, n_slips: int = 100, n_paths: int = 2000,
                seed: Optional[int] = 11, drawdown_levels: Sequence[float] = (0.2, 0.4)) -> Dict:
    """Run the same slip `n_slips` times in a row from a bankroll, staking `stake_fraction` of the
    STARTING bankroll each time (flat stake, so paths are comparable), across the model-
    uncertainty worlds in R (worlds x sims, from evaluate()).

    Each path picks a random world (a fixed "true" probability set for that path) and draws each
    slip's return from that world's simulated outcomes. Returns the final-bankroll distribution
    (as a multiple of the starting bankroll), P(ahead), P(ruin = bankroll <= 0), and for each
    drawdown level the chance the bankroll EVER fell that far from its running peak."""
    rng = np.random.default_rng(seed)
    W, n = R.shape
    world_idx = rng.integers(0, W, size=n_paths)
    draw_idx = rng.integers(0, n, size=(n_paths, n_slips))
    returns = R[world_idx[:, None], draw_idx]                  # (paths x slips) return multiples
    pnl = stake_fraction * (returns - 1.0)                     # change in bankroll fraction per slip
    path = 1.0 + np.cumsum(pnl, axis=1)
    final = path[:, -1]
    peak = np.maximum.accumulate(np.concatenate([np.ones((n_paths, 1)), path], axis=1), axis=1)[:, 1:]
    dd = (peak - path) / np.maximum(peak, 1e-9)
    max_dd = dd.max(axis=1)
    ruined = (path <= 0).any(axis=1)
    return {
        "n_slips": n_slips, "stake_fraction": stake_fraction,
        "final_p05": float(np.percentile(final, 5)), "final_p25": float(np.percentile(final, 25)),
        "final_p50": float(np.percentile(final, 50)), "final_p75": float(np.percentile(final, 75)),
        "final_p95": float(np.percentile(final, 95)), "p_ahead": float((final > 1.0).mean()),
        "p_ruin": float(ruined.mean()),
        "p_drawdown": {float(lv): float((max_dd >= lv).mean()) for lv in drawdown_levels},
        "fan": {q: np.percentile(path, q, axis=0).tolist() for q in (5, 25, 50, 75, 95)},
    }


def breakeven_leg_prob(multiple: float, k: int) -> Optional[float]:
    """For an all-or-nothing entry paying `multiple`x on k legs: the per-leg hit probability at
    which EV is exactly zero (independent legs) = multiple ** (-1/k). None if not computable."""
    if multiple is None or multiple <= 1 or k < 1:
        return None
    return float(multiple ** (-1.0 / k))
