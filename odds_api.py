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

import pytz
import requests

BASE = "https://api.the-odds-api.com/v4"
SPORT = "baseball_mlb"
NFL_SPORT = "americanfootball_nfl"
_EASTERN = pytz.timezone("US/Eastern")


def _eastern_date_str(iso_utc: Optional[str]) -> Optional[str]:
    """A game's real US/Eastern calendar date (YYYY-MM-DD), not the UTC date its commence_time
    happens to be stamped in. Same conversion sports.game_dt already does elsewhere in this
    codebase (UTC ISO -> US/Eastern) -- reimplemented locally here rather than importing sports
    into this lower-level API-client module, to avoid a new cross-layer dependency for one date
    string. Returns None for missing/malformed input, same fail-soft contract as sports.game_dt."""
    if not iso_utc:
        return None
    try:
        return datetime.fromisoformat(str(iso_utc).replace("Z", "+00:00")).astimezone(_EASTERN).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


# NFL market keys confirmed against The Odds API's own market taxonomy -- same source as the
# MLB keys above. Only the 4 real prop markets the NFL engine currently projects for:
# pass yards, rush yards, receptions, receiving yards. Anytime TD has its own separate key
# (player_anytime_td) but uses a binary market structure (not Over/Under), not wired yet.
NFL_SUPPORTED_MARKETS = [
    "player_pass_yds", "player_rush_yds", "player_receptions", "player_reception_yds",
]

