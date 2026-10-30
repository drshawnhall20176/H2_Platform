"""
model_tuning.py — the adjustments approved on the Postgame Review page, as multipliers the props models apply.

factor(sport, market, slot) = (the market-wide multiplier) x (the slot's own, if one was approved). 1.0 when nothing
is approved or the store can't be read. Read once and kept 10 minutes per process (approving one clears it).
"""
from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

CACHE_S = 600
FACTOR_RANGE = (0.80, 1.20)          # an approved multiplier can never move a projection more than 20%
_cache: Dict = {"at": 0.0, "map": {}}


def clear_cache() -> None:
    _cache["at"] = 0.0
    _cache["map"] = {}


def _load() -> Dict[Tuple[str, str, str], float]:
    if time.time() - _cache["at"] < CACHE_S:
        return _cache["map"]
    out: Dict[Tuple[str, str, str], float] = {}
    try:
        import model_store as MS
        for t in MS.list_tuning():
            lo, hi = FACTOR_RANGE
            out[(t["sport"], t["market"], t.get("slot") or "")] = max(lo, min(hi, float(t["factor"])))
    except Exception:                                           # noqa: BLE001
        out = {}
    _cache["map"], _cache["at"] = out, time.time()
    return out


def factor(sport: str, market: str, slot: Optional[str] = "") -> float:
    m = _load()
    if not m:
        return 1.0
    f = m.get((sport, market, ""), 1.0)
    if slot:
        f *= m.get((sport, market, str(slot)), 1.0)
    return f
