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


def parse_event_moneyline(event_json: Dict) -> Dict[str, Dict[str, float]]:
    """{team_name: {book: price}} for one event's "h2h" (moneyline) market -- keeping EVERY
    book's own price, a genuinely different parser from parse_game_spread just above (which
    averages across books into a single display number). A real price LOOKUP needs the specific
    preferred-book price or the best available across books, not an average nobody can actually
    bet at.

    h2h outcomes have NO `point` at all (moneyline isn't a line-based market the way spreads/
    totals are) -- oc.get("name") IS the team name itself, unlike a player-prop outcome where
    `name` is Over/Under and `description` carries the player. Forcing h2h through
    parse_event_offers (which requires a non-None point) would silently drop every outcome."""
    by_team: Dict[str, Dict[str, float]] = {}
    for bm in event_json.get("bookmakers", []):
        book = bm.get("key", "?")
        for mk in bm.get("markets", []):
            if mk.get("key") != "h2h":
                continue
            for oc in mk.get("outcomes", []):
                try:
                    team = oc.get("name")
                    price = oc.get("price")
                    if team is None or price is None:
                        continue
                    by_team.setdefault(team, {})[book] = float(price)
                except Exception as e:  # noqa: BLE001
                    # A shape surprise on ONE outcome must never take down the whole parse --
                    # print the real raw entry so the actual live shape is visible in the next
                    # log, and keep going rather than losing every other real price over one bad
                    # record. Same posture search_players' own hardening already established
                    # for exactly this kind of unverified-live-response risk.
                    print(f"[parse_event_moneyline] skipped one malformed outcome: "
                         f"{type(e).__name__}: {e} -- raw entry: {oc!r}")
                    continue
    return by_team


def fetch_slate_moneylines(date_str: str, api_key: str,
                           sport: str = SPORT) -> Tuple[Dict[str, Dict[str, float]], Dict]:
    """{team_name: {book: price}} for every team playing on date_str, plus (info) with remaining
    quota -- same (result, info) contract as fetch_slate_spreads, just keeping per-book
    granularity instead of an averaged display number, since a real price lookup needs a
    specific, actually-bettable price.

    sport: any Odds API sport key -- deliberately sport-agnostic, not MLB-specific. Moneylines
    exist the same way (an "h2h" market) across every sport this platform covers, so this one
    function serves all of them, not a copy per sport."""
    events = fetch_events(api_key, sport=sport)
    todays = [e for e in events if _eastern_date_str(e.get("commence_time")) == date_str]
    moneylines: Dict[str, Dict[str, float]] = {}
    remaining = None
    fetched = 0
    for e in todays:
        try:
            ej, hdr = fetch_event_props(e["id"], api_key, ["h2h"], sport=sport)
        except OddsAPIError:
            continue
        remaining = hdr.get("remaining") or remaining
        for team, book_prices in parse_event_moneyline(ej).items():
            moneylines.setdefault(team, {}).update(book_prices)
        fetched += 1
    return moneylines, {"events_total": len(todays), "events_fetched": fetched, "remaining": remaining}


def real_moneyline_price(moneylines: Dict[str, Dict[str, float]], team_name: str,
                         preferred_book: Optional[str] = None) -> Optional[Tuple[float, str]]:
    """The REAL moneyline price (American odds) for one team, picked from `moneylines` (already
    fetched via fetch_slate_moneylines) -- the team-level counterpart to real_entry_price's own
    player-prop lookup, added for the same real reason: quick_log.py's Fair-odds fallback meant
    a moneyline pick's entry_odds was always the model's own theoretical price, never a real
    captured one, the same measurement gap real_entry_price closed for player props.

    Same preferred_book resolution as real_entry_price: the exact price at preferred_book when
    that book posted this team's moneyline, otherwise the single BEST (highest-payout) price
    across every book that did.

    TEAM NAME MATCHING is a simple, lightly-normalized exact match (lowercased, whitespace-
    stripped) -- deliberately NOT the same abbreviation-tolerant matching bet_settlement.py's own
    game-label fix needed. That fix existed because a PERSON free-typed a game label into a form
    (with a placeholder that taught abbreviations). Here, neither side of the comparison is
    user-typed: both the play's own team name (from the sport's own schedule data) and the Odds
    API's own event data are already real, canonical team names -- an exact-ish match is the
    right level of tolerance, not a full abbreviation table repeated per sport.

    Returns (price, book), or None if this team has no real moneyline offer at all right now."""
    try:
        target = (team_name or "").strip().lower()
        if not target:
            return None
        book_prices = None
        for team, prices in (moneylines or {}).items():
            if not isinstance(prices, dict):
                print(f"[real_moneyline_price] skipped a non-dict price entry for team "
                     f"{team!r}: {type(prices)} -- {prices!r}")
                continue
            if (team or "").strip().lower() == target:
                book_prices = prices
                break
        if not book_prices:
            return None
        if preferred_book and preferred_book in book_prices:
            return float(book_prices[preferred_book]), preferred_book
        picked = _best_price(book_prices)
        if picked is None:
            return None
        book, price = picked
        return float(price), book
    except Exception as e:  # noqa: BLE001
        # Same posture as search_players' own hardening: a live data-shape surprise here must
        # degrade to "no real price found" (the same honest fallback this function already has
        # for a genuine no-match), never crash the page a bet is being logged from. Confirmed
        # as a real, not hypothetical, risk: a live deploy hit a TypeError inside this exact
        # code path, past where the original (unguarded) version had no protection at all.
        print(f"[real_moneyline_price] unexpected error for team={team_name!r}: "
             f"{type(e).__name__}: {e}")
        return None


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


