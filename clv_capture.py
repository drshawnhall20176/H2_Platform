"""
clv_capture.py — match open bets to live odds so closing lines can be captured automatically.

The engine is pure and testable: given your open bets and the current odds offers (from
odds_api.parse_event_offers), it returns the price at the SAME book you bet, for the same
player / market / side / line. The runner (capture_closing_lines.py) calls this on a timer
and writes the latest pre-game price into each open bet as its closing line.

Apples-to-apples is the rule: CLV only means something if the close comes from the same book
you took the bet at, so a bet with no book recorded is skipped (reported, not guessed).
"""

from __future__ import annotations

from typing import Dict, List, Optional

# Bet Log display market -> Odds API market key.
# EXPANDED to all 17 real MLB markets, matching projections.MLB_MARKET_TO_ODDS_KEY exactly.
# The original 7 meant that bets on HRR, Walks, RBIs, Runs, Singles, Doubles, Triples, Walks,
# Pitcher Earned Runs, and Pitcher Hits Allowed NEVER got a closing line captured -- they'd
# silently land in capture_updates' no_match list on every run, with no error, no explanation.
MARKET_TO_ODDS_KEY = {
    "Batter HR":              "batter_home_runs",
    "Batter Total Bases":     "batter_total_bases",
    "Batter Total Hits":      "batter_hits",
    "Batter Strikeouts":      "batter_strikeouts",
    "Batter Runs":            "batter_runs_scored",
    "Batter RBIs":            "batter_rbis",
    "Batter Stolen Bases":    "batter_stolen_bases",
    "Batter Singles":         "batter_singles",
    "Batter Doubles":         "batter_doubles",
    "Batter Triples":         "batter_triples",
    "Batter Walks":           "batter_walks",
    "Batter Hits+Runs+RBIs":  "batter_hits_runs_rbis",
    "Pitcher Strikeouts":     "pitcher_strikeouts",
    "Pitcher Outs":           "pitcher_outs",
    "Pitcher Walks":          "pitcher_walks",
    "Pitcher Earned Runs":    "pitcher_earned_runs",
    "Pitcher Hits Allowed":   "pitcher_hits_allowed",
}


def _norm(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum())


# Markets with a single fixed line (point is always 0.5), matched WITHOUT comparing the point.
# MLB default; the sport registry passes each sport's own set (e.g. NFL anytime-TD).
_MLB_SINGLE_LINE = {"batter_home_runs"}


# Nov 18 (research/close_gap.py): only 72 of 424 November bets had a closing price. Bets logged under the model's short
# market names ("PRA", "RA") matched nothing in the display-name map; long shots sit on the alternate ladder, which
# was never fetched; and game lines (spreads, totals, moneylines) had no capture at all.
_SHORT = {"PRA": "Pts+Reb+Ast", "PR": "Pts+Reb", "PA": "Pts+Ast", "RA": "Reb+Ast", "3PM": "Threes Made",
          "Threes": "Threes Made", "SOG": "Shots on Goal"}
GAME_KEYS = {"Spread": "spreads", "Puck Line": "spreads", "Run Line": "spreads", "Total": "totals",
             "Moneyline": "h2h"}


def odds_key(market: Optional[str], mmap: Dict) -> Optional[str]:
    if not market:
        return None
    return mmap.get(market) or mmap.get(_SHORT.get(market, "")) or \
        next((v for k, v in mmap.items() if _norm(k) == _norm(market)), None)


def alternates(keys) -> List[str]:
    return [k + "_alternate" for k in keys if k.startswith("player_") or k.startswith("batter_")]


def parse_game_offers(event_json: Dict) -> List[Dict]:
    """Game-line outcomes from one event's odds: {market, name, point, prices: {book: price}, home, away}."""
    import odds_api as _O
    out: Dict = {}
    for bm in event_json.get("bookmakers", []) or []:
        book = _O.canonical_book(bm.get("key", "?")) or "?"
        for mk in bm.get("markets", []) or []:
            if mk.get("key") not in ("h2h", "spreads", "totals"):
                continue
            for oc in mk.get("outcomes", []) or []:
                k = (mk["key"], oc.get("name"), oc.get("point"))
                slot = out.setdefault(k, {"market": mk["key"], "name": oc.get("name"), "point": oc.get("point"),
                                          "prices": {}, "home": event_json.get("home_team"),
                                          "away": event_json.get("away_team")})
                if oc.get("price") is not None:
                    slot["prices"][book] = oc["price"]
    return list(out.values())


