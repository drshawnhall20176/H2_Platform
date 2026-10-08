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


def match_event(events: Iterable[Dict], home_name: str, away_name: str) -> Optional[Dict]:
    """The Odds API event for a game: the one whose two teams are these two (any order, case-blind). None if absent."""
    want = {str(home_name or "").strip().lower(), str(away_name or "").strip().lower()}
    for e in events or []:
        if {str(e.get("home_team") or "").strip().lower(), str(e.get("away_team") or "").strip().lower()} == want:
            return e
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
