"""
props_money.py — the Money Score for player props (Nov 20).

The game-line Money Score (money_score.py) for props: the expected return per $1 at the price, from a chance that
starts at the books' no-vig chance and adds the model's disagreement only as far as its record has earned --

    logit P(over) = a + b * logit(books' no-vig over) + c * (logit(model's own over) - logit(books' no-vig over))

fit per sport x market (a sport-wide fit for markets with under MIN_FIT graded reads), pulled toward trusting the books,
refit each morning on the last WINDOW_DAYS of graded reads (`python props_money.py fit`).

research/money_score_props.py, walk-forward (each day scored by a fit on earlier days only), Oct 6 - Nov 19:
  NBA, scoring +4% to +12% with a 40%+ chance: 1,131 reads, hit 54.1%, +3.5% per $1 (halves +6.8% / +0.3%);
  NHL 271, +4.2% (+16.5% / -8.1%, unstable); NFL 53, -7.7%. The +4% to +7% NBA band was the steadiest (+6.3%, 713).
Shown as INFORMATION beside the 💰 rule (Best Bets' "Money score" column) until it has a live record of its own
(research/money_score_props.py re-run on the live weekend decides whether it replaces the rule).
"""
from __future__ import annotations

import math
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

KEY = "money_score:props"
SPORTS = ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB")
MIN_FIT = 300
WINDOW_DAYS = 45
_CACHE: Dict[str, object] = {}


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _sig(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def rows_from_graded(graded: Sequence[Dict]) -> List[Dict]:
    """[{market, pm, pmod, y}] over-oriented, from graded prop reads with both prices and both chances."""
    import props_engine as PE
    out = []
    for r in graded:
        if r.get("actual") is None or r.get("p_model") is None or r.get("p_market") is None or r.get("line") is None:
            continue
        if (r.get("book") or "") in PE.PICKEM_BOOKS or r.get("over_price") is None or r.get("under_price") is None:
            continue
        thr = PE.threshold(float(r["line"]))
        if r["actual"] == thr:
            continue
        out.append({"market": r.get("market"), "pm": float(r["p_market"]), "pmod": float(r["p_model"]),
                    "y": float(r["actual"] > thr)})
    return out


def fit_sport(rows: Sequence[Dict]) -> Dict[str, List[float]]:
    """{"_all": [a, b, c, n], market: [a, b, c, n]} -- per market where it has MIN_FIT reads."""
    import money_score as MSC
    out: Dict[str, List[float]] = {}
    if len(rows) >= MIN_FIT:
        w = MSC.fit(rows, lam=3.0)
        if w:
            out["_all"] = w + [len(rows)]
    by: Dict[str, List[Dict]] = {}
    for r in rows:
        by.setdefault(r["market"], []).append(r)
    for m, rs in by.items():
        if len(rs) >= MIN_FIT:
            w = MSC.fit(rs, lam=3.0)
            if w:
                out[m] = w + [len(rs)]
    return out


def refit(save=None, grade=None) -> Dict:
    import props_engine as PE
    if grade is None:
        import daily_review as DR
        import model_store as MS
        since = (date.fromisoformat(PE._et_today()) - timedelta(days=WINDOW_DAYS)).isoformat()

        def grade(sp):
            g = DR.grade_dates(sp, [d for d in MS.snapshot_dates(sp) if d >= since])
            return [r for rs in g.values() for r in rs]
    coefs = {}
    for sp in SPORTS:
        try:
            c = fit_sport(rows_from_graded(grade(sp)))
        except Exception as exc:                                # noqa: BLE001 -- one sport never stops the rest
            print(f"{sp}: props money fit failed ({type(exc).__name__}: {exc})")
            continue
        if c:
            coefs[sp] = c
            a = c.get("_all")
            if a:
                print(f"{sp} props: a={a[0]:+.3f} books={a[1]:.3f} model disagreement={a[2]:+.3f} ({a[3]} reads), "
                      f"{len(c) - 1} markets with their own fit")
        else:
            print(f"{sp} props: under {MIN_FIT} graded reads — no score yet")
    rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "coefs": coefs}
    if save is None:
        import model_store as MS
        save = MS.save_setting
    save(KEY, rec)
    save(f"{KEY}:{PE._et_today()}", rec)
    _CACHE.clear()
    return rec


def coefs(get=None) -> Dict[str, Dict[str, List[float]]]:
    hit = _CACHE.get("v")
    if hit and time.time() - hit[0] < 600 and get is None:
        return hit[1]
    try:
        if get is None:
            import model_store as MS
            get = MS.get_setting
        c = (get(KEY, None) or {}).get("coefs") or {}
    except Exception:                                           # noqa: BLE001
        c = {}
    _CACHE["v"] = (time.time(), c)
    return c


def score(sport: str, market: str, side: str, p_model_side, p_market_side, price, w_by=None) -> Optional[float]:
    """Expected return per $1 at `price` for `side` (Over / Under), or None without a fit, chances or a price."""
    import props_engine as PE
    if side not in ("Over", "Under") or p_model_side is None or p_market_side is None or price is None:
        return None
    cf = (w_by if w_by is not None else coefs()).get(sport) or {}
    w = cf.get(market) or cf.get("_all")
    d = PE.decimal(price)
    if not w or not d:
        return None
    pm = float(p_market_side) if side == "Over" else 1 - float(p_market_side)
    pmod = float(p_model_side) if side == "Over" else 1 - float(p_model_side)
    po = _sig(w[0] + w[1] * _logit(pm) + w[2] * (_logit(pmod) - _logit(pm)))
    return (po if side == "Over" else 1 - po) * d - 1


def play_score(sport: str, p: Dict, w_by=None) -> Optional[float]:
    """score() for a board play (Best Bets row)."""
    if p.get("Pickem"):
        return None
    return score(sport, p.get("Market"), p.get("Side"), p.get("ModelRaw"), p.get("MarketProb"), p.get("RealPrice"),
                 w_by)


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if (argv[0] if argv else "fit") == "fit":
        refit()
        return 0
    print("usage: python props_money.py fit")
    return 2


if __name__ == "__main__":
    sys.exit(main())
