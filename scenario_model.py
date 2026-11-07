"""
scenario_model.py — how a game is likely to go before it starts: favorite blows it open / middle / close / underdog
blows it open, from the line AND the matchup (Nov 7).

The Game Script page started with a fixed table: the four scenario chances by the size of the spread alone. This
model adds what the teams have shown this season, every number computed only from games BEFORE the one predicted:

  strength      the spread (NHL: the favorite's no-vig moneyline chance, as a log-odds)
  volatility    how widely each team's own results swing (average margin SD of the two teams)
  blow_fav      how often the favorite has won by the blowout margin; blow_dog how often the underdog has lost by it
  close_rate    how often the two teams' games finish within the close margin
  sos_gap       the schedule-adjusted margin gap (each team's margins + its opponents' average margins) minus what the
                spread implies -- where the matchup says "bigger (or smaller) than the line"
  pace          the two teams' average combined score vs the league's
  rest          favorite / underdog playing on no rest (back-to-back); favorite at home

Fit as a 4-way multinomial logistic regression (numpy, L2-penalized), team histories shrunk toward the league for
small samples. research/scenario_study.py tests it against the spread-only table on games it wasn't fit on; the
nightly script-learn job refits it as games finish and keeps it only while it still beats the table on held-out
games (scenario_learn.py). Every prediction is logged before the game and graded after -- the track record.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

CLASSES = ("fav_blowout", "middle", "close", "dog_blowout")
FEATURES = ("strength", "volatility", "blow_fav", "blow_dog", "close_rate", "sos_gap", "pace", "fav_b2b", "dog_b2b",
            "fav_home")
SHRINK_GAMES = 6.0          # a team's rate counts as much as 6 league-average games until it has its own
MIN_SEASON_GAMES = 0


def label(fav_margin: float, close: float, blow: float) -> str:
    if fav_margin >= blow:
        return "fav_blowout"
    if fav_margin <= -blow:
        return "dog_blowout"
    if abs(fav_margin) <= close:
        return "close"
    return "middle"


def _d(x) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


# ---------------------------------------------------------------- team histories (as-of)
class History:
    """Per-team results in date order. add() after a game is final; features() reads only earlier games."""

    def __init__(self):
        self.games: Dict[str, List[Tuple[date, float, float, str]]] = defaultdict(list)   # team -> (day, margin, total, opp)
        self._lg: Dict = {}

    def add(self, day, home: str, away: str, home_score: float, away_score: float) -> None:
        dd = _d(day)
        self._lg = {}
        self.games[str(home)].append((dd, home_score - away_score, home_score + away_score, str(away)))
        self.games[str(away)].append((dd, away_score - home_score, home_score + away_score, str(home)))

    def before(self, team: str, day) -> List[Tuple[date, float, float, str]]:
        dd = _d(day)
        return [g for g in self.games.get(str(team), []) if g[0] < dd]

    def league(self, day, season_start=None) -> Dict[str, float]:
        """League-wide reference numbers from games before `day` (this season when season_start is given)."""
        dd = _d(day)
        lo = _d(season_start) if season_start else date.min
        if (dd, lo) in self._lg:
            return self._lg[(dd, lo)]
        m, t = [], []
        seen = set()
        for team, gs in self.games.items():
            for g in gs:
                if lo <= g[0] < dd and g[1] >= 0:               # each game once (the winner's row)
                    key = (g[0], team, g[3])
                    if key not in seen:
                        seen.add(key)
                        m.append(g[1])
                        t.append(g[2])
        if len(m) < 20:
            out = {}
        else:
            absm = np.abs(np.array(m))
            out = {"sd": float(np.sqrt(np.mean(np.array(m) ** 2))), "total": float(np.mean(t)), "n": len(m), "absm": absm}
        self._lg[(dd, lo)] = out
        return out


def _shrunk(vals: Sequence[float], prior: float, k: float = SHRINK_GAMES) -> float:
    n = len(vals)
    return (sum(vals) + k * prior) / (n + k)


def features(hist: History, day, fav: str, dog: str, fav_home: bool, strength: float, sport_kind: str,
             close: float, blow: float, season_start=None, margin_per_strength: float = 1.0) -> Optional[Dict[str, float]]:
    """The feature vector for one game, from games before `day` only. strength: the spread (positive) or, for
    hockey, the favorite's chance."""
    lg = hist.league(day, season_start)
    if not lg:
        return None
    lo = _d(season_start) if season_start else date.min
    hf = [g for g in hist.before(fav, day) if g[0] >= lo]
    hd = [g for g in hist.before(dog, day) if g[0] >= lo]
    absm = lg["absm"]
    p_blow = float(np.mean(absm >= blow)) / 2 + 1e-3             # a team's chance of winning (or losing) by `blow`
    p_close = float(np.mean(absm <= close))

    def sd(gs):
        return math.sqrt(_shrunk([g[1] ** 2 for g in gs], lg["sd"] ** 2))

    def net(gs):
        return _shrunk([g[1] for g in gs], 0.0)

    def opp_net(gs):
        return _shrunk([net(hist.before(g[3], g[0])) for g in gs], 0.0)

    if sport_kind == "ml":
        p = min(0.95, max(0.5, float(strength)))
        s = math.log(p / (1 - p))
        implied = s * margin_per_strength
    else:
        s = abs(float(strength))
        implied = s
    adj_gap = (net(hf) + opp_net(hf)) - (net(hd) + opp_net(hd))
    last_f = hf[-1][0] if hf else None
    last_d = hd[-1][0] if hd else None
    dd = _d(day)
    return {
        "strength": s,
        "volatility": (sd(hf) + sd(hd)) / 2 / max(lg["sd"], 1e-6),
        "blow_fav": _shrunk([1.0 if g[1] >= blow else 0.0 for g in hf], p_blow) / p_blow,
        "blow_dog": _shrunk([1.0 if g[1] <= -blow else 0.0 for g in hd], p_blow) / p_blow,
        "close_rate": (_shrunk([1.0 if abs(g[1]) <= close else 0.0 for g in hf], p_close)
                       + _shrunk([1.0 if abs(g[1]) <= close else 0.0 for g in hd], p_close)) / 2 / max(p_close, 1e-3),
        "sos_gap": (adj_gap - implied) / max(lg["sd"], 1e-6),
        "pace": ((_shrunk([g[2] for g in hf], lg["total"]) + _shrunk([g[2] for g in hd], lg["total"])) / 2
                 / max(lg["total"], 1e-6)) - 1.0,
        "fav_b2b": 1.0 if last_f and (dd - last_f).days <= 1 else 0.0,
        "dog_b2b": 1.0 if last_d and (dd - last_d).days <= 1 else 0.0,
        "fav_home": 1.0 if fav_home else 0.0,
    }


