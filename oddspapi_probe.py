"""
oddspapi_probe.py -- what OddsPapi's free tier actually returns for UFC (Nov 27). A one-off check, run by hand.

Owner, Nov 27: trying OddsPapi's free tier for UFC props (The Odds API carries fight winner and a few totals; the
SportsGameOdds free tier doesn't include UFC). This reads OddsPapi's MMA market list (sportId 20), the UFC fights of the
next 10 days that have odds, and the odds for up to LIMIT of them, then prints the market names, how many fights carry
each, which books post them -- DraftKings first -- and one fight's DraftKings prices. Never prints the key (the job logs
are public).

    ODDSPAPI_API_KEY=... python oddspapi_probe.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from datetime import date, timedelta
from typing import Dict, List

import requests

BASE = "https://api.oddspapi.io/v4"
MMA = 20
LIMIT = 3


def get(path: str, key: str, **params):
    r = requests.get(f"{BASE}/{path}", params=dict(params, apiKey=key), timeout=30)
    print(f"GET /{path} {sorted(params)} -> HTTP {r.status_code}")
    time.sleep(1.1)                                             # the free tier's rate limit
    try:
        return r.json()
    except ValueError:
        return {"error": r.text[:300]}


def _rows(js):
    return js if isinstance(js, list) else (js.get("data") if isinstance(js, dict) and isinstance(js.get("data"), list)
                                            else [])


def market_names(key: str) -> Dict[str, str]:
    js = get("markets", key, sportId=MMA)
    out = {}
    for m in _rows(js):
        mid = str(m.get("marketId") or m.get("id") or "")
        name = m.get("marketName") or m.get("name") or ""
        if mid:
            out[mid] = f"{name}" + (f" {m.get('handicap')}" if m.get("handicap") not in (None, 0, "0") else "")
    print(f"  {len(out)} MMA markets listed")
    if not out:
        print("  ", json.dumps(js)[:300])
    return out


def ufc_fights(key: str) -> List[Dict]:
    today = date.today()
    js = get("fixtures", key, sportId=MMA, **{"from": today.isoformat(), "to": (today + timedelta(days=10)).isoformat()})
    rows = _rows(js)
    if not rows:
        print("  ", json.dumps(js)[:300])
    with_odds = [f for f in rows if f.get("hasOdds")]
    ufc = [f for f in with_odds if "UFC" in str(f.get("categoryName") or f.get("tournamentName") or "").upper()]
    print(f"  {len(rows)} MMA fights in the next 10 days, {len(with_odds)} with odds, {len(ufc)} UFC")
    return ufc or with_odds


def main() -> int:
    key = os.environ.get("ODDSPAPI_API_KEY", "").strip()
    if not key:
        print("ODDSPAPI_API_KEY is not set")
        return 1
    names = market_names(key)
    fights = ufc_fights(key)
    by_market, books = Counter(), Counter()
    dk = None
    for f in fights[:LIMIT]:
        js = get("odds", key, fixtureId=f.get("fixtureId"))
        bo = (js or {}).get("bookmakerOdds") or {}
        print(f"\nFight: {f.get('participant1Name')} vs {f.get('participant2Name')} · {f.get('tournamentName')} · "
              f"{f.get('startTime')} · {len(bo)} books")
        seen = set()
        for bk, b in bo.items():
            mk = (b or {}).get("markets") or {}
            books[bk] += len(mk)
            for mid in mk:
                if mid not in seen:
                    seen.add(mid)
                    by_market[mid] += 1
            if dk is None and bk == "draftkings" and mk:
                dk = (f, mk)
    print("\nMarkets (and how many of these fights carry each):")
    for mid, n in sorted(by_market.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {mid} {names.get(mid, '?')}: {n}")
    print("\nBooks (markets posted across these fights):")
    for bk, n in books.most_common(30):
        print(f"  {bk}: {n}")
    if dk:
        f, mk = dk
        print(f"\nDraftKings, {f.get('participant1Name')} vs {f.get('participant2Name')}:")
        for mid, m in mk.items():
            prices = []
            for oid, o in ((m or {}).get("outcomes") or {}).items():
                p = (((o or {}).get("players") or {}).get("0") or {})
                prices.append(f"{oid}={p.get('price') if isinstance(p, dict) else p}")
            print(f"  {mid} {names.get(mid, '?')}: {', '.join(prices)}")
    else:
        print("\nNo DraftKings markets on these fights.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