def real_entry_price(offers: List[Dict], player_name: str, market_key: str, side: str,
                     preferred_book: Optional[str] = None,
                     projections_module=None) -> Optional[Tuple[float, float, str]]:
    """The REAL sportsbook price (American odds) for one player's specific market/side, picked
    from `offers` (already fetched via fetch_slate_props) -- what a bet's entry_odds SHOULD be
    when a real book price is available, instead of falling back to the model's own theoretical
    Fair odds. Added directly to close a real, confirmed gap: quick_log.py's own Fair-odds
    fallback meant entry_odds was always mathematically derived from the SAME probability CLV
    was supposed to be checking against a real captured price -- comparing model_prob's own
    price against the closing line isn't really measuring "did we get a good price," it's
    measuring "did the model's own belief end up on the right side of where the market closed."
    Confirmed directly against a real bet log export: every single tracked bet showed a priced
    edge of well under 0.1 percentage points versus its own stated model_prob -- not a small real
    edge, a tautology.

    Returns (price, point, book) -- the real price, the real point/line that price was posted at
    (which may differ slightly from the bet's own logged line if the book's number has since
    moved), and which book it came from -- or None if this player/market/side has no real book
    offer right now at all. Common well before a slate posts real props, or for a lower-profile
    game/player a book hasn't priced yet -- the honest degradation quick_log.py falls back to
    Fair odds for, same as always, just now the LAST resort instead of the ONLY option.

    MATCHING: same normalize_name convention as market_lines_for_player/compute_edges, and the
    same book-count tie-break as market_lines_for_player when more than one point is posted for
    this player/market (prefer the point backed by the most total book quotes).

    preferred_book RESOLUTION: same strategy as market_lines_for_slate -- the exact price at
    preferred_book if that book posted this specific market, otherwise the single BEST (highest-
    payout) price across every book that did. Never averages or silently picks an arbitrary book."""
    if projections_module is None:
        import projections as projections_module
    P = projections_module
    target_name = P.normalize_name(player_name)
    side_lower = (side or "").lower()
    if side_lower.startswith("over") or side_lower == "yes":
        side_key = "over"
    elif side_lower.startswith("under"):
        side_key = "under"
    else:
        return None   # a side this function doesn't know how to price (e.g. a future new type)

    best_offer = None
    best_count = -1
    for off in offers:
        if P.normalize_name(off.get("player", "")) != target_name:
            continue
        if off.get("market") != market_key:
            continue
        count = len(off.get("over") or {}) + len(off.get("under") or {})
        if count > best_count:
            best_count = count
            best_offer = off

    if best_offer is None:
        return None
    book_prices = best_offer.get(side_key) or {}
    if not book_prices:
        return None
    point = best_offer.get("point")
    if point is None:
        return None

    if preferred_book and preferred_book in book_prices:
        return float(book_prices[preferred_book]), float(point), preferred_book

    picked = _best_price(book_prices)
    if picked is None:
        return None
    book, price = picked
    return float(price), float(point), book


