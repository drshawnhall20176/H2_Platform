"""
intl_hoops.py — international basketball game model (Nov 3): EuroLeague and Australia's NBL. TRACKING ONLY until it
proves itself.

Data: EuroLeague's own API (every game, every season) and ESPN's NBL scoreboard. Odds: The Odds API
(basketball_euroleague, basketball_nbl): moneyline, spread and total at the US books.

The model is the same one the college spreads use (game_picks.ratings): every team gets an offense and a defense
rating -- points scored and allowed after adjusting for who it played -- plus a home-court edge, fitted by ridge least
squares on the season's completed games. Projected margin and total come straight from the ratings.
"""
from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Callable, Dict, Iterable, List, Optional, Sequence

LEAGUES = {
    "EUROLEAGUE": {"title": "EuroLeague", "odds_key": "basketball_euroleague", "min_games": 40, "lam": 3.0},
    "NBL": {"title": "NBL (Australia)", "odds_key": "basketball_nbl", "min_games": 25, "lam": 3.0},
}
EL_URL = "https://api-live.euroleague.net/v2/competitions/E/seasons/{code}/games"
NBL_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nbl/scoreboard"
STOP = {"basket", "basketball", "bc", "kk", "bk", "club", "de", "the", "fc", "sk", "cb", "pbc", "ok", "and"}


def _http(url: str, params: Optional[Dict] = None):
    import requests
    try:
        r = requests.get(url, params=params or {}, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        return r.json() if r.ok else None
    except Exception:                                           # noqa: BLE001
        return None


def _num(x) -> Optional[float]:
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def tokens(name: Optional[str]) -> set:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    return {w for w in re.split(r"[^a-z0-9]+", s) if len(w) >= 3 and w not in STOP}


def same_team(a: Optional[str], b: Optional[str]) -> bool:
    return bool(tokens(a) & tokens(b))


def match_event(events: Iterable[Dict], home: str, away: str) -> Optional[Dict]:
    """The odds event for a game: both teams share a distinctive word with the event's (either order); the best
    overlap wins."""
    best, score = None, 0
    for e in events or []:
        h, a = tokens(e.get("home_team")), tokens(e.get("away_team"))
        for x, y in ((h, a), (a, h)):
            s1, s2 = len(x & tokens(home)), len(y & tokens(away))
            if s1 and s2 and s1 + s2 > score:
                best, score = e, s1 + s2
    return best


# --------------------------------------------------------------------------- results
def euroleague_season(code: str, fetch: Callable = _http) -> List[Dict]:
    """Completed games of one EuroLeague season ("E2025" = 2025-26)."""
    data = fetch(EL_URL.format(code=code)) or {}
    out = []
    for g in data.get("data") or []:
        if not g.get("played"):
            continue
        loc, road = g.get("local") or {}, g.get("road") or {}
        hs, as_ = _num(loc.get("score")), _num(road.get("score"))
        hn = ((loc.get("club") or {}).get("name"))
        an = ((road.get("club") or {}).get("name"))
        if hs is None or as_ is None or not hn or not an:
            continue
        out.append({"league": "EUROLEAGUE", "id": str(g.get("identifier") or g.get("id")),
                    "date": str(g.get("date") or g.get("utcDate") or "")[:10], "season": code,
                    "home_team": hn, "away_team": an, "home_points": hs, "away_points": as_, "neutral_site": False})
    return out


def nbl_day(day: date, fetch: Callable = _http) -> List[Dict]:
    data = fetch(NBL_URL, {"dates": day.strftime("%Y%m%d")}) or {}
    out = []
    for ev in data.get("events") or []:
        for c in ev.get("competitions") or []:
            if not ((c.get("status") or {}).get("type") or {}).get("completed"):
                continue
            side = {}
            for t in c.get("competitors") or []:
                side[t.get("homeAway")] = ((t.get("team") or {}).get("displayName"), _num(t.get("score")))
            if "home" in side and "away" in side and side["home"][1] is not None:
                out.append({"league": "NBL", "id": f"nbl-{c.get('id')}", "date": str(c.get("date") or "")[:10],
                            "home_team": side["home"][0], "away_team": side["away"][0], "home_points": side["home"][1],
                            "away_points": side["away"][1], "neutral_site": bool(c.get("neutralSite"))})
    return out


def nbl_range(start: date, end: date, fetch: Callable = _http) -> List[Dict]:
    seen = {}
    d = start
    while d <= end:
        for g in nbl_day(d, fetch):
            seen[g["id"]] = g
        d += timedelta(days=1)
    return sorted(seen.values(), key=lambda g: g["date"])


def season_of(league: str, day: str) -> str:
    """Both leagues run Sept/Oct to May/June: a season is named by the year it starts."""
    y, m = int(day[:4]), int(day[5:7])
    return str(y if m >= 7 else y - 1)


# --------------------------------------------------------------------------- model
def ratings(games: Sequence[Dict], lam: float = 3.0) -> Optional[Dict]:
    import game_picks as GP
    return GP.ratings(games, lam)


def project(r: Optional[Dict], home: str, away: str, neutral: bool = False) -> Optional[Dict]:
    import game_picks as GP
    if not r:
        return None
    key = {t: t for t in r["off"]}
    h = next((t for t in key if same_team(t, home)), None)
    a = next((t for t in key if same_team(t, away)), None)
    if not h or not a or h == a:
        return None
    m = GP.project(r, h, a, neutral)
    return None if m is None else {"margin": m[0], "total": m[1]}


def win_prob(margin: float, sd: float = 11.5) -> float:
    """Home win chance from the projected margin (normal, basketball game-to-game spread ~11-12 points)."""
    return 0.5 * math.erfc(-margin / (sd * math.sqrt(2)))
