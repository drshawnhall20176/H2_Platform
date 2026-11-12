"""
tennis_calibration.py — keeps the Tennis Lab's match chances honest (Nov 12).

Owner, after a losing morning on tennis favourites: yes, correct it automatically. Over the last month the model's
favourite won 64% of the time against the 69% it said; 70-80% favourites won only ~60%. So the chance is pulled
toward 50%:  p' = 0.5 + k x (p - 0.5).

Every morning (daily_review) k is refitted on every graded match (best log-loss over a grid), and the new k is used
only if it also beats the k in use on days it never saw: walk forward through the later half of the match days, fit
on the days before each, score both on that day -- it must win on 2 of every 3 such days and overall, the same rule
as the other sports' automatic calibration. Retirements and walkovers are left out (the books void them).

Records saved after Nov 12 keep the raw chance in `model_p_raw`; older ones only have the raw chance as `model_p`.

Nov 12 (owner: every module gets the tennis updates): the same fit and held-out rule runs for every Game Lab and
International Hoops league (sport=...), each with its own setting `game_calibration:<LEAGUE>`; tennis keeps its key.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

KEY = "tennis_calibration"
GRID = [round(0.30 + 0.02 * i, 2) for i in range(46)]          # 0.30 .. 1.20
MIN_N = 100
MIN_DAYS = 6


def shrink(p: float, k: float) -> float:
    return min(0.99, max(0.01, 0.5 + k * (float(p) - 0.5)))


def key_for(sport: str = "TENNIS") -> str:
    return KEY if sport == "TENNIS" else f"game_calibration:{sport}"


def current_k(get=None, sport: str = "TENNIS") -> float:
    try:
        if get is None:
            import model_store as MS
            get = MS.get_setting
        v = get(key_for(sport))
        return float(v["k"]) if isinstance(v, dict) and v.get("k") else 1.0
    except Exception:                                           # noqa: BLE001
        return 1.0


def rows(picks: Sequence[Dict]) -> List[Dict]:
    """Graded matches: raw chance for the home player, whether home won, the day."""
    out = []
    for p in picks:
        if p.get("result") not in ("home", "away"):
            continue
        raw = p.get("model_p_raw", p.get("model_p"))
        if raw is None:
            continue
        out.append({"p": float(raw), "y": 1.0 if p["result"] == "home" else 0.0, "day": str(p.get("kickoff"))[:10]})
    return out


def _ll(rs: Sequence[Dict], k: float) -> float:
    s = 0.0
    for r in rs:
        q = shrink(r["p"], k)
        s -= r["y"] * math.log(q) + (1 - r["y"]) * math.log(1 - q)
    return s / max(len(rs), 1)


def fit(rs: Sequence[Dict]) -> float:
    return min(GRID, key=lambda k: _ll(rs, k))


def holdout(rs: Sequence[Dict], k_now: float) -> Dict:
    days = sorted({r["day"] for r in rs})
    splits = passed = 0
    gain = 0.0
    for i in range(max(1, len(days) // 2), len(days)):
        train = [r for r in rs if r["day"] < days[i]]
        test = [r for r in rs if r["day"] == days[i]]
        if len(train) < 30 or not test:
            continue
        kf = fit(train)
        g = (_ll(test, k_now) - _ll(test, kf)) * len(test)
        splits += 1
        passed += g >= 0
        gain += g
    return {"splits": splits, "passed": passed, "gain": round(gain, 3)}


def auto(picks: Optional[Sequence[Dict]] = None, write: bool = True, get=None, save=None, sport: str = "TENNIS") -> Dict:
    """Refit k; apply it when it holds up out of sample. Returns the decision in the calibration report's shape."""
    import model_store as MS
    get = get or MS.get_setting
    save = save or MS.save_setting
    key = key_for(sport)
    picks = MS.load_game_picks(sport) if picks is None else picks
    rs = rows(picks)
    k_now = current_k(get, sport)
    out = {"side": "overall", "active": k_now, "new": k_now, "applied": False, "n": len(rs),
           "label": "win chances" if sport == "TENNIS" else f"{sport} win chances"}
    days = len({r["day"] for r in rs})
    if len(rs) < MIN_N or days < MIN_DAYS:
        out["why"] = f"not enough yet ({len(rs)} graded matches over {days} days; needs {MIN_N} over {MIN_DAYS})"
        return out
    k_new = fit(rs)
    out["new"] = k_new
    if abs(k_new - k_now) < 0.03:
        out["why"] = f"{k_now:.2f} still fits ({len(rs)} matches)"
        return out
    h = holdout(rs, k_now)
    ok = h["splits"] >= 3 and h["passed"] >= (2 / 3) * h["splits"] and h["gain"] > 0
    if not ok:
        out["why"] = f"{k_new:.2f} fits the past but didn't hold up on held-out days ({h['passed']} of {h['splits']})"
        return out
    out["applied"] = True
    out["why"] = (f"held up on {h['passed']} of {h['splits']} held-out days; a model 75% now reads "
                  f"{shrink(0.75, k_new):.0%}")
    if write:
        prev = get(key) if isinstance(get(key), dict) else {}
        hist = list((prev or {}).get("history") or [])[-20:]
        hist.append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "k": k_new, "from": k_now,
                     "n": len(rs), "holdout": h})
        save(key, {"k": k_new, "history": hist})
    return out
