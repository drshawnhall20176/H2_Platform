"""
clv.py -- closing-line value for the model's own reads (Nov 18).

Wins and losses need hundreds of bets to tell skill from luck; whether the market moved TOWARD a read between the time
it was shown and kickoff tells within a few dozen (the books' closing price is the sharpest number there is). Each saved
prop keeps the first time it carried a bet tag (model_store "bet_" columns) and its last pre-game view; this compares
the two for the bet tag's side:
  * the line moved our way (Over: line went up; Under: line went down)        -> beat
  * same line, the no-vig chance of our side rose by 1 point or more          -> beat
  * the opposite                                                              -> lost
  * otherwise                                                                 -> same
Owner: "data in is the determinant ... make sure nothing is being excluded or missed."
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, Optional

PROB_STEP = 0.01


def _imp(a) -> Optional[float]:
    try:
        a = float(a)
    except (TypeError, ValueError):
        return None
    if -100 < a < 100:
        return None
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def _nv(side: str, over, under) -> Optional[float]:
    o, u = _imp(over), _imp(under)
    if o is None or u is None:
        return None
    p = o / (o + u)
    return p if side == "Over" else 1 - p


def of(row: Dict, entry: str = "bet") -> Optional[Dict]:
    """{"result": beat/lost/same, "line_move" (points our way), "prob_move" (no-vig chance change of our side, same line
    only), "tag"} for one saved prop, from its `entry` snapshot ("bet" or "first") to its last pre-game view."""
    ts0, ts1 = row.get(f"{entry}_ts"), row.get("ts")
    if not ts0 or not ts1 or str(ts0) >= str(ts1) or row.get(f"{entry}_line") is None or row.get("line") is None:
        return None
    side = row.get(f"{entry}_side") or "Over"
    l0, l1 = float(row[f"{entry}_line"]), float(row["line"])
    move = (l1 - l0) if side == "Over" else (l0 - l1)
    out = {"tag": row.get(f"{entry}_use_tag"), "side": side, "line_move": move, "prob_move": None}
    if move > 0:
        out["result"] = "beat"
    elif move < 0:
        out["result"] = "lost"
    else:
        p0 = _nv(side, row.get(f"{entry}_over_price"), row.get(f"{entry}_under_price"))
        p1 = _nv(side, row.get("over_price"), row.get("under_price"))
        if p0 is None or p1 is None:
            out["result"] = "same"
        else:
            out["prob_move"] = p1 - p0
            out["result"] = "beat" if p1 - p0 >= PROB_STEP else "lost" if p0 - p1 >= PROB_STEP else "same"
    return out


def record(rows: Iterable[Dict], entry: str = "bet", key=lambda c, r: c["tag"]) -> Dict[str, Dict]:
    """{group: {"beat", "lost", "same", "n", "beat_rate" (of those that moved)}} -- grouped by the entry tag."""
    import props_engine as PE
    agg: Dict[str, Dict] = defaultdict(lambda: {"beat": 0, "lost": 0, "same": 0, "n": 0})
    for r in rows:
        c = of(r, entry)
        if c is None:
            continue
        c["tag"] = PE.norm_use(c["tag"]) if c.get("tag") else c.get("tag")
        a = agg[key(c, r)]
        a[c["result"]] += 1
        a["n"] += 1
    for a in agg.values():
        moved = a["beat"] + a["lost"]
        a["beat_rate"] = a["beat"] / moved if moved else None
    return dict(agg)
