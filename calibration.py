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



# --------------------------------------------------------------------------- by side (Nov 5)
# The Nov 5 audit (research/calibration_audit.py, 2,479 NBA reads Oct 30 - Nov 4): the model's UNDER chances were
# honest (said 55%, hit 56%) but its OVER chances weren't (said 53%, hit 45%; Points 54% -> 41%, combos 53-57% ->
# 34-41%). One factor for both sides can't fix that, so each side gets its own. Held out (research/
# side_calibration_test.py, fit on earlier days, scored on later ones): the per-side version beat both "as shown" and
# one shared factor on log loss in every split, and the Overs it stopped calling singles had hit 46-50%.
# Applied to the model's P(over) before the lean, edge and Use tag are worked out (props_engine.read_line), so the
# chance shown, the value and the tags all move together. Owner-approved per sport on Postgame Review, like `s`.
SIDE_S_RANGE = (0.3, 1.0)


def _side_key(sport: Optional[str], side: str) -> str:
    return f"{sport or ''}:{side}"


def side_factors(sport: Optional[str]):
    """(s_over, s_under) approved for this sport; (1.0, 1.0) = no change."""
    factor(None)                                                # refreshes the shared cache when it's stale
    lo, hi = SIDE_S_RANGE
    m = _cache["map"]
    return (max(lo, min(hi, m.get(_side_key(sport, "Over"), 1.0))), max(lo, min(hi, m.get(_side_key(sport, "Under"), 1.0))))


def apply_side(p_over: Optional[float], factors) -> Optional[float]:
    """P(over) with the side factor of whichever side it favors pulled toward 50%."""
    if p_over is None or not factors:
        return p_over
    s_over, s_under = factors
    s = s_over if p_over > 0.5 else s_under
    return honest(p_over, s)


def fit_by_side(rows: Iterable[Dict]) -> Dict:
    """{"Over": fit, "Under": fit} -- the honest-chance factor for each side the model took (range 0.30-1.00)."""
    rows = list(rows)
    out = {}
    for side in ("Over", "Under"):
        data = usable([r for r in rows if (r.get("side") or "Over") == side])
        n = len(data)
        if n < MIN_N:
            out[side] = {"s": 1.0, "n": n, "enough": False}
            continue
        lo, hi = SIDE_S_RANGE
        grid = [round(lo + i * 0.01, 2) for i in range(int(round((hi - lo) / 0.01)) + 1)]
        best = min(grid, key=lambda g: _ll(data, g))
        out[side] = {"s": best, "n": n, "enough": True, "said": sum(p for p, _ in data) / n,
                     "hit": sum(y for _, y in data) / n, "log_loss": (round(_ll(data, 1.0), 4), round(_ll(data, best), 4))}
    return out


# --------------------------------------------------------------------------- learned nightly (Nov 8)
# The owner asked for a system that learns every day as picks reconcile, not one that waits for a study and a button.
# Each morning review (daily_review.review_sport) runs this on the last 30 days of graded reads: for each side, fit the
# factor that would have made the chances honest, then check it the way research/side_calibration_test.py does -- on
# every split, fit on the earlier days and score on the later ones. A change is applied only when it improves the held-out
# log loss in at least two thirds of the splits AND moves the factor by 0.03 or more; it can tighten (chances
# overconfident) or loosen back toward 1.00 (an earlier correction overshot). Every change is written with its evidence
# (calibration table, details.auto = true), shown in that morning's notes, and can be turned off on Postgame Review.
AUTO_MIN_ROWS = 300            # reads on that side in the window
AUTO_MIN_DATES = 3
AUTO_MIN_SPLITS = 2
AUTO_MIN_MOVE = 0.03
AUTO_SPLIT_PASS = 2 / 3
_REL_GRID = [round(0.5 + i * 0.01, 2) for i in range(101)]     # relative to the active factor: 0.50 .. 1.50


def _ll_rel(rows, s):
    tot = 0.0
    for r in rows:
        q = min(max(honest(r["p"], s), 1e-3), 1 - 1e-3)
        tot -= math.log(q) if r["y"] else math.log(1 - q)
    return tot / len(rows)


