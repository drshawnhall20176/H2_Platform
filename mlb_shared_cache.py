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

A THIRD CONSOLIDATION, load_hitter_slate_cached, and a FOURTH, get_team_injuries_cached: both the
SAME real class of problem as load_pitching_slate_cached above -- genuinely byte-for-byte
identical local wrappers, confirmed directly by reading each pair, differing only in their own
chosen TTL. Shared here at the shorter (more conservative) of each pair's two original values.

A FIFTH CONSOLIDATION, load_slate_with_fip_cached, found in a THIRD, later audit pass: MLB Dinger
Engine and Pitching Lab each independently called build_slate WITH an explicit fip_constant
before diverging into genuinely different downstream work. The same real narrow-consolidation
shape as get_team_bullpen_fatigue_cached above -- share only the identical, expensive fetch.

A SIXTH ADDITION, get_all_active_player_names_cached: not a consolidation of an existing
redundancy like the five above, but a NEW real capability, added directly on request, that lets
Edge Board's own diagnostic panel tell a genuine, fixable name mismatch apart from a real,
active player who simply isn't part of tonight's specific slate (see mlb_engine.
get_all_active_player_names' own docstring for the full, confirmed reasoning). A real, notably
longer TTL than every other entry here -- see that function's own docstring below for why.
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

    @st.cache_data(ttl=900, show_spinner=False)
    def get_team_injuries_cached(team_id: int) -> List[Dict]:
        """Cached companion to mlb_engine.get_team_injuries -- the ONE real, shared entry point
        for a team's own injury report every page needing it should call.

        A REAL, CONFIRMED FIX, the SAME real class of problem as the other two consolidations
        in this module: Game Watch and MLB Matchup Lab (page 9) each independently defined a
        byte-for-byte-identical local wrapper -- confirmed directly by reading both, differing
        only in their own real TTL (900s vs 1800s). Shared here at 900s, the SHORTER (more
        conservative) of the two -- an injury report can genuinely change (a real activation or
        a real new IL move), so fresher data is the safer real default, not an average of the
        two original values."""
        if not team_id:
            return []
        return E.get_team_injuries(team_id)

    @st.cache_data(ttl=300, show_spinner=False)
    def load_slate_with_fip_cached(date_str: str, fip_constant: float):
        """Cached companion to mlb_engine.build_slate WITH an explicit fip_constant -- a real,
        genuinely different call (and cache key) from load_hitter_slate_cached above, which
        calls build_slate with its own default fip_constant instead.

        A REAL, CONFIRMED FIX found in a THIRD real audit pass: MLB Dinger Engine and Pitching
        Lab each independently ran this exact same real fetch -- confirmed directly by reading
        both -- before diverging into genuinely different downstream work (Dinger Engine builds
        hitter-focused weather/split/power context; Pitching Lab builds pitcher-focused
        projections and FIP regression). Only this shared, identical prefix is consolidated here
        -- each page's own real, different post-processing (including each page's own separate
        call to best_bets_data.fetch_mlb_real_lines, which is ALREADY shared at its own source
        and needed no further consolidation) stays exactly as it was."""
        return E.build_slate(date_str, fip_constant)

    @st.cache_data(ttl=21600, show_spinner=False)
    def get_all_active_player_names_cached(season: int) -> set:
        """Cached companion to mlb_engine.get_all_active_player_names -- the ONE real, shared
        entry point for "every real player active in the majors this season" any page needing
        it should call.

        ADDED DIRECTLY ON REQUEST, a real, confirmed fix for a real, reported case (see that
        function's own docstring for the full reasoning). TTL set to 21600s (6 hours), a real,
        deliberate departure from every other TTL in this module -- every other real lookup here
        (a slate, an injury report, a bullpen state) can genuinely change within minutes, but a
        real trade or a real roster move is a genuinely rare, discrete event, not a continuous
        one -- caching this for 6 hours means one real, shared league-wide fetch covers an
        entire real trading session's worth of page loads, not one fetch per page per rerun."""
        return E.get_all_active_player_names(season)
