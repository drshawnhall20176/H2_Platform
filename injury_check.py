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
from typing import Callable, Dict, Iterable, List, Optional

LEAGUES = {"NBA": "basketball/nba", "NFL": "football/nfl", "NHL": "hockey/nhl", "WNBA": "basketball/wnba",
           "NCAAF": "football/college-football", "NCAAMB": "basketball/mens-college-basketball"}
URL = "https://site.api.espn.com/apis/site/v2/sports/{path}/injuries"
TTL = 600
_OUT_STATUS = {"out", "doubtful", "injured reserve", "suspension", "ir", "out for season"}
_OUT_TEXT = re.compile(r"\b(?:is|will be|has been ruled|ruled|remains?)\s+(?:out|doubtful)\b|\bwon't play\b|\bwill not play\b",
                       re.I)
_Q_TEXT = re.compile(r"\bquestionable\b|\bgame[- ]time decision\b|\buncertain\b", re.I)
_cache: Dict[str, tuple] = {}
_full: Dict[str, tuple] = {}


def _norm(name) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", "", s)
    return " ".join(w for w in s.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def classify(status: Optional[str], comment: Optional[str]) -> Optional[str]:
    st = (status or "").strip().lower()
    if st in _OUT_STATUS:
        return "out"
    if st == "active":                                          # Nov 26: cleared on the inactives list -- an old
        return None                                             # "questionable" note no longer counts
    c = comment or ""
    if _OUT_TEXT.search(c):
        return "out"
    if st == "questionable" or _Q_TEXT.search(c):
        return "questionable"
    return None


def _get_json(sport: str) -> Dict:
    path = LEAGUES.get(sport)
    if not path:
        return {}
    try:
        import requests
        return requests.get(URL.format(path=path), timeout=8).json() or {}
    except Exception:                                           # noqa: BLE001
        return {}


def parse(js: Dict) -> List[Dict]:
    """Nov 25: every flagged player with his team, so a game card can list who's out on each side.
    {"name", "team", "abbr", "pos", "status": "out" | "questionable", "label", "type", "returns", "comment"}"""
    out: List[Dict] = []
    for team in (js or {}).get("injuries") or []:
        for i in team.get("injuries") or []:
            ath = i.get("athlete") or {}
            name = ath.get("displayName")
            comment = i.get("shortComment") or i.get("longComment") or ""
            c = classify(i.get("status"), comment)
            if not name or not c:
                continue
            tm = ath.get("team") or {}
            det = i.get("details") or {}
            out.append({"name": name, "team": tm.get("displayName") or team.get("displayName") or "",
                        "abbr": tm.get("abbreviation") or "", "pos": (ath.get("position") or {}).get("abbreviation") or "",
                        "status": c, "label": i.get("status") or "", "type": det.get("type") or "",
                        "returns": det.get("returnDate") or "", "comment": comment})
    return out


def entries(sport: str, now: Optional[float] = None) -> List[Dict]:
    """parse() of the league's report, cached TTL seconds."""
    now = time.time() if now is None else now
    hit = _full.get(sport)
    if hit and now - hit[0] < TTL:
        return hit[1]
    got = parse(_get_json(sport))
    _full[sport] = (now, got)
    return got


def _fetch(sport: str) -> Dict[str, str]:
    return {_norm(e["name"]): e["status"] for e in entries(sport)}


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


def _team_keys(team) -> set:
    t = _norm(team)
    keys = {t} if t else set()
    if t and len(t.split()) > 1:
        keys.add(t.split()[-1])                                 # "boston bruins" -> "bruins"
    return keys


def for_team(sport: str, team, report_entries: Optional[List[Dict]] = None) -> List[Dict]:
    """The flagged players on one team (matched on abbreviation, full name or nickname), out first."""
    want = _team_keys(team)
    if not want:
        return []
    got = []
    for e in (entries(sport) if report_entries is None else report_entries):
        have = _team_keys(e.get("team")) | ({_norm(e.get("abbr"))} if e.get("abbr") else set())
        full_w, full_h = _norm(team), _norm(e.get("team"))
        if want & have or (full_w and full_h and (full_h.startswith(full_w + " ") or full_w.startswith(full_h + " "))):
            got.append(e)
    return sorted(got, key=lambda e: (e["status"] != "out", e["name"]))


def live_for(day) -> bool:
    """Today's injury report only means today (ET)."""
    try:
        from datetime import datetime
        import pytz
        return str(day) == datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
    except Exception:                                           # noqa: BLE001
        return False


def screen(rows: Iterable[Dict], sport_of: Callable[[Dict], str], name_of: Callable[[Dict], str],
           status: Optional[Callable[[str, str], Optional[str]]] = None) -> List[Dict]:
    """Nov 25 (PropSeason scrub): drop picks on players now ruled out; tag questionable ones with
    _inj="questionable" so cards can say so. Any failure leaves the rows as they were."""
    rows = list(rows or [])
    try:
        status = status or (lambda sp, nm: globals()["status"](sp, nm))
        out = []
        for r in rows:
            sp, nm = sport_of(r) or "", name_of(r) or ""
            s = status(sp, nm) if sp in LEAGUES and nm else None
            if s == "out":
                continue
            out.append(dict(r, _inj="questionable") if s == "questionable" else r)
        return out
    except Exception:                                           # noqa: BLE001
        return rows


def chip(state: Optional[str]) -> str:
    return {"out": "🚑 Out tonight", "questionable": "⚠️ Questionable tonight"}.get(state or "", "")
