"""
odds_api.py — The Odds API client + edge calculation.

Fetches MLB player-prop odds and joins them to the model's projection index to compute
true edge: the model probability evaluated AT THE BOOK'S LINE, compared to a de-vigged
market price.

Key handling: the API key is passed IN as an argument (the page reads it from
st.secrets / env). This module never stores, logs, or hardcodes it.

Quota: player props cost 1 unit per market per event. fetch_slate_props pulls all
requested markets for each slate event in a single request each, and returns the
remaining-quota header so the UI can warn you.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

BASE = "https://api.the-odds-api.com/v4"
SPORT = "baseball_mlb"

# The model's markets, expressed as Odds API market keys.
SUPPORTED_MARKETS = [
    "batter_home_runs", "batter_total_bases", "batter_hits", "batter_strikeouts",
    "pitcher_strikeouts", "pitcher_outs", "pitcher_walks",
]


# ---- odds math -------------------------------------------------------------
def american_to_decimal(american: float) -> float:
    a = float(american)
    if a == 0 or not math.isfinite(a):
        return 1.0  # invalid/zero odds -> no payout (safe sentinel, never divides by zero)
    return 1 + (a / 100 if a > 0 else 100 / (-a))


def implied_prob(american: float) -> float:
    return (-american) / ((-american) + 100) if american < 0 else 100 / (american + 100)


def ev_percent(prob: float, american: float) -> float:
    """Expected value per $1 staked, as a percent. +5 means +5% EV."""
    return (prob * american_to_decimal(american) - 1) * 100


def devig_two_way(over_american: float, under_american: float) -> Optional[float]:
    """Return the no-vig (fair) probability of the OVER from a book's two-sided prices."""
    io, iu = implied_prob(over_american), implied_prob(under_american)
    total = io + iu
    return io / total if total > 0 else None


# ---- API client ------------------------------------------------------------
class OddsAPIError(Exception):
    pass


def _get(path: str, params: Dict) -> Tuple[Dict, Dict]:
    try:
        r = requests.get(f"{BASE}/{path}", params=params, timeout=20)
    except requests.RequestException as e:
        raise OddsAPIError(f"network error: {e}") from e
    if r.status_code == 401:
        raise OddsAPIError("401 Unauthorized — check your API key.")
    if r.status_code == 429:
        raise OddsAPIError("429 — out of quota for this period.")
    if r.status_code != 200:
        raise OddsAPIError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json(), {
        "remaining": r.headers.get("x-requests-remaining"),
        "used": r.headers.get("x-requests-used"),
    }


def fetch_events(api_key: str, sport: str = SPORT) -> List[Dict]:
    data, _ = _get(f"sports/{sport}/events", {"apiKey": api_key, "dateFormat": "iso"})
    return data if isinstance(data, list) else []


def fetch_event_props(event_id: str, api_key: str, markets: List[str],
                      regions: str = "us", sport: str = SPORT) -> Tuple[Dict, Dict]:
    return _get(
        f"sports/{sport}/events/{event_id}/odds",
        {"apiKey": api_key, "regions": regions, "markets": ",".join(markets),
         "oddsFormat": "american", "dateFormat": "iso"},
    )


# ---- parsing ---------------------------------------------------------------
def parse_event_offers(event_json: Dict, supported_markets: Optional[List[str]] = None) -> List[Dict]:
    """Collapse all bookmakers into per-(market, player, line) offers with both sides.

    `supported_markets` filters to the model's markets — defaults to MLB's SUPPORTED_MARKETS;
    the sport registry passes each sport's own list.

    Returns list of dicts:
      {market, player, point, over:{book:price}, under:{book:price}}
    """
    offers: Dict[Tuple, Dict] = {}
    markets_allowed = supported_markets if supported_markets is not None else SUPPORTED_MARKETS
    for bm in event_json.get("bookmakers", []):
        book = bm.get("key", "?")
        for mk in bm.get("markets", []):
            mkey = mk.get("key")
            if mkey not in markets_allowed:
                continue
            for oc in mk.get("outcomes", []):
                player = oc.get("description")
                point = oc.get("point")
                side = (oc.get("name") or "").lower()
                price = oc.get("price")
                if player is None or point is None or price is None:
                    continue
                k = (mkey, player, point)
                slot = offers.setdefault(k, {"market": mkey, "player": player,
                                             "point": point, "over": {}, "under": {}})
                if side.startswith("o"):
                    slot["over"][book] = price
                elif side.startswith("u"):
                    slot["under"][book] = price
    return list(offers.values())