def real_market_prob(offers: List[Dict], player_name: str, market_key: str, side: str,
                     preferred_book: Optional[str] = None,
                     projections_module=None) -> Optional[float]:
    """The REAL, no-vig market probability of one specific side, for one specific player/market —
    what a play's Conviction/grade SHOULD be measured against when real two-sided book prices
    exist, instead of a hand-typed guess at what's "typical" for the whole market category.

    Added directly to close a real, confirmed gap: BEST_BET_REF (projections.py) is a hardcoded
    dict of reasoned-but-unvalidated estimates ("Batter Total Bases": 0.42, etc.) -- several
    entries are explicitly documented as "reasoned, stated estimates... not empirically fit
    against this platform's own graded history yet." Conviction (model_prob / BEST_BET_REF
    [market]) is described everywhere in this codebase as "this play's real probability is 3.2x
    the MARKET-TYPICAL rate for this prop" -- but the denominator was never actually the real
    market's own rate, it was one person's best guess at it. The exact same class of gap
    real_entry_price closed for entry_odds, one level deeper: now it's the REFERENCE a play gets
    graded against, not just the price shown next to it.

    MATCHING: identical to real_entry_price's own player/market matching (same normalize_name
    convention, same book-count tie-break for the point).

    TWO-SIDED RESOLUTION: uses ONE book's own real prices on BOTH sides (Over AND Under) for a
    genuinely consistent devig — mixing one book's Over price with a DIFFERENT book's Under price
    would blend two different books' own independent vig structures into a number that isn't
    really either book's true market view. Prefers preferred_book when it posted both sides;
    otherwise the first book (by iteration order) that posted both sides. Returns None if no
    single book posted both sides — a one-sided-only offer can't be devigged at all, and this
    function never guesses at what the missing side "probably" costs.

    Returns the no-vig probability of the SPECIFIC side requested (Over probability directly,
    1 - Over probability for Under), or None if there's no real two-sided match at all."""
    if projections_module is None:
        import projections as projections_module
    P = projections_module
    target_name = P.normalize_name(player_name)
    side_lower = (side or "").lower()
    if side_lower.startswith("over") or side_lower == "yes":
        want_over = True
    elif side_lower.startswith("under"):
        want_over = False
    else:
        return None

    best_offer = None
    best_count = -1
    for off in offers:
        if P.normalize_name(off.get("player", "")) != target_name:
            continue
        if off.get("market") != market_key:
            continue
        count = len(off.get("over") or {}) + len(off.get("under") or {})
        if count > best_count:
            best_count = count
            best_offer = off
    if best_offer is None:
        return None

    over_books = best_offer.get("over") or {}
    under_books = best_offer.get("under") or {}
    two_sided_books = set(over_books) & set(under_books)
    if not two_sided_books:
        return None   # no single book posted both sides -- can't devig, never guess

    book = preferred_book if preferred_book in two_sided_books else sorted(two_sided_books)[0]
    over_prob = devig_two_way(over_books[book], under_books[book])
    if over_prob is None:
        return None
    return over_prob if want_over else (1.0 - over_prob)


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
    unmatched_names: List[Dict[str, str]] = []

    for off in offers:
        mkey, point = off["market"], off["point"]
        nm = P.normalize_name(off["player"])
        entry = index.get((nm, mkey))
        if entry is None:
            unmatched += 1
            # The real, actionable fix for a long-open item ("player name mismatches"): a bare
            # count gives no way to know WHICH player/market actually failed to match, so a real
            # mismatch (a book's own spelling differing from the model's roster data) stays
            # invisible and unfixable. Recording the real book-side name here is what lets a
            # person actually add the right alias/fix once a genuine mismatch shows up in a live
            # run, instead of guessing at names that might not even be the ones causing trouble.
            unmatched_names.append({"player": off["player"], "market": mkey})
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
    seen = set()
    deduped_unmatched: List[Dict[str, str]] = []
    for u in unmatched_names:
        key = (u["player"], u["market"])
        if key not in seen:
            seen.add(key)
            deduped_unmatched.append(u)
    return rows, {"matched": matched, "unmatched": unmatched, "unmatched_names": deduped_unmatched}


def fetch_slate_props(date_str: str, api_key: str, markets: List[str], sport: str = SPORT) -> Tuple[List[Dict], Dict]:
    """Pull props for every event on the slate date. Returns (offers, info).

    info includes remaining quota and event counts so the UI can show cost."""
    events = fetch_events(api_key, sport=sport)
    todays = [e for e in events if _eastern_date_str(e.get("commence_time")) == date_str]
    # Raw, unfiltered summary of exactly what the provider's own /events listing returned for
    # today -- the fastest way to confirm or rule out a real external-data limitation (e.g. a
    # same-day doubleheader only getting ONE event entry from the provider for both legs)
    # instead of guessing from downstream symptoms.
    todays_summary = [{"id": e.get("id"), "away": e.get("away_team"), "home": e.get("home_team"),
                       "commence_time": e.get("commence_time")} for e in todays]
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
                    "remaining": remaining, "no_offer_events": no_offer_events,
                    "todays_events": todays_summary}


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
