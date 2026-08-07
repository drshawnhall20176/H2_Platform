"""
mlb_shared_cache.py — the ONE place page-level Streamlit caches live for expensive MLB calls
that more than one page needs, so the same real work is never done twice in the same session.

WHY THIS IS ITS OWN MODULE, NOT PART OF mlb_engine.py: mlb_engine.py's own docstring states a
real, deliberate principle -- "Framework-agnostic (no Streamlit import)" -- so it can be imported
by standalone scripts (backfill_grading_history.py, lineup_neighbor_analysis.py) that run in
environments without Streamlit installed at all. Adding a Streamlit dependency there, even a
conditional one, would work but would quietly erode that stated boundary. This module exists
specifically to hold the Streamlit-caching layer, so mlb_engine.py can stay exactly what its own
docstring says it is.

THE REAL, CONFIRMED PROBLEM THIS SOLVES, first found in a real module-audit pass: three separate
view files (Bullpen Watch, Game Watch, MLB First Innings Totals) each defined their own,
byte-for-byte-identical local wrapper --

    @st.cache_data(...)
    def load_pitching_slate(date_str_inner):
        return E.build_pitching_slate(date_str_inner)

Streamlit's cache_data keys on a function's own identity (module + qualname + source), so three
separately-defined functions with identical bodies are NOT the same cache entry, even though they
do the exact same real work on the exact same date. build_pitching_slate is one of the more
expensive real calls in this whole platform (a real per-pitcher fetch across the entire slate) --
a real session visiting Bullpen Watch, then Game Watch, then First Innings Totals for the same
date re-ran that full, expensive fetch up to three separate times, each on its own independent
TTL, none of them aware the others existed. The exact same real class of problem, and the exact
same real fix, already proven once in this codebase for Statcast data (see statcast_data.py's own
load_cached docstring for that original, confirmed incident).

TTL set to 300s (5 minutes) for load_pitching_slate_cached, the SHORTER of the two real TTLs the
three original wrappers used (300s and 600s) -- deliberately the more conservative choice, not an
average: build_pitching_slate's own data is probable starters, which can genuinely change closer
to game time (a late scratch), so freshness matters more here than it does for something like
season-long Statcast rates.

A SECOND, NARROWER CONSOLIDATION, get_team_bullpen_fatigue_cached: Game Watch and Bullpen Watch
each independently cached this same real, expensive fetch too, but their own page-local wrappers
around it are NOT byte-for-byte identical the way the pitching-slate ones were (Bullpen Watch's
own version also names the single most-taxed pitcher). Rather than force a shared shape onto two
genuinely different real outputs, only the expensive, identical part -- the raw fetch itself -- is
shared here; each page's own different post-processing stays local, called on this shared result.
"""

from __future__ import annotations

from typing import Dict, List

try:
    import streamlit as st
except ImportError:
    # Same real, established pattern as statcast_data.py's own identical fix -- a module used by
    # BOTH the live Streamlit app and standalone scripts that must not require Streamlit at all.
    st = None

import mlb_engine as E


if st is not None:
    @st.cache_data(ttl=300, show_spinner=False)
    def load_pitching_slate_cached(date_str: str) -> List[Dict]:
        """Cached companion to mlb_engine.build_pitching_slate -- the ONE real, shared entry
        point every page needing today's probable-starter slate should call, instead of each
        defining its own local wrapper. See this module's own docstring for the full, confirmed
        reasoning on why this consolidation exists.

        DEFINED ONLY WHEN STREAMLIT IS ACTUALLY IMPORTABLE (see the module-level try/except
        above) -- a standalone script that imports mlb_engine directly (backfill_grading_
        history.py, lineup_neighbor_analysis.py) never imports THIS module and never calls this
        function; every real caller of load_pitching_slate_cached is a live Streamlit page,
        which already requires Streamlit to run at all."""
        return E.build_pitching_slate(date_str)

    @st.cache_data(ttl=600, show_spinner=False)
    def get_team_bullpen_fatigue_cached(team_id: int, date_str: str) -> List[Dict]:
        """Cached companion to mlb_engine.get_team_bullpen_fatigue -- the ONE real, shared entry
        point for a team's own raw recent-appearance data every page needing bullpen freshness
        should call.

        A REAL, CONFIRMED FIX, narrower than load_pitching_slate_cached above: Game Watch's own
        load_bullpen_freshness and Bullpen Watch's own load_team_freshness independently cached
        this exact same real fetch, confirmed directly by reading both -- but they are NOT
        byte-for-byte identical wrappers the way the pitching-slate ones were (Bullpen Watch's
        own version also names the single most-taxed pitcher and the real pitcher count, real,
        different shaping Game Watch doesn't need). Rather than force both into one, possibly
        awkward shared shape, this shares only the genuinely expensive, genuinely identical
        part -- the real network fetch -- and leaves each page's own real, different
        post-processing (bullpen_fatigued_fraction, and whatever each page builds from it)
        completely untouched, called locally, on this shared result.

        Same real, deliberate TTL (600s) both original wrappers already independently agreed on
        -- not a new, guessed value."""
        return E.get_team_bullpen_fatigue(team_id, date_str)

    @st.cache_data(ttl=300, show_spinner=False)
    def load_hitter_slate_cached(date_str: str):
        """Cached companion to mlb_engine.build_slate -- the ONE real, shared entry point for
        today's hitter rows (paired with each game's own real meta -- gamePk, etc.) every page
        needing the full hitting slate should call.

        A REAL, CONFIRMED FIX found in the same real audit pass, the SAME real class of problem
        as load_pitching_slate_cached above: MLB Player Lines and MLB Matchup Lab (the pitch-
        level one, page 9) each independently defined a byte-for-byte-identical local
        @st.cache_data wrapper around E.build_slate(date_str) -- confirmed directly by reading
        both. Same real 300s TTL both original wrappers already independently agreed on."""
        return E.build_slate(date_str)
