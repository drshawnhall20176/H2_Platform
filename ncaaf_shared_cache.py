"""
ncaaf_shared_cache.py — the ONE place page-level Streamlit caches should live for expensive
NCAAF calls that more than one page needs, so the same real work is never done twice in the same
session.

BUILT PROACTIVELY, BEFORE THE PROBLEM EXISTS -- a real, deliberate difference from mlb_shared_
cache.py and nfl_shared_cache.py, both of which were built to fix a redundancy already confirmed
in real, existing pages. Confirmed directly, in the same real module-audit pass that found NFL's
own redundancy: NCAAF currently has ZERO dedicated view files of its own (grep across every real
view file for a static `import ncaaf_engine as E` returns nothing) -- it only runs today through
the shared, dynamic-engine pages every sport already uses (Hot Hand Engine, Matchup Lab, Edge
Board, etc., all resolving E = _active.engine per sport), which don't have this class of problem
by design, since there's exactly one real page, not several independently wrapping the same call.

NFL had this same shape once, before its own four dedicated pages (Matchup Lab, Anytime TD
Engine, QB Lab, Hot Hand Engine) existed. Given NCAAF is described as going live on a similar
timeline, with its own dedicated pages a real, likely next step, this exists now so that whoever
builds NCAAF's first dedicated page reaches for THIS shared cache from the very first line,
rather than defining a local wrapper that a second dedicated page will inevitably duplicate --
the exact real mistake NFL's own four pages made independently, found and fixed only after the
fact. Mirrors mlb_shared_cache.py's and nfl_shared_cache.py's own proven template exactly.

WHY THIS IS ITS OWN MODULE, NOT PART OF ncaaf_engine.py: same real, deliberate separation the
other two shared-cache modules already established -- keeps ncaaf_engine.py importable by any
future standalone script without requiring Streamlit to be installed at all.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

try:
    import streamlit as st
except ImportError:
    # Same real, established pattern as mlb_shared_cache.py's and nfl_shared_cache.py's own
    # identical fix -- a module used by BOTH the live Streamlit app and any future standalone
    # script that must not require Streamlit at all.
    st = None

import ncaaf_engine as E


if st is not None:
    @st.cache_data(ttl=300, show_spinner=False)
    def load_ncaaf_slate_cached(date_str: str) -> Tuple[List[Dict], List[Dict]]:
        """Cached companion to ncaaf_engine.build_slate -- the ONE real, shared entry point any
        NCAAF page needing today's slate (rows, meta) should call. Reach for this FIRST, before
        writing a new local wrapper -- see this module's own docstring for why.

        DEFINED ONLY WHEN STREAMLIT IS ACTUALLY IMPORTABLE (see the module-level try/except
        above) -- a standalone script that imports ncaaf_engine directly never imports THIS
        module and never calls this function; every real caller of load_ncaaf_slate_cached is a
        live Streamlit page, which already requires Streamlit to run at all."""
        return E.build_slate(date_str)
