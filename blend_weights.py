"""
blend_weights.py — the owner-approved share of the vote the model gets against the books' no-vig line, per sport and
market (Nov 2). Fitted by the weekly tuning report (tuning_report.py); approved on Postgame Review or through the
approve-tuning workflow ({"blend:Points": 0.25}).

weight(sport, market, default) -> the approved weight, else `default` (props_engine.MODEL_WEIGHT). Read once and kept
10 minutes per process; approving or retiring one clears it. Never raises: a store problem means the default.
"""
from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

CACHE_S = 600
W_RANGE = (0.0, 0.6)          # the model can be turned down to nothing, but never above 60% of the vote
_cache: Dict = {"at": 0.0, "map": {}}


def clear_cache() -> None:
    _cache["at"] = 0.0
    _cache["map"] = {}


def _load() -> Dict[Tuple[str, str], float]:
    if time.time() - _cache["at"] < CACHE_S:
        return _cache["map"]
    out: Dict[Tuple[str, str], float] = {}
    try:
        import model_store as MS
        lo, hi = W_RANGE
        for b in MS.list_blend():
            out[(b["sport"], b["market"])] = max(lo, min(hi, float(b["w"])))
    except Exception:                                           # noqa: BLE001
        out = {}
    _cache["map"], _cache["at"] = out, time.time()
    return out


def weight(sport: Optional[str], market: Optional[str], default: float) -> float:
    if not sport or not market:
        return default
    return _load().get((sport, market), default)
