"""
injury_check.py — who is out tonight, from ESPN's league-wide injury report, checked at read time (Nov 18).

The owner saw RJ Barrett 45+ Pts+Reb+Ast at the top of tonight's long shots after Barrett had been ruled out
(Sportsnet, 5:55 PM ET). The long-shot scan had run at 4:13 PM, before the news, and its saved picks are shown for
hours afterwards. Dean Wade, downgraded to questionable at 1:06 PM, was on the same list: the scan's read didn't treat
"questionable" as a reason to hold a long shot back. So saved picks are re-checked against the live report every time
they're shown (cached 10 minutes).

status(name) -> "out" | "questionable" | None. "out": Out / Doubtful / Injured Reserve / Suspension, or a report that
says he's out / doubtful. "questionable": a report that says questionable / game-time decision. ESPN lists plenty of
players as "Day-To-Day" with a box-score line for a comment (Tyrese Maxey tonight) -- that alone is not news.
Every failure returns {} (no news), the same as the platform's other injury reads.
"""
from __future__ import annotations

import re
import time
import unicodedata
from typing import Dict, Optional

LEAGUES = {"NBA": "basketball/nba", "NFL": "football/nfl", "NHL": "hockey/nhl", "WNBA": "basketball/wnba",
           "NCAAF": "football/college-football", "NCAAMB": "basketball/mens-college-basketball"}
URL = "https://site.api.espn.com/apis/site/v2/sports/{path}/injuries"
TTL = 600
_OUT_STATUS = {"out", "doubtful", "injured reserve", "suspension", "ir", "out for season"}
_OUT_TEXT = re.compile(r"\b(?:is|will be|has been ruled|ruled|remains?)\s+(?:out|doubtful)\b|\bwon't play\b|\bwill not play\b",
                       re.I)
_Q_TEXT = re.compile(r"\bquestionable\b|\bgame[- ]time decision\b|\buncertain\b", re.I)
_cache: Dict[str, tuple] = {}


def _norm(name) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", "", s)
    return " ".join(w for w in s.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def classify(status: Optional[str], comment: Optional[str]) -> Optional[str]:
    st = (status or "").strip().lower()
    if st in _OUT_STATUS:
        return "out"
    c = comment or ""
    if _OUT_TEXT.search(c):
        return "out"
    if st == "questionable" or _Q_TEXT.search(c):
        return "questionable"
    return None


def _fetch(sport: str) -> Dict[str, str]:
    path = LEAGUES.get(sport)
    if not path:
        return {}
    try:
        import requests
        js = requests.get(URL.format(path=path), timeout=8).json()
    except Exception:                                           # noqa: BLE001
        return {}
    out: Dict[str, str] = {}
    for team in js.get("injuries") or []:
        for i in team.get("injuries") or []:
            name = (i.get("athlete") or {}).get("displayName")
            c = classify(i.get("status"), i.get("shortComment") or i.get("longComment"))
            if name and c:
                out[_norm(name)] = c
    return out


def report(sport: str, now: Optional[float] = None) -> Dict[str, str]:
    """{normalized name: "out" | "questionable"} for the league, cached TTL seconds."""
    now = time.time() if now is None else now
    hit = _cache.get(sport)
    if hit and now - hit[0] < TTL:
        return hit[1]
    got = _fetch(sport)
    _cache[sport] = (now, got)
    return got


def status(sport: str, name) -> Optional[str]:
    return report(sport).get(_norm(name))
