"""
nfl_shared_cache.py — the ONE place page-level Streamlit caches live for expensive NFL calls
that more than one page needs, so the same real work is never done twice in the same session.

Mirrors mlb_shared_cache.py's own proven template exactly -- same real reasoning, same real
safety pattern, applied to NFL before it goes live rather than after, on direct request: "this
functionality and mindset is going to flow into the NFL and NCAAF models."

WHY THIS IS ITS OWN MODULE, NOT PART OF nfl_engine.py: keeps the same real, deliberate separation
mlb_shared_cache.py already established for MLB -- the Streamlit-caching layer lives here, so
nfl_engine.py stays importable by any future standalone script (a backfill job, a research
script) without requiring Streamlit to be installed at all, the exact same real class of problem
statcast_data.py's own load_cached already hit once for MLB (see that module's own docstring for
the original, confirmed incident this pattern guards against).

THE REAL, CONFIRMED PROBLEM THIS SOLVES, found in the same real module-audit pass that found
MLB's four consolidations: four separate NFL view files (NFL Matchup Lab, Anytime TD Engine, QB
Lab, NFL Hot Hand Engine) each call E.build_slate(date_str) as their own first step -- confirmed
directly by reading all four. Unlike MLB's own build_slate/hitters case, each of these four pages
does genuinely different, substantial post-processing afterward (Anytime TD Engine builds a whole
TD board; QB Lab and Hot Hand Engine both do real, additional per-opponent stat fetches) -- the
same real shape as MLB's own bullpen-fatigue consolidation, not the pitching-slate one. Only the
expensive, identical part -- the raw E.build_slate fetch -- is shared here; each page's own real,
different post-processing stays completely local, called on this shared result.

TTL set to 300s, matching three of the four original wrappers' own real choice (QB Lab's own was
600s, the one outlier) -- the shorter, more conservative value, for the same real reason MLB's
own consolidations picked the shorter of any differing pair: a real slate can change (a real
inactive, a real lineup update), so fresher data is the safer real default.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

try:
    import streamlit as st
except ImportError:
    # Same real, established pattern as mlb_shared_cache.py's own identical fix -- a module
    # used by BOTH the live Streamlit app and any future standalone script that must not
    # require Streamlit at all.
    st = None

import nfl_engine as E


if st is not None:
    @st.cache_data(ttl=300, show_spinner=False)
    def load_nfl_slate_cached(date_str: str) -> Tuple[List[Dict], List[Dict]]:
        """Cached companion to nfl_engine.build_slate -- the ONE real, shared entry point every
        NFL page needing today's slate (rows, meta) should call, instead of each defining its
        own local wrapper. See this module's own docstring for the full, confirmed reasoning.

        DEFINED ONLY WHEN STREAMLIT IS ACTUALLY IMPORTABLE (see the module-level try/except
        above) -- a standalone script that imports nfl_engine directly never imports THIS module
        and never calls this function; every real caller of load_nfl_slate_cached is a live
        Streamlit page, which already requires Streamlit to run at all."""
        return E.build_slate(date_str)