# ---- edge computation ------------------------------------------------------
def _best_price(book_prices: Dict[str, float]) -> Optional[Tuple[str, float]]:
    """Best (highest decimal payout) price across books for one side."""
    if not book_prices:
        return None
    book, price = max(book_prices.items(), key=lambda kv: american_to_decimal(kv[1]))
    return book, price


def parse_game_spread(event_json: Dict) -> Dict[str, float]:
    """{team_name: spread} for one game's "spreads" market, averaged across books that post it.
    Negative = favorite, positive = underdog — the Odds API's own convention. This is a separate,
    purpose-built parser from parse_event_offers: a spreads market's outcomes are shaped
    differently from a player prop's (one point per TEAM, identified by `name`, with no
    over/under split and no `description` field), so forcing it through parse_event_offers would
    silently drop every outcome rather than parse them. Returns {} if no bookmaker posted a
    spreads market for this event."""
    samples: Dict[str, List[float]] = {}
    for bm in event_json.get("bookmakers", []):
        for mk in bm.get("markets", []):
            if mk.get("key") != "spreads":
                continue
            for oc in mk.get("outcomes", []):
                team = oc.get("name")
                point = oc.get("point")
                if team is None or point is None:
                    continue
                samples.setdefault(team, []).append(point)
    return {team: sum(pts) / len(pts) for team, pts in samples.items()}


def fetch_slate_spreads(date_str: str, api_key: str, sport: str = SPORT) -> Tuple[Dict[str, float], Dict]:
    """{team_name: spread} for every team playing on date_str, plus (info) with remaining quota —
    same (result, info) contract as fetch_slate_props so pages can show cost the same way. Only
    the "spreads" market is requested (1 unit/event, far cheaper than the 4-market player-prop
    fetch), since this exists for game-level blowout-risk context, not player pricing — pages
    that need both call this separately from fetch_slate_props rather than this function trying
    to do double duty."""
    events = fetch_events(api_key, sport=sport)
    todays = [e for e in events if str(e.get("commence_time", ""))[:10] == date_str]
    spreads: Dict[str, float] = {}
    remaining = None
    fetched = 0
    for e in todays:
        try:
            ej, hdr = fetch_event_props(e["id"], api_key, ["spreads"], sport=sport)
        except OddsAPIError:
            continue
        remaining = hdr.get("remaining") or remaining
        spreads.update(parse_game_spread(ej))
        fetched += 1
    return spreads, {"events_total": len(todays), "events_fetched": fetched, "remaining": remaining}


def market_lines_for_player(offers: List[Dict], player_name: str, projections_module=None) -> Dict[str, float]:
    """{market_key: point} — the actual sportsbook prop line(s) for one player, picked from
    `offers` (already fetched via fetch_slate_props). This is a display/reference lookup, distinct
    from compute_edges (which prices every offer against the model) — for a page like Matchup Lab
    that just wants "what's the line on her tonight" for a trend chart, not a full edge board.

    Matches by normalize_name (sport-specific, same as compute_edges) so a book's spelling of a
    player's name doesn't cause a miss. `projections_module` supplies normalize_name for the
    sport, same convention as compute_edges — defaults to MLB's if not given.

    If a market has offers at more than one point (different books posting different numbers),
    the point backed by the MOST total book quotes (over+under combined) wins — a simple, honest
    proxy for market consensus, not a claim of a more sophisticated line-shopping model. A market
    with no matching offer is just absent from the result, not a fabricated guess."""
    if projections_module is None:
        import projections as projections_module
    P = projections_module
    target = P.normalize_name(player_name)
    best: Dict[str, Tuple[float, int]] = {}   # market -> (point, book_count) with the highest book_count so far
    for off in offers:
        if P.normalize_name(off.get("player", "")) != target:
            continue
        mkey = off.get("market")
        point = off.get("point")
        if mkey is None or point is None:
            continue
        book_count = len(off.get("over") or {}) + len(off.get("under") or {})
        if book_count == 0:
            continue
        cur = best.get(mkey)
        if cur is None or book_count > cur[1]:
            best[mkey] = (point, book_count)
    return {mkey: point for mkey, (point, _cnt) in best.items()}


