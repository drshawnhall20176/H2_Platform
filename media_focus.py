"""
media_focus.py — day- and game-aware framing for the Media Room / Podcast Studio.

Why this exists (reported gap): the Media Room used to curate selections from the WHOLE slate the
engine returned. For MLB that is one day, but NFL/NCAAF slates are a full WEEK, so on a Monday
night with one game on the ticket the page still talked about Sunday's games. This module is the
shared, pure (no Streamlit) layer that:
  * works out which calendar day (US/Eastern) each play/game belongs to,
  * narrows a slate to the games actually on the chosen date,
  * groups/curates selections per game in kickoff order, and
  * words the framing ("Monday night — one game: Falcons at Saints").

Honest limits: a bare date (no clock) still pins a game to that day but not to a kickoff time;
a play with NO date at all is kept (never silently dropped) because we can't tell where it belongs.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import sports

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

NFL_NICKNAMES = {
    "ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills", "CAR": "Panthers",
    "CHI": "Bears", "CIN": "Bengals", "CLE": "Browns", "DAL": "Cowboys", "DEN": "Broncos",
    "DET": "Lions", "GB": "Packers", "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars",
    "KC": "Chiefs", "LA": "Rams", "LAC": "Chargers", "LAR": "Rams", "LV": "Raiders",
    "MIA": "Dolphins", "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
    "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SEA": "Seahawks", "SF": "49ers",
    "TB": "Buccaneers", "TEN": "Titans", "WAS": "Commanders", "WSH": "Commanders",
}


def day_of(iso: Optional[str]) -> Optional[str]:
    """'YYYY-MM-DD' (US/Eastern) for a start time. A bare date returns itself; missing/garbled → None."""
    if not iso:
        return None
    s = str(iso).strip()
    if len(s) <= 10:
        return s if len(s) == 10 and s[4] == "-" and s[7] == "-" else None
    dt = sports.game_dt(s)
    return dt.strftime("%Y-%m-%d") if dt else None


def plays_on_date(plays: List[Dict], date_str: str) -> List[Dict]:
    """Plays whose game is on `date_str` (Eastern). Plays with no usable date are kept."""
    out = []
    for p in plays:
        d = day_of(p.get("GameDate"))
        if d is None or d == date_str:
            out.append(p)
    return out


def nice_matchup(label: str) -> str:
    """'ATL @ NO' → 'Falcons at Saints' when both are known NFL codes; otherwise 'A at B'."""
    if " @ " not in (label or ""):
        return label or ""
    away, home = [x.strip() for x in label.split(" @ ", 1)]
    return f"{NFL_NICKNAMES.get(away.upper(), away)} at {NFL_NICKNAMES.get(home.upper(), home)}"


def games_on_date(meta: List[Dict], plays: List[Dict], date_str: str) -> List[Dict]:
    """Games on `date_str`, kickoff order (unknown time last). Built from slate meta; falls back
    to the plays' own Game/GameDate if meta is empty. Each: label, matchup, start, time_text, slot."""
    raw: Dict[str, Optional[str]] = {}
    for m in meta or []:
        if m.get("label"):
            raw[m["label"]] = m.get("game_date") or m.get("GameDate")
    if not raw:
        for p in plays or []:
            if p.get("Game"):
                raw.setdefault(p["Game"], p.get("GameDate"))
    games = []
    for label, iso in raw.items():
        d = day_of(iso)
        if d is not None and d != date_str:
            continue
        dt = sports.game_dt(iso)
        games.append({
            "label": label, "matchup": nice_matchup(label), "start": dt,
            "time_text": dt.strftime("%-I:%M %p ET") if dt else "time TBD",
            "slot": sports.slot_of(dt),
        })
    games.sort(key=lambda g: (g["start"] is None, g["start"] or 0, g["label"]))
    return games


def other_days_with_games(meta: List[Dict], date_str: str) -> List[str]:
    """Other calendar days that DO have games — for the 'nothing today' message."""
    days = {day_of(m.get("game_date") or m.get("GameDate")) for m in meta or []}
    return sorted(d for d in days if d and d != date_str)


def slate_phrase(games: List[Dict], date_str: str, sport_key: str = "") -> str:
    """e.g. 'Monday night — one game on the ticket: Falcons at Saints (8:15 PM ET)'."""
    if not games:
        return "No games on the ticket"
    dt = next((g["start"] for g in games if g["start"]), None)
    try:
        from datetime import datetime
        wd = _WEEKDAYS[datetime.strptime(date_str, "%Y-%m-%d").weekday()]
    except ValueError:
        wd = ""
    part = ""
    if dt is not None:
        part = " afternoon" if dt.hour < 17 else " night"
    when = f"{wd}{part}".strip()
    if len(games) == 1:
        g = games[0]
        return f"{when} — one game on the ticket: {g['matchup']} ({g['time_text']})"
    return f"{when} — {len(games)} games on the ticket"


def group_by_game(plays: List[Dict], games: List[Dict]) -> List[Tuple[Dict, List[Dict]]]:
    """[(game, plays)] in kickoff order; plays for unlisted games get a trailing synthetic game."""
    by = {g["label"]: [] for g in games}
    extra: Dict[str, List[Dict]] = {}
    for p in plays:
        lab = p.get("Game")
        (by if lab in by else extra).setdefault(lab, []).append(p)
    out = [(g, by[g["label"]]) for g in games]
    for lab, ps in extra.items():
        out.append(({"label": lab, "matchup": nice_matchup(lab), "start": None,
                     "time_text": "time TBD", "slot": "TBD"}, ps))
    return out


def curate_per_game(plays: List[Dict], games: List[Dict], curate, per_game: int = 3,
                    per_market_cap: int = 2, rank_key: str = "Conviction"
                    ) -> List[Tuple[Dict, List[Dict]]]:
    """Top `per_game` selections for EACH game (kickoff order), via the sport's own
    curate_selections (`curate`). Games with no qualifying play are kept with an empty list so the
    show can still say 'nothing we love in X'."""
    return [(g, curate(ps, n=per_game, per_market_cap=per_market_cap, rank_key=rank_key))
            for g, ps in group_by_game(plays, games)]


def today_eastern():
    """Today's date in US/Eastern — the server runs in UTC, so a plain datetime.now() flips to
    'tomorrow' at 8 PM ET, exactly when Monday Night Football is on."""
    from datetime import datetime
    return datetime.now(sports._EASTERN).date()
