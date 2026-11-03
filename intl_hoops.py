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
    # College: ~360 teams and a new season every November, so the ratings are fitted on the last ~13 months with
    # recent games weighted more (half-life HALF_LIFE days) and last season's games discounted -- usable from opening
    # night instead of waiting weeks for this season's sample.
    "NCAAMB": {"title": "College basketball (men)", "odds_key": "basketball_ncaab", "min_games": 0, "lam": 4.0,
               "decay": True},
}
# Nov 3: the pro leagues ESPN covers, same ratings machinery (recency-weighted, last season discounted).
ESPN_LEAGUE_URL = {"NBA": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
                   "NHL": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
                   "WNBA": "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"}
LEAGUES.update({
    "NBA": {"title": "NBA", "odds_key": "basketball_nba", "min_games": 0, "lam": 3.0, "decay": True, "sd": 12.5},
    "NHL": {"title": "NHL", "odds_key": "icehockey_nhl", "min_games": 0, "lam": 3.0, "decay": True, "sd": 2.4},
    "WNBA": {"title": "WNBA", "odds_key": "basketball_wnba", "min_games": 0, "lam": 3.0, "decay": True, "sd": 12.0},
})
LEAGUES["NCAAMB"]["sd"] = 11.0
LEAGUES["EUROLEAGUE"]["sd"] = 11.5
LEAGUES["NBL"]["sd"] = 12.0
HALF_LIFE = 45.0               # days: a game 45 days old counts half as much as tonight's
PRIOR_SEASON_WEIGHT = 0.5      # and last season's games count half again (rosters turn over)
NCAAMB_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
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


ALIAS = {"munchen": "munich", "muenchen": "munich", "milano": "milan", "olimpia": "milan", "armani": "milan",
         "beograd": "belgrade", "zvezda": "crvena", "partizan": "partizan", "olympiakos": "olympiacos",
         "pireus": "piraeus", "virtus": "virtus", "bologna": "bologna", "baskonia": "baskonia", "vitoria": "baskonia",
         "gasteiz": "baskonia", "saski": "baskonia", "efes": "efes", "anadolu": "efes", "maccabi": "maccabi",
         "zalgiris": "zalgiris", "kaunas": "zalgiris", "villeurbanne": "asvel", "lyon": "asvel"}


def tokens(name: Optional[str]) -> set:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    return {ALIAS.get(w, w) for w in re.split(r"[^a-z0-9]+", s) if len(w) >= 3 and w not in STOP}


def same_team(a: Optional[str], b: Optional[str]) -> bool:
    return bool(tokens(a) & tokens(b))


def _key(name: Optional[str]) -> str:
    return " ".join(sorted(tokens(name)))


def find_team(names: Iterable[str], name: str, loose: bool = False) -> Optional[str]:
    """The one name in `names` that is this team: an exact match (ignoring case / accents / filler words) first, else
    the single best word overlap (share of the shorter name's words). None when nothing matches or two tie -- college
    has many "Wildcats" and "Tennessee ..." teams, so a guess is worse than no read."""
    names = list(names)
    k = _key(name)
    exact = [n for n in names if _key(n) == k]
    if len(exact) == 1:
        return exact[0]
    t = tokens(name)
    if not t:
        return None
    scored = []
    for n in names:
        u = tokens(n)
        if t & u:
            scored.append((len(t & u) / min(len(t), len(u)), len(t & u), n))
    if not scored:
        return None
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][:2] == scored[1][:2]:
        return None
    if loose:                                                   # small leagues: one distinctive shared word is enough
        return scored[0][2]
    return scored[0][2] if scored[0][0] >= 0.99 or scored[0][1] >= 2 else None


def match_event(events: Iterable[Dict], home: str, away: str) -> Optional[Dict]:
    """The odds event for a game: exact team names first (either order), else both teams share a distinctive word
    with the event's; the best overlap wins."""
    events = list(events or [])
    for e in events:
        if {_key(e.get("home_team")), _key(e.get("away_team"))} == {_key(home), _key(away)}:
            return e
    best, score = None, 0
    for e in events:
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


def ncaamb_day(day: date, fetch: Callable = _http) -> List[Dict]:
    """Division I games final on `day` (ESPN groups=50)."""
    data = fetch(NCAAMB_URL, {"dates": day.strftime("%Y%m%d"), "groups": 50, "limit": 500}) or {}
    out = []
    for ev in data.get("events") or []:
        for c in ev.get("competitions") or []:
            if not ((c.get("status") or {}).get("type") or {}).get("completed"):
                continue
            side = {}
            for t in c.get("competitors") or []:
                side[t.get("homeAway")] = ((t.get("team") or {}).get("displayName"), _num(t.get("score")))
            if "home" in side and "away" in side and side["home"][1] is not None and side["away"][1] is not None:
                out.append({"league": "NCAAMB", "id": f"ncaamb-{c.get('id')}", "date": str(c.get("date") or "")[:10],
                            "home_team": side["home"][0], "away_team": side["away"][0], "home_points": side["home"][1],
                            "away_points": side["away"][1], "neutral_site": bool(c.get("neutralSite"))})
    return out


