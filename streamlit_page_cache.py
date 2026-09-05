"""
streamlit_page_cache.py — compute-once, filter-instantly pattern.

WHY THIS EXISTS, DIRECTLY FROM USER REPORT: MLB Best Bets and other pages were taking
minutes to respond to filter changes (time slot, game picker, position). The root cause:
Streamlit reruns the entire page script on every widget interaction. Even with @st.cache_data,
there is overhead on each rerun -- serialization/deserialization of cached results, multiple
sequential cache lookups, and critically, board-building functions that were moved OUTSIDE
cached wrappers to support slot/game filtering, meaning they reran on every filter change.

THE FIX: store the expensive, already-computed board in st.session_state as a native Python
object. Session state lookups are O(1) dict lookups with zero serialization cost -- the
data stays as plain Python lists of dicts in memory. Filter widgets (slot, game, position)
then operate as pure Python list comprehensions on the in-memory board, which is
sub-millisecond regardless of board size. Recomputation only happens when the HEAVY inputs
change (date, stats_date_str, selected player) -- not when filter widgets change.

USAGE:
    from streamlit_page_cache import compute_once, invalidate_page

    # Heavy computation -- only reruns when date_str or stats_date_str actually change
    board = compute_once("hot_hand", build_board_fn, date_str, stats_date_str)

    # Instant -- pure in-memory filter, no recomputation
    filtered = [r for r in board if r["Game"] == game_pick]

    # Wire to Refresh button
    if st.button("Refresh"):
        invalidate_page("hot_hand")
        st.rerun()
"""

import streamlit as st
from typing import Any, Callable


def compute_once(page_key: str, compute_fn: Callable, *args) -> Any:
    """
    Return the cached in-memory result if the heavy inputs haven't changed since the last
    call; otherwise call compute_fn(*args), store the result, and return it.

    page_key: unique per page (e.g. "best_bets", "ncaaf_hot_hand") -- keeps different
              pages' cached results isolated from each other in session state.
    compute_fn: the expensive function to call when inputs change.
    *args: both the arguments to compute_fn AND the cache key -- if any arg changes,
           recomputation is triggered. Keep these to the HEAVY inputs only (date, player,
           stats_date_str); filter widget values should NOT be args here.
    """
    val_key = f"_psc_{page_key}_val"
    sig_key = f"_psc_{page_key}_sig"

    # Signature from args -- change in any arg triggers recomputation
    try:
        sig = repr(args)
    except Exception:
        sig = str(id(args))  # fallback for truly unhashable args

    if st.session_state.get(sig_key) != sig or val_key not in st.session_state:
        result = compute_fn(*args)
        st.session_state[val_key] = result
        st.session_state[sig_key] = sig

    return st.session_state[val_key]


def invalidate_page(page_key: str) -> None:
    """Force recomputation on the next compute_once call for this page.
    Wire this to the Refresh button so manual refresh always gets fresh data."""
    sig_key = f"_psc_{page_key}_sig"
    st.session_state.pop(sig_key, None)


def invalidate_all() -> None:
    """Invalidate all pages -- useful for a global cache clear."""
    keys_to_delete = [k for k in st.session_state if k.startswith("_psc_") and k.endswith("_sig")]
    for k in keys_to_delete:
        del st.session_state[k]
