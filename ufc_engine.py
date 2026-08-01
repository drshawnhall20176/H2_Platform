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
  fighter_wins_by_ko_tko  = Fighter wins specifically by KO/TKO
  fighter_wins_by_submission = Fighter wins by submission
  fighter_wins_by_decision   = Fighter wins by decision (any type)

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
    "fighter_wins_by_ko_tko",
    "fighter_wins_by_submission",
    "fighter_wins_by_decision",
]

# Human-readable display names for each market
UFC_MARKET_LABELS = {
    "h2h":                       "Moneyline",
    "totals":                    "Fight Duration",
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
