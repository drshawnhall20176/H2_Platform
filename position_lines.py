"""
position_lines.py — posted book lines for the Position Matchups game log (the "Best lines" and "Hit rate" rows).

The log shows how often a position went OVER the line the books have posted for the OPPOSING starter in this
game, for each stat column. This module is the lookup side: which market a column maps to, finding the game's
event, picking one line per market, and the best over / under price. The network call is one function
(`fetch_offers`) that the page puts behind a button, because every market costs one Odds API credit.

PURE except fetch_offers.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import odds_api as O

# Log column key -> The Odds API player-prop market. Shares and target counts have no market.
COLUMN_MARKETS: Dict[str, str] = {
    "atd": "player_anytime_td", "td": "player_anytime_td",
    "pass_att": "player_pass_attempts", "pass_cmp": "player_pass_completions", "pass_yds": "player_pass_yds",
    "pass_long": "player_pass_longest_completion", "pass_td": "player_pass_tds", "pass_int": "player_pass_interceptions",
    "rush_att": "player_rush_attempts", "rush_yds": "player_rush_yds", "rush_long": "player_rush_longest",
    "rec": "player_receptions", "rec_yds": "player_reception_yds", "rec_long": "player_reception_longest",
    "rush_rec_yds": "player_rush_reception_yds",
}
_SUFFIX = {"jr", "sr", "ii", "iii", "iv", "v"}


def norm_name(name) -> str:
    """'D.J. Moore Jr.' and 'DJ Moore' compare equal: lower-case, punctuation out, generational suffix off."""
    words = re.sub(r"[^a-z0-9 ]+", "", str(name or "").lower().replace(".", "").replace("'", "")).split()
    while words and words[-1] in _SUFFIX:
        words.pop()
    return " ".join(words)


def markets_for(columns: Iterable[Tuple[str, str]]) -> List[str]:
    """The distinct markets the shown columns need, in column order."""
    out: List[str] = []
    for key, _ in columns:
        m = COLUMN_MARKETS.get(key)
        if m and m not in out:
            out.append(m)
    return out


# nflreadpy keys NFL teams by abbreviation ("KC"); The Odds API names them in full ("Kansas City Chiefs"). Without
# this, Position Matchups never matched an NFL game to the books (found Oct 29: "The books haven't listed this
# game yet" for Thursday night's CAR @ GB).
NFL_TEAMS = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers", "CHI": "Chicago Bears", "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys", "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars", "JAC": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs", "LA": "Los Angeles Rams", "LAR": "Los Angeles Rams", "LAC": "Los Angeles Chargers",
    "LV": "Las Vegas Raiders", "OAK": "Las Vegas Raiders", "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings",
    "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants", "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans", "WAS": "Washington Commanders", "WSH": "Washington Commanders",
}


def _norm_team(x) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(x or "")).encode("ascii", "ignore").decode()   # San José -> San Jose
    t = t.lower().replace(".", "").replace("'", "").replace("’", "").replace("&", "and")
    return " ".join(t.split())


# Schedule short names -> the books' school names (Oct 31: "App State" never matched "Appalachian State Mountaineers").
_ALIASES = {"app state": "appalachian state", "uconn": "connecticut", "umass": "massachusetts",
            "southern miss": "southern mississippi", "fiu": "florida international", "fau": "florida atlantic",
            "sam houston": "sam houston state", "ul monroe": "louisiana monroe", "ulm": "louisiana monroe",
            "louisiana": "louisiana ragin cajuns", "hawaii": "hawaii rainbow warriors", "miami (oh)": "miami ohio",
            "miami oh": "miami ohio", "usf": "south florida", "unlv": "unlv rebels", "utsa": "utsa roadrunners",
            "pitt": "pittsburgh", "ole miss": "mississippi", "nc state": "north carolina state",
            "texas aandm": "texas a and m", "kennesaw st": "kennesaw state"}


def _team_keys(name) -> set:
    keys = {_norm_team(name)}
    full = NFL_TEAMS.get(str(name or "").strip().upper())
    if full:
        keys.add(_norm_team(full))
    for k in list(keys):
        if k in _ALIASES:
            keys.add(_ALIASES[k])
    # ESPN says "LA Clippers", the books "Los Angeles Clippers" (Oct 30: no lines loaded for LAC @ MIN).
    for k in list(keys):
        if k.startswith("la "):
            keys.add("los angeles " + k[3:])
        elif k.startswith("los angeles "):
            keys.add("la " + k[12:])
    return keys


def _same_team(a, b, prefix: bool) -> bool:
    ka, kb = _team_keys(a), _team_keys(b)
    if ka & kb:
        return True
    # College: the schedule says "Ohio State", the books "Ohio State Buckeyes".
    return prefix and any(y.startswith(x + " ") or x.startswith(y + " ") for x in ka for y in kb if x and y)


def match_event(events: Iterable[Dict], home_name: str, away_name: str) -> Optional[Dict]:
    """The Odds API event for a game: the one whose two teams are these two (any order). Exact names (or an NFL
    abbreviation's full name) first; then a name that is the start of the other ("Ohio State" / "Ohio State
    Buckeyes") -- only when exactly one event matches that way. None if absent or ambiguous."""
    events = list(events or [])
    for prefix in (False, True):
        hits = [e for e in events
                if (_same_team(e.get("home_team"), home_name, prefix) and _same_team(e.get("away_team"), away_name, prefix))
                or (_same_team(e.get("home_team"), away_name, prefix) and _same_team(e.get("away_team"), home_name, prefix))]
        if len(hits) == 1 or (hits and not prefix):
            return hits[0]
    return None


def _book_count(offer: Dict) -> int:
    return len(set(offer.get("over") or {}) | set(offer.get("under") or {}))


def _balance(offer: Dict) -> float:
    """How even the main prices are (0 = both sides the same payout) — breaks ties between lines posted by equally many books."""
    o, u = O._best_price(offer.get("over") or {}), O._best_price(offer.get("under") or {})
    if not o or not u:
        return 9.0
    return abs(O.american_to_decimal(o[1]) - O.american_to_decimal(u[1]))


def best_lines(offers: Sequence[Dict], player: str, columns: Iterable[Tuple[str, str]]) -> Dict[str, Dict]:
    """Per column key, the line to show for `player`: {"point", "over": (book, price) | None, "under": ..., "books"}.

    A player can have several lines in one market (28.5 at some books, 27.5 at others); the line posted by the most
    books wins, ties going to the more balanced one, then the lower number. Over / under are the BEST price any book
    offers on THAT line. Columns with no market, or a market the player has no line in, are simply absent."""
    target = norm_name(player)
    by_market: Dict[str, List[Dict]] = {}
    for off in offers or []:
        if norm_name(off.get("player")) == target:
            by_market.setdefault(off.get("market"), []).append(off)
    out: Dict[str, Dict] = {}
    for key, _ in columns:
        market = COLUMN_MARKETS.get(key)
        cands = by_market.get(market) or []
        if not cands:
            continue
        pick = min(cands, key=lambda o: (-_book_count(o), _balance(o), o.get("point") if o.get("point") is not None else 1e9))
        over, under = O._best_price(pick.get("over") or {}), O._best_price(pick.get("under") or {})
        out[key] = {"point": float(pick["point"]), "over": over, "under": under, "books": _book_count(pick)}
    return out


def lines_from(best: Dict[str, Dict]) -> Dict[str, float]:
    """{column key: line} out of best_lines() — what the hit-rate row measures against."""
    return {k: v["point"] for k, v in best.items()}


def fmt_price(price) -> str:
    """American odds with an explicit sign: +294, -115."""
    try:
        p = float(price)
    except (TypeError, ValueError):
        return "—"
    return f"{p:+.0f}"


def fetch_offers(api_key: str, event: Dict, markets: Sequence[str], sport: str) -> Tuple[List[Dict], Optional[str]]:
    """One game's offers for `markets` — ONE request, billed one credit per market. (offers, error): an API failure
    comes back as a message (and no offers) rather than an exception, so the page can say so and carry on."""
    try:
        data, _hdr = O.fetch_event_props(event["id"], api_key, list(markets), sport=O.feed_for(event, sport))
    except O.OddsAPIError as exc:
        return [], str(exc)
    except Exception as exc:                                              # noqa: BLE001 — never let one bad response sink the page
        return [], f"{type(exc).__name__}: {exc}"
    return O.parse_event_offers(data or {}, supported_markets=list(markets)), None


# --------------------------------------------------------------------------- why a market has no lines (Oct 31)
LINE_STATUS_TEXT = {
    "started": ("🔒", "This game has already started — the books take their pregame player props down at kickoff, so "
                     "there's nothing to load. The projections below still show what the model expected."),
    "unmatched": ("⚠️", "The books' game list didn't match this game's team names, so no lines could be loaded. "
                        "That's a platform issue worth flagging (send the matchup); meanwhile you can type lines in."),
    "not_posted": ("🕐", "The books have this game but haven't posted {market} props for it yet. Smaller games often get "
                        "props late in the afternoon, for only a few players, or not at all — press 🔄 Refresh book "
                        "lines closer to kickoff, or type your own."),
    "not_loaded": ("🕐", "Book lines aren't loaded — turn on **Load book lines automatically** or press 🔄 Refresh "
                        "book lines (or type your own)."),
    "no_key": ("🔑", "No Odds API key is set on this deployment, so lines can't be loaded — type your own."),
    "error": ("⚠️", "The books couldn't be reached just now ({detail}). Try 🔄 Refresh book lines in a minute."),
}


def line_status(got: Optional[Dict], kickoff: Optional[str], now=None) -> str:
    """Why a market shows no lines: started / unmatched / not_posted / not_loaded / no_key / error."""
    from datetime import datetime, timezone
    if kickoff:
        try:
            k = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
            if k.tzinfo is None:
                k = k.replace(tzinfo=timezone.utc)
            if (now or datetime.now(timezone.utc)) >= k:
                return "started"
        except ValueError:
            pass
    got = got or {}
    if got.get("no_key"):
        return "no_key"
    err = str(got.get("error") or "")
    if "haven't listed" in err or "didn't match" in err:
        return "unmatched"
    if err:
        return "error"
    if not got:
        return "not_loaded"
    return "not_posted"


def line_status_message(status: str, market: str, got: Optional[Dict] = None) -> Tuple[str, str]:
    icon, text = LINE_STATUS_TEXT.get(status, LINE_STATUS_TEXT["not_posted"])
    return icon, text.format(market=market, detail=str((got or {}).get("error") or "")[:80])
