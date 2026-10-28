"""
props_odds.py — the books' read on ONE game for Position Matchups' Player props tab: the spread, total and
moneyline (for the implied team totals and blowout risk) and every posted line for the chosen prop market (for
line shopping and the market blend). One Odds API request per load (billed per market), behind a button.

`game_lines` is pure (unit tested); `fetch_game` is the only network call and never raises: an API failure comes
back as {"error": ...} so the page can say so and carry on with typed numbers.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import odds_api as O
import position_lines as PL
import props_engine as PE

GAME_MARKETS = ["spreads", "totals", "h2h"]


def game_lines(event_json: Dict) -> Dict:
    """{"spread_home" (negative = home favored), "total", "p_home" (no-vig win probability)} from one event's
    spreads / totals / h2h markets, averaged across books. Missing pieces are None."""
    home, away = event_json.get("home_team"), event_json.get("away_team")
    spreads = O.parse_game_spread(event_json)
    total = O.parse_game_total(event_json)
    sh = spreads.get(home)
    if sh is None and spreads.get(away) is not None:
        sh = -spreads[away]
    ml = O.parse_event_moneyline(event_json)
    p_home = None
    per_book = [PE.devig(ml[home][b], ml[away][b]) for b in set(ml.get(home) or {}) & set(ml.get(away) or {})]
    per_book = [p for p in per_book if p is not None]
    if per_book:
        p_home = sum(per_book) / len(per_book)
    return {"spread_home": sh, "total": total, "p_home": p_home, "home_team": home, "away_team": away}


def hockey_spread_from_ml(p_home: Optional[float]) -> Optional[float]:
    """Hockey's puck line is always +/-1.5, so it says little; a goal-margin equivalent comes from the moneyline:
    about 0.5 goals of margin per 10 points of win probability above 50%."""
    if p_home is None:
        return None
    return -(p_home - 0.5) * 5.0


def fetch_game(api_key: str, sport_odds_key: str, home_name: str, away_name: str,
               prop_markets: Sequence[str]) -> Dict:
    """{"offers", "lines" (game_lines), "remaining", "error"} for the game between these two teams."""
    try:
        ev = PL.match_event(O.fetch_events_all(api_key, sport=sport_odds_key), home_name, away_name)
    except Exception as exc:                                                   # noqa: BLE001
        return {"error": f"Couldn't list the games at the books ({type(exc).__name__})."}
    if ev is None:
        return {"error": "The books haven't listed this game yet (or the team names didn't match)."}
    sport = O.feed_for(ev, sport_odds_key)
    markets = list(dict.fromkeys(list(GAME_MARKETS) + [m for m in prop_markets if m]))
    data, hdr, err = None, {}, None
    for attempt in (markets, list(GAME_MARKETS), [m for m in prop_markets if m]):
        if not attempt:
            continue
        try:
            got, hdr = O.fetch_event_props(ev["id"], api_key, attempt, sport=sport)
        except Exception as exc:                                               # noqa: BLE001
            err = str(exc)
            continue
        data = _merge(data, got)
        if attempt is markets:
            break
    if data is None:
        return {"error": f"The books didn't answer ({err})."}
    offers: List[Dict] = O.parse_event_offers(data, supported_markets=[m for m in prop_markets if m])
    return {"offers": offers, "lines": game_lines(data), "remaining": (hdr or {}).get("remaining"), "error": None}


def _merge(a: Optional[Dict], b: Optional[Dict]) -> Dict:
    """Two event responses (game lines, then props) -> one, bookmakers' markets combined."""
    if not a:
        return b or {}
    if not b:
        return a
    out = dict(a)
    books = {bm.get("key"): dict(bm, markets=list(bm.get("markets") or [])) for bm in a.get("bookmakers") or []}
    for bm in b.get("bookmakers") or []:
        if bm.get("key") in books:
            books[bm["key"]]["markets"] += list(bm.get("markets") or [])
        else:
            books[bm.get("key")] = bm
    out["bookmakers"] = list(books.values())
    return out
