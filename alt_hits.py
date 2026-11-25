"""
alt_hits.py — alternate-line hit rates next to the price's break-even (Nov 25, PropSeason scrub item 5).

PropSeason's cheat sheet lists "Embiid 3.5+ rebounds, 14/14" with no price. A hit rate means nothing without one: a
rung priced -900 needs 90% just to break even. Ours puts every rung's last-10 hit rate beside the break-even of its
real price and says which side of it the history falls on.

No new Odds API credits: the long-shot scan already archives each game's alternate prices before tip-off
(long_shots_scan.ALT_ARCHIVE), and tonight's board rows (todays_best.KEY_ALL) carry each player's last 10 games.

History, not a pick: ten games is a small sample, these rungs were never tested as bets, and the model's own read of
the player is the projection shown beside it.
"""
from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional, Tuple

EDGE = 0.10                 # history at least 10 points over break-even reads "above"; within 10 reads "about right"


def implied(price: float) -> float:
    return 100 / (price + 100) if price > 0 else -price / (-price + 100)


def _norm(s) -> str:
    import injury_check as IC
    return IC._norm(s)


def rungs(quotes: Iterable[Dict], rows: Iterable[Dict], alt_map: Dict[str, str], n_games: int = 10) -> List[Dict]:
    """One row per Over rung that has a price and a player on tonight's board with recent games."""
    by: Dict[Tuple[str, str], Dict] = {}
    for r in rows or []:
        mk = r.get("market_key")
        if r.get("player") and mk:
            by.setdefault((_norm(r["player"]), mk), r)
    out, seen = [], set()
    for q in quotes or []:
        main = alt_map.get(q.get("market"))
        if not main or str(q.get("name")).lower() != "over" or q.get("point") is None or q.get("price") is None:
            continue
        r = by.get((_norm(q.get("description")), main))
        if not r:
            continue
        vals = [float(v) for v in list(r.get("values") or [])[:n_games] if v is not None]
        if len(vals) < 5:
            continue
        need = float(q["point"]) + 0.5                          # "Over 7.5" = 8+
        key = (r["player"], main, need)
        if key in seen:
            continue
        seen.add(key)
        price = float(q["price"])
        hits = sum(1 for v in vals if v >= need)
        rate, be = hits / len(vals), implied(price)
        out.append({"player": r["player"], "team": r.get("team"), "game": r.get("game") or "", "time": r.get("time") or "",
                    "market": r.get("market") or main, "rung": f"{need:g}+ {r.get('market') or main}", "need": need,
                    "price": price, "hits": hits, "games": len(vals), "rate": rate, "break_even": be,
                    "margin": rate - be, "projection": r.get("projection"), "main_line": r.get("line")})
    return out


def verdict(margin: float) -> str:
    if margin >= EDGE:
        return "History above break-even"
    if margin <= -EDGE:
        return "History below break-even"
    return "Priced about right"


def table(rs: Iterable[Dict], parse_time: Optional[Callable] = None) -> List[Dict]:
    """Display rows: earliest start first, then the biggest margin over break-even."""
    def key(r):
        t = None
        if parse_time is not None:
            try:
                t = parse_time(r.get("time"))
            except Exception:                                   # noqa: BLE001
                t = None
        return (t is None, str(t or r.get("time") or ""), -r["margin"])
    return [{"Time": r["time"], "Player": r["player"], "Rung": r["rung"], "Price": f"{r['price']:+.0f}",
             "Last 10": f"{r['hits']}/{r['games']}", "Hit rate": r["rate"], "Break-even": r["break_even"],
             "History vs price": verdict(r["margin"]),
             "Projection": "—" if r.get("projection") is None else f"{float(r['projection']):.1f}",
             "Game": r["game"]} for r in sorted(rs, key=key)]


def for_day(sport: str, day: str, rows: List[Dict], load_odds: Optional[Callable] = None) -> List[Dict]:
    """Every game's archived alternate prices against tonight's board rows."""
    import long_shots as LS
    import long_shots_scan as LSS
    alt_map = (LS.SPORTS.get(sport) or {}).get("alt") or {}
    if not alt_map:
        return []
    if load_odds is None:
        import model_store as MS
        load_odds = lambda h, a: MS.load_odds(sport, day, h, a, LSS.ALT_ARCHIVE)   # noqa: E731
    out = []
    for game in sorted({r.get("game") for r in rows or [] if " @ " in str(r.get("game") or "")}):
        away, home = game.split(" @ ", 1)
        try:
            quotes = ((load_odds(home, away) or {}).get("offers")) or []
        except Exception:                                       # noqa: BLE001
            quotes = []
        out += rungs(quotes, [r for r in rows if r.get("game") == game], alt_map)
    return out


CAPTION = ("Last 10: how many of his last 10 games reached the rung. Break-even: the hit rate the price needs to pay "
           "off. History above break-even means the last 10 games beat the price by 10+ points — a small sample, and "
           "these rungs were never tested as bets, so it's history, not a pick. Prices: the alternate lines the "
           "long-shot scan saved before tip-off.")
