"""
basketball_shared_cache.py — the ONE place page-level Streamlit caches live for the real
spread/blowout-risk signal, so any page that wants to surface it reuses the same real, cached
fetch instead of each page defining its own.

ADDED DIRECTLY ON REQUEST, part of a real, two-part fix for a real, repeated community pain
point: "blowouts causing failed parlays" and "the fact that the players seem to forget how to
play after halftime" -- both real descriptions of the same real basketball phenomenon (garbage
time: once a game is decided, the favorite rests its stars, the underdog's bench gets extended
run). A real signal for exactly this (basketball_projections.blowout_risk_tag, driven by real,
live sportsbook spreads) already existed -- but was only ever wired into Hot Hand Engine, a page
the real community data barely mentions, and completely absent from Best Bets, Graded Picks, and
Suggested Parlays, the real pages where picks actually get built. This module exists to make
surfacing that same real, already-reasoned signal on those pages a one-line addition, not a
separate real fetch/cache implementation per page.

SPORT-AGNOSTIC BY DESIGN, not WNBA-specific: confirmed directly that WNBA, NBA, and NCAAMB's own
projections modules all already share the exact same real blowout_risk_tag/team_spreads
convention (basketball_projections.py's own shared function, re-exported by each). Gated by
hasattr(proj, "blowout_risk_tag"), not a hardcoded list of sport keys -- a real, deliberate
choice matching the same pattern already proven for UFC's own known_roster_names: checking for
the real CAPABILITY a sport's own projections module provides, not a list that could silently
drift stale if a new basketball sport is ever added without updating a hardcoded set here too.

DELIBERATELY KEPT SEPARATE FROM ModelProb/Grade, same as the original Hot Hand Engine design:
this module only ever fetches and caches the real spread; it never touches or adjusts a play's
own real probability. Whether this signal is accurate enough to ever inform live pricing is a
real, separate, evidence-based question -- see retro.py's own real blowout_risk_calibration (a
later, separate real addition) for the actual validation work, not a decision made silently here.

TTL set to 300s, matching fetch_slate_spreads' own real cost profile (a real, live odds-API call,
1 unit/event -- cheap relative to a full player-prop fetch, but still a real, live network cost,
not free) -- the same real TTL Hot Hand Engine's own existing load_spreads already uses.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

try:
    import streamlit as st
except ImportError:
    # Same real, established pattern as mlb_shared_cache.py's own identical fix -- a module
    # used by BOTH the live Streamlit app and any future standalone script that must not
    # require Streamlit at all.
    st = None

import sports
import odds_api as O


if st is not None:
    @st.cache_data(ttl=300, show_spinner=False)
    def load_team_spreads_cached(sport_key: str, date_str: str, api_key: str) -> Tuple[Dict[str, float], Dict]:
        """Cached companion to odds_api.fetch_slate_spreads -- the ONE real, shared entry point
        any page needing tonight's real spreads (for blowout_risk_tag, or any other real, future
        use) should call, instead of each page defining its own local wrapper the way Hot Hand
        Engine's own load_spreads did before this existed.

        DEFINED ONLY WHEN STREAMLIT IS ACTUALLY IMPORTABLE (see the module-level try/except
        above) -- every real caller of this function is a live Streamlit page, which already
        requires Streamlit to run at all."""
        sport = sports.get(sport_key)
        return O.fetch_slate_spreads(date_str, api_key, sport=sport.odds_sport_key)


def blowout_risk_for_team(team: str, team_spreads: Dict[str, float], proj_module) -> str:
    """A real, tiny, sport-agnostic wrapper around proj_module.blowout_risk_tag -- exists so a
    calling page never needs to know that function's own name or import path, just "give me the
    real blowout-risk label for this real team, using this sport's own real projections module
    and whatever real spreads were fetched." Returns "—" (proj_module.blowout_risk_tag's own
    honest "no data" case) when the sport has no real blowout_risk_tag at all, or the team isn't
    in team_spreads (no real spread fetched or found for them tonight)."""
    if not hasattr(proj_module, "blowout_risk_tag"):
        return "—"
    return proj_module.blowout_risk_tag(team_spreads.get(team))