def held_out_side(rows: List[Dict]) -> Dict:
    """rows: [{"date", "p" (chance as graded, active factor already in it), "y"}] for ONE side.
    -> {"rel": fit on everything (relative to active), "splits": n, "passed": n, "gain": mean held-out improvement}."""
    ds = sorted({r["date"] for r in rows})
    out = {"rel": 1.0, "splits": 0, "passed": 0, "gain": 0.0, "n": len(rows), "dates": len(ds)}
    if len(rows) < 2 or not ds:
        return out
    out["rel"] = min(_REL_GRID, key=lambda g: _ll_rel(rows, g))
    gains = []
    for cut in ds[1:]:
        tr = [r for r in rows if r["date"] < cut]
        te = [r for r in rows if r["date"] >= cut]
        if len(tr) < 100 or len(te) < 100:
            continue
        s = min(_REL_GRID, key=lambda g: _ll_rel(tr, g))
        g = _ll_rel(te, 1.0) - _ll_rel(te, s)
        gains.append(g)
    out["splits"] = len(gains)
    out["passed"] = sum(1 for g in gains if g > 0)
    out["gain"] = sum(gains) / len(gains) if gains else 0.0
    return out


def auto_side(sport: str, graded_by_date: Dict[str, List[Dict]], morning: str, write: bool = True) -> List[Dict]:
    """Learn each side's factor from the window; apply what passes. Returns the decisions (applied or not, and why)."""
    rows = {"Over": [], "Under": []}
    for d, rs in graded_by_date.items():
        for r in rs:
            if r.get("result") not in ("hit", "miss") or r.get("market") in SKIP_MARKETS:
                continue
            try:
                p = float(r.get("chance"))
            except (TypeError, ValueError):
                continue
            if 0 < p < 1 and r.get("side") in rows:
                rows[r["side"]].append({"date": d, "p": p, "y": 1 if r["result"] == "hit" else 0})
    active = dict(zip(("Over", "Under"), side_factors(sport)))
    # A graded chance carries the factor that was active when its snapshot was taken, so a side is judged only on days
    # since its current factor went live -- otherwise a fresh correction would be applied again on top of itself.
    since = {}
    try:
        import model_store as MS
        for c in MS.list_calibration():
            if c["sport"] in (f"{sport}:Over", f"{sport}:Under"):
                since[c["sport"].split(":")[1]] = str(c.get("approved_ts") or "")[:10]
    except Exception:                                           # noqa: BLE001
        pass
    for side in rows:
        if since.get(side):
            rows[side] = [r for r in rows[side] if r["date"] >= since[side]]
    out = []
    lo, hi = SIDE_S_RANGE
    for side, rs in rows.items():
        h = held_out_side(rs)
        new = round(max(lo, min(hi, active[side] * h["rel"])), 2)
        dec = {"sport": sport, "side": side, "active": active[side], "new": new, **h, "applied": False,
               "since": since.get(side)}
        if h["n"] < AUTO_MIN_ROWS or h["dates"] < AUTO_MIN_DATES:
            dec["why"] = f"not enough yet ({h['n']} reads over {h['dates']} days)"
        elif h["splits"] < AUTO_MIN_SPLITS:
            dec["why"] = "not enough days to hold any out"
        elif abs(new - active[side]) < AUTO_MIN_MOVE:
            dec["why"] = f"already honest (best {new:.2f} vs active {active[side]:.2f})"
        elif h["passed"] < AUTO_SPLIT_PASS * h["splits"] or h["gain"] <= 0:
            dec["why"] = f"didn't hold up on held-out days ({h['passed']} of {h['splits']})"
        else:
            dec["why"] = f"held up on {h['passed']} of {h['splits']} held-out splits"
            if write:
                import model_store as MS
                dec["applied"] = MS.approve_calibration(f"{sport}:{side}", new, {
                    "auto": True, "morning": morning, "n": h["n"], "rel_fit": h["rel"], "splits": h["splits"],
                    "passed": h["passed"], "held_out_gain": round(h["gain"], 5), "was": active[side]})
        out.append(dec)
    return out


def auto_notes(decisions: List[Dict]) -> List[str]:
    notes = []
    for d in decisions:
        if d.get("applied"):
            way = "toward 50% (they ran overconfident)" if d["new"] < d["active"] else "back out (the last correction overshot)"
            notes.append(f"🤖 Learned overnight: {d['sport']} {d['side']} chances {d['active']:.2f} → {d['new']:.2f}, "
                         f"pulled {way}; {d['why']} ({d['n']} reads). Undo on Postgame Review.")
    return notes