# The model's markets, expressed as Odds API market keys.
# EXPANDED from the original 7 to the full 16, matching sports.py's own _MLB_MARKET_MAP exactly
# -- confirmed directly on request, after a real, reported discrepancy (a Graded Picks play
# showing "Pitcher Strikeouts Under 5.5" for a pitcher whose real DraftKings line was 3.5) traced
# back to this platform's core prop-generation pipeline never having been wired to real odds at
# all, for ANY market -- it always used a fixed per-market placeholder (see config.py's own
# DEFAULT_LINES, which documented this as known, unfinished work). sports.py's own market_map
# already had real Odds API key mappings for all 16, "confirmed directly against the-odds-
# api.com's own live 'Betting Markets' documentation" per its own comment -- this file's own
# SUPPORTED_MARKETS had simply never been expanded to match, so Edge Board itself was also only
# ever pricing 7 of the 16 real markets this platform actually generates picks for.
#
# REAL, HONEST LIMITATION: the 9 markets added here beyond the original 7 (batter_runs_scored,
# batter_rbis, batter_stolen_bases, batter_singles, batter_doubles, batter_triples, batter_walks,
# pitcher_earned_runs, pitcher_hits_allowed) are NOT verified against a live Odds API response
# from this sandbox (no network path to api.the-odds-api.com here) -- confirmed via the
# provider's own documentation, same honest posture as every other externally-documented-but-
# not-live-tested assumption on this platform, but worth a real, deliberate first check once this
# runs somewhere with live access, given the real stakes riding on it.
SUPPORTED_MARKETS = [
    "batter_home_runs", "batter_total_bases", "batter_hits", "batter_strikeouts",
    "batter_runs_scored", "batter_rbis", "batter_stolen_bases", "batter_singles",
    "batter_doubles", "batter_triples", "batter_walks", "batter_hits_runs_rbis",
    "pitcher_strikeouts", "pitcher_outs", "pitcher_walks", "pitcher_earned_runs",
    "pitcher_hits_allowed",
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


# ---- historical (backfill for already-completed games) ---------------------
# A SEPARATE, more expensive product from everything above -- confirmed against the provider's
# own docs (the-odds-api.com/historical-odds-data/ and .../liveapi/guides/v4/), not assumed:
#   - Requires a paid usage plan. A free-tier key gets 401/403 on any /v4/historical/* path even
#     though the exact same key works fine against /v4/sports/... above.
#   - historical event-odds costs 10 credits x [markets requested] x [regions requested], PER
#     EVENT, per snapshot -- ten times this module's own documented live per-event rate ("1 unit
#     per market per event", see this file's own module docstring). Seventeen MLB markets in one
#     call is 170 credits for that one event/snapshot, not 17 -- request only the markets a given
#     event's missing bets actually need, not the sport's full market list.
#   - The historical events-list call's exact cost isn't stated at that same 10x rate in the docs
#     (events endpoints generally are described as cheap/infrequent), but isn't confirmed flat-1
#     either -- backfill_closing_lines.py prints the real x-requests-used header this module's
#     _get() already surfaces after every call, rather than assuming a number here.
#
# Neither function below has been exercised against a live key from this sandbox -- its network
# is allowlisted to a fixed domain set that doesn't include the-odds-api.com, so these follow the
# provider's documented request/response shape exactly but that response shape is, honestly,
# unverified here. backfill_closing_lines.py prints the raw wrapper on the very first call if the
# expected "data" key isn't where it's expected, so a shape surprise is loud and diagnosable
# instead of silently returning zero matches with no explanation.
def fetch_historical_events(api_key: str, date_iso: str, sport: str = SPORT) -> Tuple[object, Dict]:
    """Events as they existed at `date_iso` (ISO8601 UTC) -- resolves this provider's own event
    id for a game that's already been played (the live fetch_events above only returns
    upcoming/in-progress events, never completed ones, so it can't be reused for backfill).

    Pass a date_iso at or after that day's LAST commence_time so every game from that date is
    guaranteed to have already been posted when this snapshot was taken.

    Returns the RAW response (unlike fetch_events, which unwraps to a bare list) -- this
    endpoint's exact wrapper shape is the least-verified assumption in this module (see this
    file's own module-level comment), so the unwrapping and the diagnostic for when it doesn't
    match live here on purpose, in backfill_closing_lines.resolve_events_for_date, the same
    "don't hide an unverified shape assumption inside the client" choice already made for
    fetch_historical_event_props below."""
    return _get(f"historical/sports/{sport}/events", {"apiKey": api_key, "date": date_iso, "dateFormat": "iso"})


def fetch_historical_event_props(event_id: str, api_key: str, markets: List[str], date_iso: str,
                                 regions: str = "us", sport: str = SPORT) -> Tuple[Dict, Dict]:
    """Odds for one event as they stood at `date_iso` -- the historical counterpart to
    fetch_event_props above. Pass the game's REAL commence_time (e.g. from mlb_engine.
    get_schedule's game_date, not a guess) as date_iso: the historical API returns the closest
    snapshot AT OR BEFORE the timestamp given, which by definition is the last pre-game price --
    the same "last update before a game starts becomes that game's closing line" definition
    capture_closing_lines.py already uses for the live capture path, just applied to a moment in
    the past instead of live.

    Returns the RAW response dict (unlike fetch_event_props, which the docs describe as unwrapped)
    -- the historical endpoint wraps the same event-odds shape inside a "data" key alongside
    "timestamp"/"previous_timestamp"/"next_timestamp" snapshot metadata. Callers need
    js.get("data") before handing it to parse_event_offers, and can read js.get("timestamp") to
    confirm how close the returned snapshot actually landed to the requested date_iso."""
    return _get(
        f"historical/sports/{sport}/events/{event_id}/odds",
        {"apiKey": api_key, "regions": regions, "markets": ",".join(markets),
         "oddsFormat": "american", "dateFormat": "iso", "date": date_iso},
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
    todays = [e for e in events if _eastern_date_str(e.get("commence_time")) == date_str]
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


# Real US sportsbook keys as returned by The Odds API (Pro tier), with their display names.
# Confirmed directly against the-odds-api.com's own Bookmaker APIs documentation.
# DraftKings is default because that's the primary book for this platform's own users.
US_BOOKS: Dict[str, str] = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "betmgm": "BetMGM",
    "caesars": "Caesars",
    "betrivers": "BetRivers",
    "fanatics": "Fanatics",
    "bovada": "Bovada",
}
DEFAULT_BOOK = "draftkings"


def books_in_offers(offers: List[Dict]) -> List[str]:
    """Returns a sorted list of Odds API book keys that actually appear in this slate's offers,
    filtered to the ones in US_BOOKS. Used to show only books with real coverage in tonight's
    data rather than the full hardcoded list -- a user can only meaningfully select a book that
    actually posted lines for this slate."""
    seen = set()
    for off in offers:
        for book in list((off.get("over") or {}).keys()) + list((off.get("under") or {}).keys()):
            if book in US_BOOKS:
                seen.add(book)
    # Return in US_BOOKS display order so DraftKings is always first
    return [k for k in US_BOOKS if k in seen]


def market_lines_for_slate(offers: List[Dict], projections_module=None,
                           preferred_book: Optional[str] = None) -> Dict[Tuple[str, str], float]:
    """{(normalized_player_name, market_key): point} for EVERY player in one pass over `offers`
    -- the real, efficient building block behind wiring live sportsbook lines into this
    platform's own CORE prop-generation pipeline (enrich_hitter_rows/build_pitcher_projection_
    rows), not just Edge Board's own display lookup.

    RESOLUTION STRATEGY: prefers the specific book in `preferred_book` (e.g. "draftkings") when
    that book has a line for a given player/market. Falls back to the MINIMUM real line across
    all books when the preferred book doesn't have coverage. This is the right design for a
    per-user sportsbook selector: a user who selects DraftKings gets DK's exact line everywhere
    DK has coverage, and minimum-across-all-books (the most favorable available line) where DK
    doesn't -- never a silent miss that leaves a player on the wrong line.

    WHY MINIMUM AS FALLBACK (not consensus): a real, specific production bug confirmed this.
    The original "most-booked point wins" logic picked 1.5 for Ezequiel Tovar's H+R+RBI when
    DraftKings had him at 0.5 and other books had him at 1.5. A bettor CAN actually bet the 0.5
    line at DraftKings -- the minimum is always the most favorable available line, and therefore
    the one the platform should compute against when no preferred book is set.

    preferred_book: an Odds API book key (e.g. "draftkings", "fanduel") -- see US_BOOKS for the
    full real list. None means minimum-across-all-books for every player/market.

    Same real matching convention as market_lines_for_player and compute_edges: keyed by
    normalize_name. A player/market combo with no real book offer is absent from the result."""
    if projections_module is None:
        import projections as projections_module
    P = projections_module

    preferred: Dict[Tuple[str, str], float] = {}   # entries where preferred_book has coverage
    fallback: Dict[Tuple[str, str], float] = {}    # minimum across all books (fallback)

    for off in offers:
        name = P.normalize_name(off.get("player", ""))
        mkey = off.get("market")
        point = off.get("point")
        if not name or mkey is None or point is None:
            continue
        book_count = len(off.get("over") or {}) + len(off.get("under") or {})
        if book_count == 0:
            continue
        key = (name, mkey)
        point = float(point)

        # Preferred book: use this exact line if the preferred book posted it
        if preferred_book:
            over_books = off.get("over") or {}
            under_books = off.get("under") or {}
            if preferred_book in over_books or preferred_book in under_books:
                cur = preferred.get(key)
                if cur is None or point < cur:   # still take the minimum if same book posts multiple
                    preferred[key] = point

        # Minimum fallback: always track the lowest real line across all books
        cur = fallback.get(key)
        if cur is None or point < cur:
            fallback[key] = point

    # Merge: preferred book's line where available, minimum everywhere else
    result = dict(fallback)
    result.update(preferred)
    return result


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
                "GameTime": entry["ctx"].get("game_date"),
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
    todays = [e for e in events if _eastern_date_str(e.get("commence_time")) == date_str]
    offers: List[Dict] = []
    remaining = None
    fetched = 0
    no_offer_events: List[str] = []
    for e in todays:
        try:
            ej, hdr = fetch_event_props(e["id"], api_key, markets, sport=sport)
        except OddsAPIError:
            continue
        remaining = hdr.get("remaining") or remaining
        event_offers = parse_event_offers(ej, supported_markets=markets)
        if not event_offers:
            # Queried successfully, but nothing came back for the markets asked -- the most
            # common real reason is the game has already started and books pulled pre-game
            # player props (a live pre-game edge no longer exists to compute). This event still
            # counts toward events_fetched below, which is exactly why "Games priced: N" alone
            # can look inconsistent with a game missing from the "Filter by game" list (built
            # from the resulting edge rows, not from this query count) -- surfacing which
            # specific events landed here makes that directly diagnosable instead of a guess.
            label = f"{e.get('away_team', '?')} @ {e.get('home_team', '?')}"
            no_offer_events.append(label)
        offers.extend(event_offers)
        fetched += 1
    return offers, {"events_total": len(todays), "events_fetched": fetched,
                    "remaining": remaining, "no_offer_events": no_offer_events}


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