def compute_edges(index: Dict, offers: List[Dict],
                  projections_module=None) -> Tuple[List[Dict], Dict]:
    """Join book offers to the model index and compute EV/edge per playable side.

    `projections_module` supplies normalize_name for the sport — defaults to MLB's projections;
    the sport registry passes each sport's own module. Returns (edge_rows, stats), EV%-sorted."""
    if projections_module is None:
        import projections as projections_module
    P = projections_module
    rows: List[Dict] = []
    matched = unmatched = 0

    for off in offers:
        mkey, point = off["market"], off["point"]
        nm = P.normalize_name(off["player"])
        entry = index.get((nm, mkey))
        if entry is None:
            unmatched += 1
            continue
        matched += 1
        dist = entry["dist"]

        # Consensus no-vig prob of the OVER (averaged across books offering both sides).
        novig_overs = []
        for book in set(off["over"]) & set(off["under"]):
            nv = devig_two_way(off["over"][book], off["under"][book])
            if nv is not None:
                novig_overs.append(nv)
        novig_over = sum(novig_overs) / len(novig_overs) if novig_overs else None

        for side, prices in (("Over", off["over"]), ("Under", off["under"])):
            bp = _best_price(prices)
            if bp is None:
                continue
            book, price = bp
            model_p = P.prob_for_side(dist, point, side)
            novig_side = (novig_over if side == "Over" else (1 - novig_over)) if novig_over is not None else None
            rows.append({
                "Player": entry["ctx"]["player"],
                "Team": entry["ctx"]["team"],
                "Game": entry["ctx"]["game"],
                "Market": mkey,
                "Side": side,
                "Line": point,
                "ModelProb": round(model_p, 4),
                "Proj": round(entry["mean"], 2),
                "Book": book,
                "Price": price,
                "ImpliedBest": round(implied_prob(price), 4),
                "NoVigMkt": round(novig_side, 4) if novig_side is not None else None,
                "EdgeVsMkt": round(model_p - novig_side, 4) if novig_side is not None else None,
                "EV%": round(ev_percent(model_p, price), 2),
            })

    rows.sort(key=lambda r: r["EV%"], reverse=True)
    return rows, {"matched": matched, "unmatched": unmatched}


def fetch_slate_props(date_str: str, api_key: str, markets: List[str], sport: str = SPORT) -> Tuple[List[Dict], Dict]:
    """Pull props for every event on the slate date. Returns (offers, info).

    info includes remaining quota and event counts so the UI can show cost."""
    events = fetch_events(api_key, sport=sport)
    todays = [e for e in events if str(e.get("commence_time", ""))[:10] == date_str]
    offers: List[Dict] = []
    remaining = None
    fetched = 0
    for e in todays:
        try:
            ej, hdr = fetch_event_props(e["id"], api_key, markets, sport=sport)
        except OddsAPIError:
            continue
        remaining = hdr.get("remaining") or remaining
        offers.extend(parse_event_offers(ej, supported_markets=markets))
        fetched += 1
    return offers, {"events_total": len(todays), "events_fetched": fetched,
                    "remaining": remaining}


# ---- Kelly stake sizing ----------------------------------------------------
def kelly_fraction(prob: float, american: float) -> float:
    """Full-Kelly fraction of bankroll for a bet at these odds. 0 if no edge or bad inputs.

    f* = (p*d - 1) / (d - 1), where d is decimal odds. This is the stake that maximizes
    long-run bankroll growth IF your probability is exactly right."""
    try:
        p, a = float(prob), float(american)
    except (TypeError, ValueError):
        return 0.0
    if not (0.0 < p < 1.0) or not math.isfinite(a) or a == 0:
        return 0.0  # missing/garbage odds or probability -> no bet
    d = american_to_decimal(a)
    b = d - 1
    if b <= 0:
        return 0.0
    return max((p * d - 1) / b, 0.0)


def kelly_stake(prob: float, american: float, bankroll: float,
                fraction: float = 0.25, cap_pct: float = 0.05) -> float:
    """Recommended dollar stake using FRACTIONAL Kelly, capped at cap_pct of bankroll.

    Why fractional + capped: full Kelly assumes your probability is exact. Model
    probabilities are noisy, so betting full Kelly overbets and risks ruin when an edge is
    mis-estimated. Quarter-Kelly (0.25) with a hard per-bet cap is the standard discipline."""
    f = min(kelly_fraction(prob, american) * fraction, cap_pct)
    return round(max(f, 0.0) * bankroll, 2)