# ---------------------------------------------------------------- multinomial logistic regression
def _softmax(z):
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def fit(X: Sequence[Dict[str, float]], y: Sequence[str], feats: Sequence[str] = FEATURES, l2: float = 1.0,
        iters: int = 3000, lr: float = 0.3) -> Dict:
    A = np.array([[x[f] for f in feats] for x in X], dtype=float)
    mu, sd = A.mean(axis=0), A.std(axis=0)
    sd[sd < 1e-9] = 1.0
    Z = (A - mu) / sd
    Y = np.zeros((len(y), len(CLASSES)))
    for i, c in enumerate(y):
        Y[i, CLASSES.index(c)] = 1
    n, k = Z.shape
    W, b = np.zeros((k, len(CLASSES))), np.log(Y.mean(axis=0) + 1e-6)
    for _ in range(iters):
        P = _softmax(Z @ W + b)
        G = P - Y
        W -= lr * (Z.T @ G / n + l2 * W / n)
        b -= lr * G.mean(axis=0)
    return {"feats": list(feats), "mu": mu.tolist(), "sd": sd.tolist(), "W": W.tolist(), "b": b.tolist(), "n": n}


def predict(model: Dict, x: Dict[str, float]) -> Dict[str, float]:
    A = np.array([[x[f] for f in model["feats"]]], dtype=float)
    Z = (A - np.array(model["mu"])) / np.array(model["sd"])
    P = _softmax(Z @ np.array(model["W"]) + np.array(model["b"]))[0]
    return {c: float(p) for c, p in zip(CLASSES, P)}


def log_loss(probs: Sequence[Dict[str, float]], y: Sequence[str]) -> float:
    return float(-np.mean([math.log(max(p[c], 1e-9)) for p, c in zip(probs, y)]))


def brier(probs: Sequence[Dict[str, float]], y: Sequence[str]) -> float:
    return float(np.mean([sum((p[c] - (1.0 if c == t else 0.0)) ** 2 for c in CLASSES) for p, t in zip(probs, y)]))


def drivers(model: Dict, x: Dict[str, float], top: int = 3) -> List[Tuple[str, str, float]]:
    """The features pushing this game toward (or away from) a favorite blowout and a close game, biggest first:
    [(feature, scenario, push in log-odds vs the average game)]."""
    W = np.array(model["W"])
    out = []
    for i, f in enumerate(model["feats"]):
        z = (x[f] - model["mu"][i]) / model["sd"][i]
        for c in ("fav_blowout", "close"):
            j = CLASSES.index(c)
            push = z * (W[i, j] - W[i].mean())
            out.append((f, c, float(push)))
    out.sort(key=lambda t: -abs(t[2]))
    seen, res = set(), []
    for f, c, p in out:
        if f not in seen and abs(p) >= 0.05:
            seen.add(f)
            res.append((f, c, p))
        if len(res) >= top:
            break
    return res


FEATURE_TEXT = {"strength": "the line", "volatility": "how widely these teams' results swing",
                "blow_fav": "the favorite's blowout wins this season", "blow_dog": "the underdog's blowout losses this season",
                "close_rate": "how often their games stay close", "sos_gap": "schedule-adjusted gap vs the line",
                "pace": "pace (combined scoring)", "fav_b2b": "favorite on a back-to-back",
                "dog_b2b": "underdog on a back-to-back", "fav_home": "favorite at home"}