def _team_in(name: Optional[str], text: Optional[str]) -> bool:
    a, b = _norm(name), _norm(text)
    return bool(a) and bool(b) and (a in b or b in a)


def game_close_price(bet: Dict, offers: List[Dict]) -> Optional[int]:
    """Latest price at the bet's own book for a spread / total / moneyline bet ("game": "Away @ Home")."""
    import odds_api as _O
    gkey = GAME_KEYS.get(bet.get("market"))
    book = _O.canonical_book(bet.get("book"))
    if not gkey or not book:
        return None
    parts = [x.strip() for x in str(bet.get("game") or "").split("@")]
    if len(parts) != 2:
        return None
    away, home = parts
    side = str(bet.get("side") or "")
    line = bet.get("line")
    for o in offers:
        if o["market"] != gkey or not (_team_in(home, o.get("home")) and _team_in(away, o.get("away"))):
            continue
        if gkey == "totals":
            if str(o.get("name") or "").lower() != side.lower():
                continue
        else:
            team = side if side and side.lower() not in ("home", "away") else bet.get("player")
            if side.lower() == "home":
                team = o.get("home")
            elif side.lower() == "away":
                team = o.get("away")
            if not _team_in(team, o.get("name")):
                continue
        if gkey != "h2h" and (line is None or o.get("point") is None or abs(float(o["point"]) - float(line)) > 1e-9):
            continue
        p = o["prices"].get(book)
        if p is not None:
            return int(p)
    return None


def _side_key(side: str) -> Optional[str]:
    s = (side or "").strip().lower()
    if s.startswith("o") or s == "yes":
        return "over"
    if s.startswith("u") or s == "no":
        return "under"
    return None


def bet_close_price(bet: Dict, offers: List[Dict], market_map: Optional[Dict] = None,
                    single_line_markets: Optional[set] = None) -> Optional[int]:
    """Latest price for this bet at its own book, or None if no clean match.

    `market_map` maps the bet's display market -> Odds API key (defaults to MLB's).
    `single_line_markets` are keys matched without comparing the point (defaults to MLB's HR).
    The sport registry passes each sport's own values.

    `offers` are odds_api.parse_event_offers() dicts:
      {market, player, point, over:{book:price}, under:{book:price}}
    Only offers from NOT-yet-started games should be passed in (the runner enforces this),
    so any match is by definition a live pre-game price."""
    mmap = market_map if market_map is not None else MARKET_TO_ODDS_KEY
    singles = single_line_markets if single_line_markets is not None else _MLB_SINGLE_LINE
    okey = odds_key(bet.get("market"), mmap)
    import odds_api as _O
    book = _O.canonical_book(bet.get("book"))   # "caesars" (old logs) -> the API's "williamhill_us"
    side = _side_key(bet.get("side"))
    if not okey or not book or side is None:
        return None

    bplayer = _norm(bet.get("player"))
    bline = bet.get("line")
    is_single = okey in singles          # single-line market; ignore point in matching

    for off in offers:                  # Nov 18: the alternate ladder too (long shots sit off the main line)
        if off.get("market") not in (okey, okey + "_alternate") or _norm(off.get("player")) != bplayer:
            continue
        if not is_single and bline is not None and off.get("point") != bline:
            continue
        prices = off.get(side) or {}
        for bk, price in prices.items():
            if bk.strip().lower() == book:
                return int(price)
    return None


def capture_updates(open_bets: List[Dict], offers: List[Dict], market_map: Optional[Dict] = None,
                    single_line_markets: Optional[set] = None, game_offers: Optional[List[Dict]] = None) -> Dict:
    """Return {bet_id: close_price} for every open bet that matched a current offer,
    plus a small report of what couldn't be matched and why. Market map / single-line set are
    passed through per sport (MLB defaults)."""
    updates, no_book, no_match = {}, [], []
    for b in open_bets:
        if not (b.get("book") or "").strip():
            no_book.append(b.get("id"))
            continue
        price = game_close_price(b, game_offers or []) if b.get("market") in GAME_KEYS else \
            bet_close_price(b, offers, market_map=market_map, single_line_markets=single_line_markets)
        if price is not None:
            updates[b["id"]] = price
        else:
            no_match.append(b.get("id"))
    return {"updates": updates, "no_book": no_book, "no_match": no_match}
