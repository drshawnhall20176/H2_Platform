"""
analyst_calibration.py — does the model's stated chance need correcting, and by how much?

The Analyst Record showed the Desk's calls hitting well below the chance it stated (NFL: said 60%, hit 48%; MLB: said 58%,
hit 50%). This module measures that from the graded record and fits the simplest honest correction: a two-number curve
(Platt scaling) that maps a stated chance to the rate that chance has actually delivered, per sport.

It is tested before it is trusted. The correction is fitted on the OLDER graded calls only and scored on the most
recent ones it never saw, against the uncorrected number (Brier score: lower is better). A sport shows a corrected
chance only when it passed that test with enough calls. Nothing here changes a lock, a rule or a published number —
it is an extra number beside the stated one.

Pure functions over ledger rows (hit, model_prob, date, logged_at); no I/O.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional

MIN_TRAIN = 60            # graded calls needed to fit on
MIN_TEST = 30             # graded calls held back to test on
TEST_SHARE = 0.30         # the most recent share of graded calls (whole days) is the test set
MIN_IMPROVEMENT = 0.001   # the correction must beat the raw Brier score by at least this much on the unseen calls
RIDGE = 2.0               # pulls the fit toward "no correction" so a small sample can't swing it wildly
P_LO, P_HI = 0.02, 0.98


def _logit(p: float) -> float:
    p = min(max(p, P_LO), P_HI)
    return math.log(p / (1 - p))


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def usable(rows: Iterable[Dict]) -> List[Dict]:
    """Graded calls with a stated chance, oldest first."""
    g = [r for r in rows if r.get("hit") is not None and r.get("model_prob") is not None]
    return sorted(g, key=lambda r: (str(r.get("date") or ""), str(r.get("logged_at") or "")))


def fit(rows: Iterable[Dict], iters: int = 50) -> Optional[Dict]:
    """Platt curve {a, b, n}: corrected = sigmoid(a * logit(stated) + b). a = 1, b = 0 is "no correction". Newton steps on the
    log-loss with a small ridge toward (1, 0). None when there are no graded calls."""
    g = usable(rows)
    if not g:
        return None
    xs = [_logit(r["model_prob"]) for r in g]
    ys = [1.0 if r["hit"] else 0.0 for r in g]
    a, b = 1.0, 0.0
    for _ in range(iters):
        ga = RIDGE * (a - 1.0)
        gb = RIDGE * b
        haa, hab, hbb = RIDGE, 0.0, RIDGE
        for x, y in zip(xs, ys):
            p = _sigmoid(a * x + b)
            w = p * (1 - p)
            ga += (p - y) * x
            gb += (p - y)
            haa += w * x * x
            hab += w * x
            hbb += w
        det = haa * hbb - hab * hab
        if det <= 1e-12:
            break
        da = (hbb * ga - hab * gb) / det
        db = (haa * gb - hab * ga) / det
        a, b = a - da, b - db
        if abs(da) + abs(db) < 1e-9:
            break
    return {"a": a, "b": b, "n": len(g)}


def apply(model: Optional[Dict], p: Optional[float]) -> Optional[float]:
    """The corrected chance for a stated one; the stated one back when there is no model."""
    if p is None or not model:
        return p
    return min(max(_sigmoid(model["a"] * _logit(p) + model["b"]), 0.01), 0.99)


def _brier(rows: List[Dict], f) -> float:
    return sum((f(r["model_prob"]) - (1.0 if r["hit"] else 0.0)) ** 2 for r in rows) / len(rows)


def evaluate(rows: Iterable[Dict]) -> Dict:
    """Fit on the older calls, score on the newest. {"status": "ok" | "not_enough", n, n_train, n_test, brier_raw, brier_adj,
    helps, test_hit, test_stated, test_adjusted, model (fitted on ALL graded calls, for use going forward)}."""
    g = usable(rows)
    out: Dict = {"status": "not_enough", "n": len(g), "n_train": 0, "n_test": 0, "helps": False, "model": None}
    if not g:
        return out
    days = sorted({str(r.get("date") or "") for r in g})
    cut_n, cut_day = 0, None
    for d in reversed(days):                       # take whole days from the newest end until the test share is reached
        cut_n += sum(1 for r in g if str(r.get("date") or "") == d)
        cut_day = d
        if cut_n >= TEST_SHARE * len(g):
            break
    train = [r for r in g if str(r.get("date") or "") < cut_day]
    test = [r for r in g if str(r.get("date") or "") >= cut_day]
    out.update(n_train=len(train), n_test=len(test))
    if len(train) < MIN_TRAIN or len(test) < MIN_TEST:
        return out
    m = fit(train)
    raw = _brier(test, lambda p: p)
    adj = _brier(test, lambda p: apply(m, p))
    out.update(status="ok", brier_raw=raw, brier_adj=adj, helps=(raw - adj) >= MIN_IMPROVEMENT,
               test_hit=sum(1 for r in test if r["hit"]) / len(test),
               test_stated=sum(r["model_prob"] for r in test) / len(test),
               test_adjusted=sum(apply(m, r["model_prob"]) for r in test) / len(test),
               model=fit(g))
    return out


def corrected_for_sport(rows: Iterable[Dict]) -> Optional[Dict]:
    """The curve to USE going forward: only when the held-back test said it helps; otherwise None (show the stated chance
    alone rather than a correction that hasn't earned its place)."""
    ev = evaluate(rows)
    return ev["model"] if ev["status"] == "ok" and ev["helps"] else None


def examples(model: Optional[Dict], points=(0.5, 0.6, 0.7, 0.8)) -> Dict[float, float]:
    """What a few stated chances become under the curve, for the Record page."""
    return {p: apply(model, p) for p in points} if model else {}
