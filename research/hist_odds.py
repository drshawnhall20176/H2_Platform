"""research/hist_odds.py — historical odds snapshots from The Odds API, shared by the international backtests (Nov 3).

Each call returns the events not yet started at the snapshot time with every book's prices. Costs credits (10 per
market per region), so callers ask only for days with games. Read-only.
"""
from __future__ import annotations

import os
import statistics
import time
from typing import Dict, List, Optional

import requests

BASE = "https://api.the-odds-api.com/v4/historical/sports/{key}/odds"
_calls = {"n": 0, "credits": 0, "remaining": None}


def snapshot(key: str, iso: str, markets: str = "h2h,spreads,totals", regions: str = "us") -> List[Dict]:
    api = os.environ.get("ODDS_API_KEY")
    if not api:
        return []
    for attempt in range(3):
        try:
            r = requests.get(BASE.format(key=key), params={"apiKey": api, "regions": regions, "markets": markets,
                                                           "oddsFormat": "american", "date": iso}, timeout=40)
        except Exception:                                       # noqa: BLE001
            time.sleep(2)
            continue
        _calls["n"] += 1
        try:
            _calls["credits"] += int(r.headers.get("x-requests-last") or 0)
            _calls["remaining"] = r.headers.get("x-requests-remaining")
        except ValueError:
            pass
        if r.status_code == 429:
            time.sleep(2 + attempt * 2)
            continue
        if not r.ok:
            return []
        return (r.json() or {}).get("data") or []
    return []


def usage() -> str:
    return f"{_calls['n']} historical calls, {_calls['credits']} credits, {_calls['remaining']} remaining"


def implied(a) -> Optional[float]:
    try:
        a = float(a)
    except (TypeError, ValueError):
        return None
    if -100 < a < 100:
        return None
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def decimal(a) -> Optional[float]:
    try:
        a = float(a)
    except (TypeError, ValueError):
        return None
    return 1 + (a / 100 if a > 0 else 100 / -a) if abs(a) >= 100 else None


def h2h(ev: Dict, name: str) -> Dict:
    """For outcome `name` (exact outcome name as the event lists it): no-vig chance averaged over books, the best
    price and DraftKings' price."""
    fair, best, dk = [], None, None
    for b in ev.get("bookmakers") or []:
        for m in b.get("markets") or []:
            if m.get("key") != "h2h":
                continue
            oc = {o.get("name"): o.get("price") for o in m.get("outcomes") or []}
            if name not in oc or len(oc) != 2:
                continue
            other = next(v for k, v in oc.items() if k != name)
            pa, pb = implied(oc[name]), implied(other)
            if pa is None or pb is None:
                continue
            fair.append(pa / (pa + pb))
            if best is None or decimal(oc[name]) > decimal(best):
                best = oc[name]
            if b.get("key") == "draftkings":
                dk = oc[name]
    return {"fair": statistics.mean(fair) if fair else None, "best": best, "dk": dk, "books": len(fair)}


def line(ev: Dict, market: str, name: str) -> Optional[Dict]:
    """Consensus (median) point and the median price for outcome `name` ("Over"/"Under" or a team / player)."""
    pts, prices = [], []
    for b in ev.get("bookmakers") or []:
        for m in b.get("markets") or []:
            if m.get("key") != market:
                continue
            for o in m.get("outcomes") or []:
                if o.get("name") == name and o.get("point") is not None:
                    pts.append(float(o["point"]))
                    prices.append(float(o.get("price") or -110))
    if not pts:
        return None
    return {"point": statistics.median(pts), "price": statistics.median(prices), "books": len(pts)}
