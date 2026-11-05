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
# Nov 4: EuroCup -- results and schedule from the EuroLeague's own feed (competition "U"); the odds feed doesn't carry it,
# so the page shows the model's fair lines and checks a typed sportsbook price instead of listing book lines.
LEAGUES["EUROCUP"] = {"title": "EuroCup", "odds_key": None, "min_games": 30, "lam": 3.0, "sd": 11.5, "comp": "U"}
LEAGUES["EUROLEAGUE"]["sd"] = 11.5
LEAGUES["NBL"]["sd"] = 12.0
HALF_LIFE = 45.0               # days: a game 45 days old counts half as much as tonight's
PRIOR_SEASON_WEIGHT = 0.5      # and last season's games count half again (rosters turn over)
NCAAMB_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
EL_URL = "https://api-live.euroleague.net/v2/competitions/{comp}/seasons/{code}/games"   # E = EuroLeague, U = EuroCup
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
def euroleague_season(code: str, fetch: Callable = _http, comp: str = "E", league: str = "EUROLEAGUE") -> List[Dict]:
    """Completed games of one EuroLeague ("E2025" = 2025-26) or EuroCup ("U2026", comp="U") season."""
    data = fetch(EL_URL.format(comp=comp, code=code)) or {}
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
        out.append({"league": league, "id": str(g.get("identifier") or g.get("id")),
                    "date": str(g.get("date") or g.get("utcDate") or "")[:10], "season": code,
                    "home_team": hn, "away_team": an, "home_points": hs, "away_points": as_, "neutral_site": False})
    return out


def euroleague_upcoming(code: str, fetch: Callable = _http, comp: str = "E", league: str = "EUROLEAGUE") -> List[Dict]:
    """Scheduled (not yet played) games with their UTC start: [{"league","id","kickoff","home","away","neutral"}]."""
    data = fetch(EL_URL.format(comp=comp, code=code)) or {}
    out = []
    for g in data.get("data") or []:
        if g.get("played"):
            continue
        hn = ((g.get("local") or {}).get("club") or {}).get("name")
        an = ((g.get("road") or {}).get("club") or {}).get("name")
        ko = g.get("utcDate")
        if not hn or not an or not ko:
            continue
        out.append({"league": league, "id": str(g.get("identifier") or g.get("id")), "kickoff": str(ko).replace("Z", "+00:00"),
                    "home": hn, "away": an, "neutral": bool(g.get("isNeutralVenue"))})
    return out


# --------------------------------------------------------------------------- FIBA club competitions (Nov 4)
# Basketball Champions League, FIBA Europe Cup and EuroCup Women: DraftKings lists them, the odds feed doesn't. FIBA's
# own competition pages carry every game (teams, scores, UTC start) as embedded JSON, so results and the schedule
# come from there and the page shows fair lines, as EuroCup does.
FIBA_PAGES = {
    "BCL": ["https://www.championsleague.basketball/en/games",
            "https://www.fiba.basketball/en/events/basketball-champions-league-{a}-{b}/games"],
    "FEC": ["https://www.fiba.basketball/en/events/fiba-europe-cup-{a}-{b}/games"],
    "EUROCUPW": ["https://www.fiba.basketball/en/events/eurocup-women-{a}-{b}/games"],
}
LEAGUES.update({
    "BCL": {"title": "Basketball Champions League", "odds_key": None, "min_games": 0, "lam": 3.0, "sd": 11.5,
            "decay": True, "min_decay_games": 40},
    "FEC": {"title": "FIBA Europe Cup", "odds_key": None, "min_games": 0, "lam": 3.0, "sd": 12.0, "decay": True,
            "min_decay_games": 60},
    "EUROCUPW": {"title": "EuroCup Women", "odds_key": None, "min_games": 0, "lam": 3.0, "sd": 11.0, "decay": True,
                 "min_decay_games": 60},
})


