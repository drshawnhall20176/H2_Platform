"""
ufc_engine.py — UFC/MMA data layer using The Odds API.

UFC is structurally different from every other sport on this platform:
- No game logs, no box scores, no counting stats
- Events are fights (bout between two fighters), not team games
- Markets are fight-outcome focused: moneyline, fight duration, method of victory
- "Slate" is a fight card — all bouts on a given date

DATA SOURCE: The Odds API (same key as MLB/NFL). Sport key: mma_mixed_martial_arts.
Markets:
  h2h                     = Moneyline (fighter wins the fight)
  totals                  = Fight goes over/under N.5 rounds

Method-of-victory markets (fighter_wins_by_ko_tko/submission/decision) are DELIBERATELY NOT
requested -- confirmed live, not assumed, that The Odds API currently rejects all three with a
real INVALID_MARKET error for MMA. Its own docs state MMA coverage is "fight winner odds, with
more markets on the way," meaning this isn't specific to one event or book; it's the API's
current MMA coverage. Requesting them alongside h2h/totals took the WHOLE request down together
(a real, confirmed bug this fixes) even though h2h/totals themselves are valid and DraftKings
does have them posted. MARKET_LABELS below is kept as-is for when the API adds support -- the
view's own display code already handles a market being absent gracefully (shows "not yet
available" rather than breaking), so re-adding these later is a one-line change back to
UFC_MARKETS, not a rebuild.

build_slate() returns (bouts, meta) matching the platform's cross-sport engine contract,
but bouts have a different shape from player-stat rows:
  {
    "Fighter A": str, "Fighter B": str,
    "GameLabel": str,  # "Fighter A vs. Fighter B"
    "game_date": str,  # ISO UTC commence time
    "event_id": str,   # Odds API event ID for fetching props
    "bout_order": int, # main event = 0, co-main = 1, etc. (derived from order in API)
    "_is_main_event": bool,
  }
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pytz
import requests

from odds_api import OddsAPIError

UFC_SPORT = "mma_mixed_martial_arts"
_EASTERN = pytz.timezone("US/Eastern")


def _eastern_date_str(iso_utc: Optional[str]) -> Optional[str]:
    """A fight card's real US/Eastern calendar date (YYYY-MM-DD), not the UTC date its
    commence_time happens to be stamped in. UFC main cards commonly run 10pm ET or later --
    exactly the window where a raw UTC-date-prefix comparison against an Eastern-context
    date_str silently excludes the event entirely (its commence_time rolls to the next UTC
    calendar day). Same fix/reasoning as odds_api.py's own _eastern_date_str, reimplemented
    locally here rather than importing across modules for one date string."""
    if not iso_utc:
        return None
    try:
        return datetime.fromisoformat(str(iso_utc).replace("Z", "+00:00")).astimezone(_EASTERN).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


# Markets the Odds API supports for UFC.
# h2h is always available; method markets depend on subscription tier.
UFC_MARKETS = [
    "h2h",
    "totals",
    "spreads",          # Nov 7: confirmed live (DraftKings et al.): the point spread, e.g. -3.5 / +3.5
    # fighter_wins_by_ko_tko / fighter_wins_by_submission / fighter_wins_by_decision
    # DELIBERATELY excluded -- see this module's own docstring for the confirmed reasoning
    # (real INVALID_MARKET error, not an assumption).
]

# Human-readable display names for each market
UFC_MARKET_LABELS = {
    "h2h":                       "Moneyline",
    "totals":                    "Fight Duration",
    "spreads":                   "Point Spread",
    "fighter_wins_by_ko_tko":    "Win by KO/TKO",
    "fighter_wins_by_submission":"Win by Submission",
    "fighter_wins_by_decision":  "Win by Decision",
}

_BASE = "https://api.the-odds-api.com/v4"
_TIMEOUT = 20


def _get(path: str, params: Dict) -> Tuple[Any, Dict]:
    """Raw GET against The Odds API. Returns (json_body, headers). Raises OddsAPIError with a
    real, descriptive message on failure -- callers must not swallow this silently; a genuine
    API error (invalid market, rate limit, auth) needs to be visibly different from "no odds
    posted yet for this event," which look identical from the UI otherwise."""
    try:
        r = requests.get(f"{_BASE}/{path}", params=params, timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise OddsAPIError(f"network error: {e}") from e
    if r.status_code == 401:
        raise OddsAPIError("401 Unauthorized — check your API key.")
    if r.status_code == 429:
        raise OddsAPIError("429 — out of quota for this period.")
    if r.status_code != 200:
        raise OddsAPIError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json(), dict(r.headers)


def get_ufc_events(api_key: str, date_str: Optional[str] = None) -> List[Dict]:
    """All upcoming UFC events, optionally filtered to a specific date. Raises OddsAPIError on a
    real API failure -- the caller (the view) is responsible for catching this and showing it,
    rather than this function silently returning [] and making a real error indistinguishable
    from "no events scheduled."""
    data, _ = _get(f"sports/{UFC_SPORT}/events", {"apiKey": api_key})
    if not date_str:
        return data or []
    return [e for e in (data or []) if _eastern_date_str(e.get("commence_time")) == date_str]


def get_event_odds(event_id: str, api_key: str,
                   markets: Optional[List[str]] = None,
                   book: str = "draftkings") -> Dict:
    """Fetch odds for a specific UFC event. Returns raw Odds API event object. Raises
    OddsAPIError on a real API failure -- same reasoning as get_ufc_events above; a real,
    fixable error (e.g. one of UFC_MARKETS not yet supported for this event) must be visible,
    not silently identical to "no odds posted yet.\""""
    markets = markets or UFC_MARKETS
    data, _ = _get(
        f"sports/{UFC_SPORT}/events/{event_id}/odds",
        {"apiKey": api_key, "regions": "us",
         "markets": ",".join(markets), "oddsFormat": "american"})
    return data or {}


def parse_bout_odds(event_data: Dict, preferred_book: str = "draftkings") -> Dict[str, Any]:
    """Extract structured odds from an event odds response.

    Returns {market_key: {fighter_name: american_odds, ...}, ...}
    For totals: {"totals": {"Over N.5": odds, "Under N.5": odds}}"""
    result: Dict[str, Any] = {}
    bookmakers = event_data.get("bookmakers") or []

    # Prefer the preferred_book; fall back to first available
    book_data = next((b for b in bookmakers if b.get("key") == preferred_book), None)
    if book_data is None and bookmakers:
        book_data = bookmakers[0]
    if book_data is None:
        return result

    for market in book_data.get("markets") or []:
        key = market.get("key", "")
        outcomes = market.get("outcomes") or []
        if key == "totals":
            result["totals"] = {
                o.get("name", ""): o.get("price")
                for o in outcomes
                if o.get("name") and o.get("price") is not None
            }
            # Also store the point value for display
            for o in outcomes:
                if o.get("point") is not None:
                    result["_total_point"] = o["point"]
                    break
        else:
            result[key] = {
                o.get("name", ""): o.get("price")
                for o in outcomes
                if o.get("name") and o.get("price") is not None
            }
            if key == "spreads":                              # Nov 7: each fighter's spread point
                result["_spread_points"] = {o.get("name", ""): o.get("point") for o in outcomes if o.get("name")}

    return result


def build_slate(date_str: str) -> Tuple[List[Dict], List[Dict]]:
    """Return (bouts, meta) for the given date.

    bouts: one dict per fighter per fight (two rows per bout — one for each fighter)
    meta: one dict per fight (the shared bout context)

    When no API key is configured or no events found, returns ([], []).
    The platform's audience gate handles the 'no data' display."""
    try:
        import streamlit as st
        api_key = st.secrets.get("ODDS_API_KEY") or os.environ.get("ODDS_API_KEY")
    except Exception:
        api_key = os.environ.get("ODDS_API_KEY")

    if not api_key:
        return [], []

    events = get_ufc_events(api_key, date_str)
    if not events:
        return [], []

    bouts: List[Dict] = []
    meta: List[Dict] = []

    for i, event in enumerate(events):
        fighter_a = event.get("home_team", "")
        fighter_b = event.get("away_team", "")
        if not fighter_a or not fighter_b:
            continue

        commence = event.get("commence_time", "")
        label = f"{fighter_a} vs. {fighter_b}"
        event_id = event.get("id", "")
        is_main = (i == 0)  # first event in the response is typically the main event

        m = {
            "label": label,
            "game_date": commence,
            "event_id": event_id,
            "fighter_a": fighter_a,
            "fighter_b": fighter_b,
            "bout_number": i,
            "_is_main_event": is_main,
        }
        meta.append(m)

        for fighter in (fighter_a, fighter_b):
            bouts.append({
                "Fighter": fighter,
                "Opponent": fighter_b if fighter == fighter_a else fighter_a,
                "GameLabel": label,
                "game_date": commence,
                "event_id": event_id,
                "_bout_number": i,
                "_is_main_event": is_main,
            })

    return bouts, meta


# --------------------------------------------------------------------------- the whole card in one call (Nov 7)
def _imp(american) -> Optional[float]:
    try:
        a = float(american)
    except (TypeError, ValueError):
        return None
    if -100 < a < 100:
        return None
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def card_from_odds(data: List[Dict], date_str: Optional[str] = None) -> List[Dict]:
    """Bulk odds response -> one row per bout, earliest first: both fighters, start time, every book's moneyline, the
    best price on each side, and the market's no-vig chance (median over books). Bouts with no posted price are kept
    (they're on the card), with None odds."""
    import statistics
    out = []
    for e in data or []:
        if date_str and _eastern_date_str(e.get("commence_time")) != date_str:
            continue
        a, b = e.get("away_team"), e.get("home_team")
        prices: Dict[str, Dict[str, float]] = {}
        for bk in e.get("bookmakers") or []:
            for m in bk.get("markets") or []:
                if m.get("key") != "h2h":
                    continue
                pr = {o.get("name"): o.get("price") for o in m.get("outcomes") or []}
                if pr.get(a) is not None and pr.get(b) is not None:
                    prices[bk.get("key")] = {"a": pr[a], "b": pr[b]}
        fair = []
        for p in prices.values():
            ia, ib = _imp(p["a"]), _imp(p["b"])
            if ia and ib:
                fair.append(ia / (ia + ib))
        pa = statistics.median(fair) if fair else None
        best_a = max((p["a"] for p in prices.values()), default=None, key=lambda v: v)
        best_b = max((p["b"] for p in prices.values()), default=None, key=lambda v: v)
        lines = {}
        for bk in e.get("bookmakers") or []:                    # every book's spread and total (rounds)
            for m in bk.get("markets") or []:
                if m.get("key") == "spreads":
                    lines.setdefault(bk.get("key"), {})["spread"] = {o.get("name"): (o.get("point"), o.get("price"))
                                                                     for o in m.get("outcomes") or []}
                elif m.get("key") == "totals":
                    lines.setdefault(bk.get("key"), {})["total"] = {o.get("name"): (o.get("point"), o.get("price"))
                                                                    for o in m.get("outcomes") or []}
        out.append({"id": e.get("id"), "commence": e.get("commence_time"), "a": a, "b": b, "p_a": pa,
                    "best_a": best_a, "best_b": best_b, "books": len(prices), "prices": prices, "lines": lines,
                    "book_keys": sorted({bk.get("key") for bk in e.get("bookmakers") or []})})
    out.sort(key=lambda r: r.get("commence") or "")
    return out


def book_lines(bout: Dict, book: str = "draftkings") -> Dict[str, str]:
    """{"spread", "total", "ml"} display strings at `book` (falls back to the first book that has each)."""
    def first(kind):
        ln = (bout.get("lines") or {})
        if book in ln and kind in ln[book]:
            return ln[book][kind]
        return next((v[kind] for v in ln.values() if kind in v), None)
    out = {"spread": "", "total": "", "ml": ""}
    sp = first("spread")
    if sp:
        parts = [f"{n.split()[-1]} {pt:+g} ({pr:+.0f})" for n, (pt, pr) in sp.items() if pt is not None and pr is not None]
        out["spread"] = " / ".join(parts)
    tt = first("total")
    if tt:
        o, u = tt.get("Over"), tt.get("Under")
        if o and u and o[0] is not None:
            out["total"] = f"O/U {o[0]:g} ({o[1]:+.0f} / {u[1]:+.0f})"
    pr = (bout.get("prices") or {}).get(book) or next(iter((bout.get("prices") or {}).values()), None)
    if pr:
        out["ml"] = f"{bout['a'].split()[-1]} {pr['a']:+.0f} / {bout['b'].split()[-1]} {pr['b']:+.0f}"
    return out


def get_card(api_key: str, date_str: Optional[str] = None) -> List[Dict]:
    """Every MMA bout on `date_str` (Eastern) with moneylines from every US book -- ONE odds request for the whole
    card (the per-bout fetch below the overview costs one request per bout). Raises OddsAPIError on a real failure."""
    data, _ = _get(f"sports/{UFC_SPORT}/odds", {"apiKey": api_key, "regions": "us", "markets": "h2h,spreads,totals",
                                               "oddsFormat": "american"})
    return card_from_odds(data, date_str)


def card_dates(api_key: str) -> List[str]:
    """Eastern dates that have bouts listed, soonest first (for an empty date: where the next card is)."""
    data, _ = _get(f"sports/{UFC_SPORT}/events", {"apiKey": api_key})
    return sorted({d for d in (_eastern_date_str(e.get("commence_time")) for e in data or []) if d})


# Nov 7 (revised): "5+ books" hid a UFC prelim (Parsons vs Henrique, priced by DraftKings and two others). A bout is on a
# main card when a major US sportsbook prices it; regional shows are priced only by offshore books.
MAJOR_BOOKS = {"draftkings", "fanduel", "betmgm", "williamhill_us", "espnbet", "fanatics", "betrivers", "hardrockbet"}
MAIN_CARD_MIN_BOOKS = 0     # kept for callers; the rule is MAJOR_BOOKS now


def main_card_only(card: List[Dict]) -> List[Dict]:
    """Bouts a major US sportsbook prices, with stale duplicates dropped: when a fighter is listed in two bouts the same
    day (an opponent change the feed hasn't cleared), keep the bout DraftKings prices, else the one more books price."""
    keep = [b for b in card if set(b.get("book_keys") or b.get("prices") or {}) & MAJOR_BOOKS]
    return dedupe(keep)


def dedupe(card: List[Dict]) -> List[Dict]:
    def rank(b):
        return ("draftkings" in (b.get("book_keys") or b.get("prices") or {}), b.get("books") or 0)
    best: Dict[str, Dict] = {}
    for b in card:
        for f in (b["a"], b["b"]):
            if f not in best or rank(b) > rank(best[f]):
                best[f] = b
    winners = {id(b) for b in best.values()}
    out = []
    for b in card:
        if id(b) in winners and best.get(b["a"]) is b and best.get(b["b"]) is b:
            out.append(b)
    return out
