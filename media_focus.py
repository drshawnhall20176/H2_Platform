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
    to the plays' own Game/GameDate if meta is empty. Each: key, label, iso, dh, matchup, start,
    time_text, slot. A doubleheader (same label twice) gets a distinct key per game and a
    "(Game n)" suffix on its matchup — plays are told apart by their own GameDate."""
    raw: List[Tuple[str, Optional[str]]] = []
    for m in meta or []:
        if m.get("label"):
            raw.append((m["label"], m.get("game_date") or m.get("GameDate")))
    if not raw:
        seen = set()
        for p in plays or []:
            k = (p.get("Game"), p.get("GameDate"))
            if p.get("Game") and k not in seen:
                seen.add(k)
                raw.append(k)
    counts: Dict[str, int] = {}
    for label, _ in raw:
        counts[label] = counts.get(label, 0) + 1
    games = []
    for label, iso in raw:
        d = day_of(iso)
        if d is not None and d != date_str:
            continue
        dt = sports.game_dt(iso)
        dh = counts[label] > 1
        games.append({
            "key": f"{label}|{iso}" if dh else label, "label": label, "iso": iso, "dh": dh,
            "game_no": None, "matchup": nice_matchup(label), "start": dt,
            "time_text": dt.strftime("%-I:%M %p ET") if dt else "time TBD",
            "slot": sports.slot_of(dt),
        })
    games.sort(key=lambda g: (g["start"] is None, g["start"] or 0, g["label"]))
    nth: Dict[str, int] = {}
    for g in games:
        if g["dh"]:
            nth[g["label"]] = nth.get(g["label"], 0) + 1
            g["game_no"] = nth[g["label"]]
            g["matchup"] = f"{g['matchup']} (Game {g['game_no']})"
    return games


def plays_for_game(plays: List[Dict], game: Dict) -> List[Dict]:
    """The plays belonging to one game (doubleheader-safe: matched on GameDate too)."""
    return [p for p in plays if p.get("Game") == game["label"]
            and (not game.get("dh") or p.get("GameDate") == game.get("iso"))]


ALL_SLATE = "All slate"
ALL_GAMES_IN_SLOT = "All games in this slot"


def slot_options(games: List[Dict]) -> List[str]:
    """The site-standard Time slot choices: 'All slate' + the slots present (Afternoon/Evening/Late/TBD)."""
    present = {g["slot"] for g in games}
    return [ALL_SLATE] + [s for s in sorted(sports.SLOT_ORDER, key=sports.SLOT_ORDER.get) if s in present]


def game_options(games: List[Dict], slot: str = ALL_SLATE) -> List[Tuple[str, str]]:
    """The site-standard Game choices for a slot: [(key, '8:15 PM ET — ATL @ NO')], chronological.
    (The caller adds the 'All games in this slot' entry.)"""
    out = []
    for g in games:
        if slot != ALL_SLATE and g["slot"] != slot:
            continue
        label = g["label"] + (f" (Game {g['game_no']})" if g["game_no"] else "")
        out.append((g["key"], label if g["start"] is None else f"{g['time_text']} — {label}"))
    return out


def select_games(games: List[Dict], slot: str, game_key: str) -> List[Dict]:
    """Apply the Time slot + Game picks (as the other pages do): game_key == ALL_GAMES_IN_SLOT keeps
    every game in the slot; otherwise exactly that game."""
    in_slot = [g for g in games if slot == ALL_SLATE or g["slot"] == slot]
    return in_slot if game_key == ALL_GAMES_IN_SLOT else [g for g in in_slot if g["key"] == game_key]


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
    out, used = [], set()
    for g in games:
        ps = plays_for_game(plays, g)
        used.update(id(p) for p in ps)
        out.append((g, ps))
    extra: Dict[str, List[Dict]] = {}
    for p in plays:
        if id(p) not in used:
            extra.setdefault(p.get("Game"), []).append(p)
    for lab, ps in extra.items():
        out.append(({"key": lab, "label": lab, "iso": None, "dh": False, "game_no": None, "matchup": nice_matchup(lab),
                     "start": None, "time_text": "time TBD", "slot": "TBD"}, ps))
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