def espn_day(league: str, day: date, fetch: Callable = _http) -> List[Dict]:
    """Completed games on `day` for an ESPN pro league (NBA / NHL / WNBA)."""
    data = fetch(ESPN_LEAGUE_URL[league], {"dates": day.strftime("%Y%m%d"), "limit": 100}) or {}
    out = []
    for ev in data.get("events") or []:
        for c in ev.get("competitions") or []:
            st = ((c.get("status") or {}).get("type") or {})
            if not st.get("completed"):
                continue
            side = {}
            for t in c.get("competitors") or []:
                side[t.get("homeAway")] = ((t.get("team") or {}).get("displayName"), _num(t.get("score")))
            if "home" in side and "away" in side and side["home"][1] is not None and side["away"][1] is not None:
                out.append({"league": league, "id": f"{league.lower()}-{c.get('id')}", "date": str(c.get("date") or "")[:10],
                            "home_team": side["home"][0], "away_team": side["away"][0], "home_points": side["home"][1],
                            "away_points": side["away"][1], "neutral_site": bool(c.get("neutralSite")),
                            "season_type": ((ev.get("season") or {}).get("type"))})
    return out


def espn_range(league: str, start: date, end: date, fetch: Callable = _http) -> List[Dict]:
    seen = {}
    d = start
    while d <= end:
        for g in espn_day(league, d, fetch):
            if g.get("season_type") in (1, "1"):                # preseason games don't count
                continue
            seen[g["id"]] = g
        d += timedelta(days=1)
    return sorted(seen.values(), key=lambda g: g["date"])


def ncaamb_range(start: date, end: date, fetch: Callable = _http) -> List[Dict]:
    seen = {}
    d = start
    while d <= end:
        for g in ncaamb_day(d, fetch):
            seen[g["id"]] = g
        d += timedelta(days=1)
    return sorted(seen.values(), key=lambda g: g["date"])


def decay_weights(games: Sequence[Dict], asof: str, league: str) -> List[float]:
    """Recency weights for a fit made on `asof`: half-life HALF_LIFE days, last season's games x PRIOR_SEASON_WEIGHT."""
    a = date.fromisoformat(asof[:10])
    cur = season_of(league, asof)
    out = []
    for g in games:
        days = max(0, (a - date.fromisoformat(g["date"][:10])).days)
        w = 0.5 ** (days / HALF_LIFE)
        if season_of(league, g["date"]) != cur:
            w *= PRIOR_SEASON_WEIGHT
        out.append(w)
    return out


def ratings_weighted(games: Sequence[Dict], weights: Sequence[float], lam: float = 4.0) -> Optional[Dict]:
    """game_picks.ratings with a weight per game (weighted ridge): {"mu","off","def","hfa"}."""
    import numpy as np
    rows = [(g, w) for g, w in zip(games, weights) if w > 1e-4 and _num(g.get("home_points")) is not None
            and _num(g.get("away_points")) is not None]
    if len(rows) < 2:
        return None
    teams = sorted({g["home_team"] for g, _ in rows} | {g["away_team"] for g, _ in rows})
    ix = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    X, y, W = [], [], []
    for g, w in rows:
        home = 0.0 if str(g.get("neutral_site")).lower() in ("true", "1") else 1.0
        for t, o, pts, h in ((g["home_team"], g["away_team"], g["home_points"], home),
                             (g["away_team"], g["home_team"], g["away_points"], -home)):
            x = np.zeros(2 * n + 1)
            x[ix[t]], x[n + ix[o]], x[2 * n] = 1.0, -1.0, 0.5 * h
            X.append(x)
            y.append(float(pts))
            W.append(w)
    X, y, W = np.array(X), np.array(y), np.array(W)
    mu = float(np.average(y, weights=W))
    Xw = X * W[:, None]
    reg = np.eye(2 * n + 1) * lam
    reg[2 * n, 2 * n] = 0.0
    beta = np.linalg.solve(X.T @ Xw + reg, Xw.T @ (y - mu))
    return {"mu": mu, "off": {t: float(beta[ix[t]]) for t in teams}, "def": {t: float(beta[n + ix[t]]) for t in teams},
            "hfa": float(beta[2 * n])}


def season_of(league: str, day: str) -> str:
    """Winter leagues run Sept/Oct to May/June: a season is named by the year it starts. The WNBA (May-Oct) is
    named by its calendar year."""
    y, m = int(day[:4]), int(day[5:7])
    if league == "WNBA":
        return str(y)
    return str(y if m >= 7 else y - 1)


# --------------------------------------------------------------------------- model
def ratings(games: Sequence[Dict], lam: float = 3.0) -> Optional[Dict]:
    import game_picks as GP
    return GP.ratings(games, lam)


def project(r: Optional[Dict], home: str, away: str, neutral: bool = False, loose: bool = False) -> Optional[Dict]:
    import game_picks as GP
    if not r:
        return None
    h = find_team(r["off"], home, loose)
    a = find_team(r["off"], away, loose)
    if not h or not a or h == a:
        return None
    m = GP.project(r, h, a, neutral)
    return None if m is None else {"margin": m[0], "total": m[1]}


def win_prob(margin: float, sd: float = 11.5, league: Optional[str] = None) -> float:
    """Home win chance from the projected margin (normal, basketball game-to-game spread ~11-12 points)."""
    if league:
        sd = LEAGUES.get(league, {}).get("sd", sd)
    return 0.5 * math.erfc(-margin / (sd * math.sqrt(2)))
