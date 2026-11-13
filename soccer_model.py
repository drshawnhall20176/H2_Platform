"""
soccer_model.py — a goals model for soccer (Nov 13).

Owner: add soccer, domestic and international — match result, totals, Asian handicap and player props.

Model (Dixon & Coles 1997, the standard for soccer): each side's goals are Poisson with
    home goals ~ Poisson(base x home_adv x attack[home] x defense[away])
    away goals ~ Poisson(base x attack[away] x defense[home])
attack > 1 scores more than average, defense > 1 concedes more. Fitted on recent results, each weighted by
0.5 ** (age_days / HALF_LIFE), with PRIOR_GAMES of average-team results mixed in so a team with few games stays near
average. Low scores get the Dixon-Coles correction (0-0 and 1-1 a little likelier, 1-0 / 0-1 a little less).

From the score grid: 1X2, over/under any line (quarter lines split into two half-stakes), both teams to score, and
Asian handicap win / push / loss for any line. Pure numpy; no network here (data loading lives with the callers).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

HALF_LIFE = 240.0        # days; a result 8 months old counts half
PRIOR_GAMES = 4.0        # average-team pseudo-games per side
RHO = -0.10              # Dixon-Coles low-score correction (typical fitted value)
MAX_GOALS = 10
ITERS = 60


def _days(a, b) -> float:
    return abs((a - b).total_seconds()) / 86400.0


def fit(matches: Sequence[Dict], as_of: Optional[datetime] = None, half_life: float = HALF_LIFE,
        prior: float = PRIOR_GAMES) -> Dict:
    """matches: [{"home", "away", "hg", "ag", "date": datetime, "neutral"?}]. Only matches before `as_of` are used.
    Returns {"base", "home_adv", "attack": {team: x}, "defense": {team: x}, "n": {team: weighted games}}."""
    as_of = as_of or datetime.now(timezone.utc)
    ms = [m for m in matches if m["date"] < as_of and m.get("hg") is not None and m.get("ag") is not None]
    if not ms:
        return {"base": 1.35, "home_adv": 1.2, "attack": {}, "defense": {}, "n": {}}
    teams = sorted({m["home"] for m in ms} | {m["away"] for m in ms})
    ix = {t: i for i, t in enumerate(teams)}
    h = np.array([ix[m["home"]] for m in ms])
    a = np.array([ix[m["away"]] for m in ms])
    hg = np.array([float(m["hg"]) for m in ms])
    ag = np.array([float(m["ag"]) for m in ms])
    w = np.array([0.5 ** (_days(as_of, m["date"]) / half_life) for m in ms])
    neu = np.array([1.0 if m.get("neutral") else 0.0 for m in ms])
    n = len(teams)
    att, dfn = np.ones(n), np.ones(n)
    base = max(0.3, float((w * (hg + ag)).sum() / (2 * w.sum())))
    hadv = 1.2
    for _ in range(ITERS):
        ha = np.where(neu > 0, 1.0, hadv)
        lam_h = base * ha * att[h] * dfn[a]
        lam_a = base * att[a] * dfn[h]
        # attack: goals scored / expected-if-attack-were-1 (+ prior games at average)
        num = np.bincount(h, w * hg, n) + np.bincount(a, w * ag, n) + prior * base
        den = np.bincount(h, w * lam_h / att[h], n) + np.bincount(a, w * lam_a / att[a], n) + prior * base
        att = num / den
        lam_h = base * ha * att[h] * dfn[a]
        lam_a = base * att[a] * dfn[h]
        num = np.bincount(a, w * hg, n) + np.bincount(h, w * ag, n) + prior * base
        den = np.bincount(a, w * lam_h / dfn[a], n) + np.bincount(h, w * lam_a / dfn[h], n) + prior * base
        dfn = num / den
        att /= math.exp(np.log(att).mean())
        dfn /= math.exp(np.log(dfn).mean())
        lam_h = base * ha * att[h] * dfn[a]
        lam_a = base * att[a] * dfn[h]
        nh = neu == 0
        if nh.any():
            hadv = max(0.9, min(1.6, float((w[nh] * hg[nh]).sum() / max((w[nh] * lam_h[nh] / ha[nh]).sum(), 1e-9))))
        base = float((w * (hg + ag)).sum() / max((w * (lam_h + lam_a) / base).sum(), 1e-9))
    games = np.bincount(h, w, n) + np.bincount(a, w, n)
    return {"base": base, "home_adv": hadv, "attack": dict(zip(teams, att.round(4))),
            "defense": dict(zip(teams, dfn.round(4))), "n": dict(zip(teams, games.round(2)))}


def rates(r: Dict, home: str, away: str, neutral: bool = False) -> Optional[Tuple[float, float]]:
    """Expected goals (home, away); None when either team is unknown."""
    if home not in r["attack"] or away not in r["attack"]:
        return None
    ha = 1.0 if neutral else r["home_adv"]
    return (r["base"] * ha * r["attack"][home] * r["defense"][away],
            r["base"] * r["attack"][away] * r["defense"][home])


def _pois(lam: float) -> np.ndarray:
    k = np.arange(MAX_GOALS + 1)
    p = np.exp(-lam) * lam ** k / np.array([math.factorial(int(i)) for i in k])
    return p


def grid(lh: float, la: float, rho: float = RHO) -> np.ndarray:
    """P[home goals = i, away goals = j], Dixon-Coles corrected, normalised."""
    g = np.outer(_pois(lh), _pois(la))
    g[0, 0] *= 1 - lh * la * rho
    g[0, 1] *= 1 + lh * rho
    g[1, 0] *= 1 + la * rho
    g[1, 1] *= 1 - rho
    g = np.clip(g, 0, None)
    return g / g.sum()


def one_x_two(g: np.ndarray) -> Tuple[float, float, float]:
    return float(np.tril(g, -1).sum()), float(np.trace(g)), float(np.triu(g, 1).sum())


def btts(g: np.ndarray) -> float:
    return float(g[1:, 1:].sum())


def _diff_total(g: np.ndarray):
    i, j = np.indices(g.shape)
    return i - j, i + j


def _half_lines(line: float) -> List[float]:
    """A quarter line (2.25, -0.75 ...) is two half-stakes on the neighbouring lines."""
    q = round(line * 4) / 4
    if abs(q * 2 - round(q * 2)) > 1e-9:            # .25 / .75
        return [q - 0.25, q + 0.25]
    return [q]


def total_outcome(g: np.ndarray, line: float, side: str = "over") -> Dict[str, float]:
    """Win / push / loss chances (half-stakes averaged for quarter lines) for over/under `line`."""
    _, tot = _diff_total(g)
    out = {"win": 0.0, "push": 0.0, "loss": 0.0}
    parts = _half_lines(line)
    for L in parts:
        over, push = float(g[tot > L].sum()), float(g[tot == L].sum())
        under = 1 - over - push
        win, loss = (over, under) if side == "over" else (under, over)
        out["win"] += win / len(parts)
        out["push"] += push / len(parts)
        out["loss"] += loss / len(parts)
    return out


def handicap_outcome(g: np.ndarray, line: float, side: str = "home") -> Dict[str, float]:
    """Asian handicap: `line` is the handicap on `side` (home -0.5 = home must win). Win / push / loss chances."""
    d, _ = _diff_total(g)
    if side == "away":
        d = -d
    out = {"win": 0.0, "push": 0.0, "loss": 0.0}
    parts = _half_lines(line)
    for L in parts:
        adj = d + L
        out["win"] += float(g[adj > 0].sum()) / len(parts)
        out["push"] += float(g[adj == 0].sum()) / len(parts)
        out["loss"] += float(g[adj < 0].sum()) / len(parts)
    return out


def ev(outcome: Dict[str, float], decimal_odds: float) -> float:
    """Expected profit per 1 staked (pushes return the stake)."""
    return outcome["win"] * (decimal_odds - 1) - outcome["loss"]


def fair_decimal(p: float) -> Optional[float]:
    return None if p <= 0 else 1 / p


def to_decimal(american: float) -> float:
    a = float(american)
    return 1 + (a / 100 if a > 0 else 100 / -a)


def to_american(decimal: float) -> Optional[int]:
    if decimal is None or decimal <= 1:
        return None
    return int(round((decimal - 1) * 100)) if decimal >= 2 else int(round(-100 / (decimal - 1)))


def devig(prices: Sequence[float]) -> List[float]:
    """Decimal prices of one market's outcomes -> no-vig chances (proportional)."""
    inv = [1 / p for p in prices]
    s = sum(inv)
    return [x / s for x in inv]


def read(r: Dict, home: str, away: str, neutral: bool = False) -> Optional[Dict]:
    """Everything the page shows for one match."""
    lam = rates(r, home, away, neutral)
    if lam is None:
        return None
    g = grid(*lam)
    ph, pd, pa = one_x_two(g)
    return {"xg_home": round(lam[0], 2), "xg_away": round(lam[1], 2), "p_home": round(ph, 4), "p_draw": round(pd, 4),
            "p_away": round(pa, 4), "p_btts": round(btts(g), 4),
            "p_over25": round(total_outcome(g, 2.5)["win"], 4), "grid": g}
