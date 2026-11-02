"""
calibration.py — how honest the model's chances have been, per sport (Nov 2: the "juice factor").

The graded reads show the blended chance runs a little optimistic (NFL reads priced 55-60% hit about half the time).
A ticket priced off inflated chances overstates itself every leg, so ticket math uses an HONEST chance:

    honest = 0.5 + s * (chance - 0.5)          s in [0.5, 1.0]; 1.0 = trust the chance as shown

fit() picks the s that best matches what actually happened (lowest log loss) on the graded reads of the last
TREND_DAYS; daily_review.py refits it every morning and stores it in the report. Nothing changes until an owner
approves an s (model_store.approve_calibration -- Postgame Review shows the before/after); factor() reads the
approved one. Scorer props (Anytime TD, goals) are left out: a 28% "Yes" isn't a lean pulled toward 50%.
"""
from __future__ import annotations

import math
import time
from typing import Dict, Iterable, List, Optional

SKIP_MARKETS = ("Anytime TD", "1st TD", "Last TD", "Goals")
MIN_N = 150
S_RANGE = (0.5, 1.0)
BUCKETS = ((0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 1.01))
CACHE_S = 300
_cache: Dict = {"at": 0.0, "map": {}}


def honest(p: Optional[float], s: float = 1.0) -> Optional[float]:
    if p is None:
        return None
    return min(max(0.5 + s * (float(p) - 0.5), 0.001), 0.999)


def _ll(rows, s):
    tot = 0.0
    for p, y in rows:
        q = honest(p, s)
        tot -= math.log(q) if y else math.log(1 - q)
    return tot / len(rows)


def usable(rows: Iterable[Dict]) -> List[tuple]:
    """(chance of the read's side, hit 0/1) for graded, non-scorer reads."""
    out = []
    for r in rows:
        if r.get("result") not in ("hit", "miss") or r.get("market") in SKIP_MARKETS:
            continue
        try:
            p = float(r.get("chance"))
        except (TypeError, ValueError):
            continue
        if 0.0 < p < 1.0:
            out.append((p, 1 if r["result"] == "hit" else 0))
    return out


def fit(rows: Iterable[Dict]) -> Dict:
    """{"s", "n", "log_loss": (before, after), "brier": (before, after), "buckets": [...] , "enough": bool}."""
    data = usable(rows)
    n = len(data)
    if not n:
        return {"s": 1.0, "n": 0, "enough": False, "buckets": []}
    lo, hi = S_RANGE
    grid = [round(lo + i * 0.01, 2) for i in range(int(round((hi - lo) / 0.01)) + 1)]
    s = min(grid, key=lambda g: _ll(data, g)) if n >= MIN_N else 1.0
    brier = lambda g: sum((honest(p, g) - y) ** 2 for p, y in data) / n
    lean = [(p, y) if p >= 0.5 else (1 - p, 1 - y) for p, y in data]     # each read on its favored side
    buckets = []
    for b_lo, b_hi in BUCKETS:
        g = [(p, y) for p, y in lean if b_lo <= p < b_hi]
        if g:
            buckets.append({"range": f"{b_lo:.0%}–{min(b_hi, 1):.0%}", "n": len(g),
                            "shown": sum(p for p, _ in g) / len(g),
                            "honest": sum(honest(p, s) for p, _ in g) / len(g),
                            "hit": sum(y for _, y in g) / len(g)})
    return {"s": s, "n": n, "enough": n >= MIN_N, "log_loss": (round(_ll(data, 1.0), 4), round(_ll(data, s), 4)),
            "brier": (round(brier(1.0), 4), round(brier(s), 4)), "buckets": buckets}


def clear_cache() -> None:
    _cache["at"] = 0.0
    _cache["map"] = {}


def factor(sport: Optional[str]) -> float:
    """The owner-approved s for this sport; 1.0 (no change) until one is approved or when the store can't be read."""
    if time.time() - _cache["at"] > CACHE_S:
        try:
            import model_store as MS
            _cache["map"] = {c["sport"]: float(c["s"]) for c in MS.list_calibration()}
        except Exception:                                       # noqa: BLE001
            _cache["map"] = {}
        _cache["at"] = time.time()
    lo, hi = S_RANGE
    return max(lo, min(hi, _cache["map"].get(sport or "", 1.0)))


def chance(sport: Optional[str], p: Optional[float], market: Optional[str] = None) -> Optional[float]:
    """The honest chance of one leg for ticket math (scorer props pass through unchanged)."""
    if p is None or market in SKIP_MARKETS:
        return p
    return honest(p, factor(sport))
