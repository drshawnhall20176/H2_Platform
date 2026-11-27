"""
sgo_probe.py -- what SportsGameOdds actually returns for UFC (Nov 27). A one-off check before anything is built on it.

Owner, Nov 27: a SportsGameOdds key for UFC props (The Odds API carries fight winner and a few totals only). This asks
the API for its MMA leagues, then the next fights with odds, and prints what it finds: the market types (statID /
betTypeID), how many fights carry each, which books post them -- DraftKings first -- and one fight's DraftKings props
as an example. Prints market names, fighters and prices only, never the key (the job logs are public). SportsGameOdds
bills per event returned, so it asks for at most LIMIT fights.

    SPORTSGAMEODDS_API_KEY=... python sgo_probe.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from typing import Dict, List

import requests

BASE = "https://api.sportsgameodds.com/v2"
LIMIT = 3


def get(path: str, key: str, **params) -> Dict:
    r = requests.get(f"{BASE}/{path}", params=params, headers={"x-api-key": key}, timeout=30)
    print(f"GET /{path} {sorted(params)} -> HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError:
        return {"error": r.text[:300]}


def mma_leagues(key: str) -> List[str]:
    js = get("leagues", key)
    rows = js.get("data") or []
    out = []
    for lg in rows:
        sid, lid = str(lg.get("sportID") or ""), str(lg.get("leagueID") or "")
        if "MMA" in sid.upper() or lid.upper() in ("UFC", "PFL", "BELLATOR"):
            out.append(lid)
            print(f"  league {lid}: sport {sid}, name {lg.get('name') or lg.get('shortName')}")
    if not rows:
        print("  no leagues returned:", json.dumps(js)[:300])
    return out


def summarize(events: List[Dict]) -> None:
    by_market, books = Counter(), Counter()
    dk_example = None
    for ev in events:
        teams = ev.get("teams") or {}
        names = [((teams.get(s) or {}).get("names") or {}).get("long") or (teams.get(s) or {}).get("teamID")
                 for s in ("away", "home")]
        start = (ev.get("status") or {}).get("startsAt")
        odds = ev.get("odds") or {}
        print(f"\nFight: {' vs '.join(str(n) for n in names)} · starts {start} · {len(odds)} odds")
        seen = set()
        for oid, o in odds.items():
            mk = f"{o.get('statID')} · {o.get('betTypeID')} · {o.get('periodID')} · " + \
                 ("fighter" if o.get("playerID") else str(o.get("statEntityID")))
            if mk not in seen:
                seen.add(mk)
                by_market[mk] += 1
            for bk, b in (o.get("byBookmaker") or {}).items():
                if b.get("available", True):
                    books[bk] += 1
            if dk_example is None and "draftkings" in (o.get("byBookmaker") or {}):
                dk_example = ev
    print("\nMarkets (statID · bet type · period · whose), and how many of these fights carry each:")
    for mk, n in sorted(by_market.items()):
        print(f"  {mk}: {n}")
    print("\nBooks (prices posted across these fights):")
    for bk, n in books.most_common(25):
        print(f"  {bk}: {n}")
    if dk_example:
        print("\nOne fight's DraftKings prices:")
        for oid, o in sorted((dk_example.get("odds") or {}).items()):
            b = (o.get("byBookmaker") or {}).get("draftkings")
            if not b:
                continue
            line = b.get("overUnder") or b.get("spread") or ""
            print(f"  {o.get('marketName') or oid}: {b.get('odds')} {line} (available {b.get('available')})")
    else:
        print("\nNo DraftKings prices on these fights.")


def main() -> int:
    key = os.environ.get("SPORTSGAMEODDS_API_KEY", "").strip()
    if not key:
        print("SPORTSGAMEODDS_API_KEY is not set")
        return 1
    leagues = mma_leagues(key) or ["UFC"]
    for lg in leagues[:2]:
        js = get("events", key, leagueID=lg, oddsAvailable="true", limit=LIMIT)
        evs = js.get("data") or []
        print(f"\n== {lg}: {len(evs)} fight(s) with odds")
        if not evs:
            print("  ", json.dumps(js)[:300])
            continue
        summarize(evs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