def _http_text(url: str, params: Optional[Dict] = None) -> Optional[str]:
    import requests
    try:
        r = requests.get(url, params=params or {}, timeout=40, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"})
        return r.text if r.ok else None
    except Exception:                                           # noqa: BLE001
        return None


def fiba_games(text: Optional[str]) -> List[Dict]:
    """Every distinct game object embedded in a FIBA competition page."""
    import json
    if not text:
        return []
    t = text.replace('\\"', '"')
    dec, out, seen, i = json.JSONDecoder(), [], set(), 0
    while True:
        i = t.find('{"gameId":', i)
        if i < 0:
            break
        try:
            g, end = dec.raw_decode(t, i)
        except ValueError:
            i += 10
            continue
        i = end
        if isinstance(g, dict) and g.get("gameId") not in seen and g.get("teamA") and g.get("teamB"):
            seen.add(g.get("gameId"))
            out.append(g)
    return out


def _fiba_name(team: Dict) -> Optional[str]:
    return (team or {}).get("shortName") or (team or {}).get("officialName")


def _fiba_played(g: Dict) -> bool:
    return (str(g.get("gameResultStatusCode") or g.get("statusCode") or "").upper() == "VALID"
            and (_num(g.get("teamAScore")) or 0) + (_num(g.get("teamBScore")) or 0) > 0 and not g.get("isLive"))


def fiba_pages(league: str, season: str) -> List[str]:
    a = int(season) % 100
    return [u.format(a=f"{a:02d}", b=f"{(a + 1) % 100:02d}") for u in FIBA_PAGES[league]]


def fiba_season(league: str, season: str, fetch_text: Callable = _http_text, current: bool = True) -> List[Dict]:
    """(completed games, upcoming games) of one season. The BCL's own site lists only the current season."""
    for u in fiba_pages(league, season):
        if "{" not in u and not current and "championsleague" in u:
            continue
        games = fiba_games(fetch_text(u))
        if games:
            return games
    return []


def fiba_results(league: str, games: Sequence[Dict]) -> List[Dict]:
    out = []
    for g in games:
        if not _fiba_played(g):
            continue
        hn, an = _fiba_name(g["teamA"]), _fiba_name(g["teamB"])
        when = str(g.get("gameDateTimeUTC") or g.get("gameDateTime") or "")[:10]
        if not hn or not an or when.startswith("0001"):
            continue
        out.append({"league": league, "id": f"fiba-{g.get('gameId')}", "date": when, "home_team": hn, "away_team": an,
                    "home_points": _num(g["teamAScore"]), "away_points": _num(g["teamBScore"]),
                    "neutral_site": str((g.get("round") or {}).get("gameSystemCode") or "HA") != "HA"})
    return out


def fiba_upcoming(league: str, games: Sequence[Dict]) -> List[Dict]:
    out = []
    for g in games:
        ko = str(g.get("gameDateTimeUTC") or "")
        if _fiba_played(g) or g.get("isLive") or g.get("isPostponed") or not ko or ko.startswith("0001"):
            continue
        hn, an = _fiba_name(g["teamA"]), _fiba_name(g["teamB"])
        if not hn or not an:
            continue
        out.append({"league": league, "id": f"fiba-{g.get('gameId')}", "kickoff": ko[:19] + "+00:00", "home": hn, "away": an,
                    "neutral": str((g.get("round") or {}).get("gameSystemCode") or "HA") != "HA"})
    return out


# --------------------------------------------------------------------------- domestic leagues via FIBA LiveStats (Nov 5)
# Leagues DraftKings lists that keep their stats on FIBA LiveStats (Genius Sports). Its open competition feed shows each
# league's CURRENT round only -- no season history -- so these leagues are recorded from Nov 5 on, every capture run,
# and get fair lines once enough games are stored to rate the teams (min_decay_games). Competition ids were matched to
# the leagues by their team lists (research/probe_leagues2.py) and change each season.
GENIUS_URL = "https://fibalivestats.dcd.shared.geniussports.com/data/competition/{}.json"
GENIUS_COMPS = {
    "NKL": [49833],        # Lithuania NKL (Žalgiris-2, Rytas-2, Sūduva, Perlas Go, Neptūnas-II, ...)
    "ICELAND": [49040],    # Iceland Premier League (Tindastóll, Keflavík, KR, Grindavík, Álftanes, ÍR, Höttur, Ármann)
    "BAHRAIN": [50172],    # Bahrain Premier League (Manama, Al Ahli, Samaheej, Sitra, Nuwaidrat, Isa Town, ...)
    "ESTONIA1": [49981],   # Estonia 1st League (Rapla, Kohila, Rakvere, Hiiumaa, Askus Jetoil, ...)
    "QATAR": [49726],      # Qatar QBL (Al Gharafa, Al Khor, ...) -- one game seen so far; confirm as more appear
}
for _k, _t in (("NKL", "Lithuania NKL"), ("ICELAND", "Iceland Premier League"), ("BAHRAIN", "Bahrain Premier League"),
               ("ESTONIA1", "Estonia 1st League"), ("QATAR", "Qatar QBL")):
    LEAGUES[_k] = {"title": _t, "odds_key": None, "min_games": 0, "lam": 3.0, "sd": 12.0, "decay": True,
                   "min_decay_games": 30}


def genius_games(league: str, fetch: Callable = _http) -> List[Dict]:
    """The games FIBA LiveStats currently lists for the league's competitions (its current round)."""
    out, seen = [], set()
    for cid in GENIUS_COMPS.get(league, []):
        for m in fetch(GENIUS_URL.format(cid)) or []:
            if isinstance(m, dict) and m.get("matchId") not in seen:
                seen.add(m.get("matchId"))
                out.append(m)
    return out


def _genius_utc(m: Dict) -> Optional[str]:
    t = str(m.get("matchTimeUTC") or "").strip()
    return (t.replace(" ", "T")[:19] + "+00:00") if len(t) >= 16 else None


def genius_results(league: str, games: Sequence[Dict]) -> List[Dict]:
    out = []
    for m in games:
        if str(m.get("matchStatus") or "").upper() != "COMPLETE":
            continue
        hs, as_ = _num(m.get("homescore")), _num(m.get("awayscore"))
        hn, an = m.get("homename"), m.get("awayname")
        ko = _genius_utc(m) or str(m.get("matchTime") or "")
        if hs is None or as_ is None or not hn or not an or not ko:
            continue
        out.append({"league": league, "id": f"gs-{m.get('matchId')}", "date": ko[:10], "home_team": hn, "away_team": an,
                    "home_points": hs, "away_points": as_, "neutral_site": False})
    return out


def genius_upcoming(league: str, games: Sequence[Dict]) -> List[Dict]:
    out = []
    for m in games:
        if str(m.get("matchStatus") or "").upper() == "COMPLETE" or str(m.get("live")) in ("1", "True", "true"):
            continue
        ko, hn, an = _genius_utc(m), m.get("homename"), m.get("awayname")
        if ko and hn and an:
            out.append({"league": league, "id": f"gs-{m.get('matchId')}", "kickoff": ko, "home": hn, "away": an,
                        "neutral": False})
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
    """Recency weights for a fit made on `asof`: half-life HALF_LIFE days of PLAYED time, last season's games x
    PRIOR_SEASON_WEIGHT.

    Nov 3 fix: the offseason no longer counts as elapsed time. Counting it (~7 months for college) left last season
    weighted ~1% on opening night, so the fit had only a handful of games and pinned everything on home court
    (~22 points -- early-season home teams are mostly favorites hosting small schools). Now a game's age is measured
    from the end of its own season when it's from a past one."""
    a = date.fromisoformat(asof[:10])
    cur = season_of(league, asof)
    cur_dates = sorted(g["date"][:10] for g in games if season_of(league, g["date"]) == cur and g["date"][:10] <= asof[:10])
    cur_start = date.fromisoformat(cur_dates[0]) if cur_dates else a
    played_this_season = max(0, (a - cur_start).days)
    last_day: Dict[str, date] = {}
    for g in games:
        s = season_of(league, g["date"])
        d = date.fromisoformat(g["date"][:10])
        if s != cur and (s not in last_day or d > last_day[s]):
            last_day[s] = d
    out = []
    for g in games:
        d = date.fromisoformat(g["date"][:10])
        s = season_of(league, g["date"])
        if s == cur:
            days = max(0, (a - d).days)
            w = 0.5 ** (days / HALF_LIFE)
        else:
            days = played_this_season + max(0, (last_day[s] - d).days)
            w = PRIOR_SEASON_WEIGHT * 0.5 ** (days / HALF_LIFE)
        out.append(w)
    return out


HFA_PRIOR = {"NCAAMB": (3.0, 200.0), "NBA": (2.5, 200.0), "NHL": (0.25, 200.0), "WNBA": (2.5, 200.0)}


def ratings_weighted(games: Sequence[Dict], weights: Sequence[float], lam: float = 4.0,
                     hfa_prior: Optional[tuple] = None) -> Optional[Dict]:
    """game_picks.ratings with a weight per game (weighted ridge): {"mu","off","def","hfa"}. hfa_prior (value,
    strength) pulls home advantage toward a known size -- in college it otherwise soaks up the early-season
    scheduling (home teams hosting much weaker opponents)."""
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
    rhs = Xw.T @ (y - mu)
    if hfa_prior:
        reg[2 * n, 2 * n] = hfa_prior[1]
        rhs[2 * n] += hfa_prior[1] * hfa_prior[0]
    beta = np.linalg.solve(X.T @ Xw + reg, rhs)
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
