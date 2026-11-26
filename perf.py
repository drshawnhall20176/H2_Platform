"""
perf.py -- where a page's load time goes, shown to the owner only (Nov 26, owner: "speed is a priority item").

Wrap a slow step in `with perf.timed("label"):` and call `perf.panel()` at the end of the page: a small expander lists
each step's seconds for this run, slowest first, so the next fix goes where the time actually is. Off the owner
deployment (AUDIENCE != owner) nothing is recorded or shown. Never raises.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import List, Tuple

_KEY = "_perf_steps"


def _owner() -> bool:
    try:
        import streamlit as st
        return st.secrets.get("AUDIENCE", "owner") == "owner"
    except Exception:                                           # noqa: BLE001 -- no secrets file: a local owner run
        return True


def start() -> None:
    """Call once at the top of a page: starts this run's list."""
    try:
        import streamlit as st
        st.session_state[_KEY] = [("_start", time.perf_counter())]
    except Exception:                                           # noqa: BLE001
        pass


@contextmanager
def timed(label: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        try:
            import streamlit as st
            st.session_state.setdefault(_KEY, []).append((label, time.perf_counter() - t0))
        except Exception:                                       # noqa: BLE001
            pass


def steps() -> Tuple[List[Tuple[str, float]], float]:
    try:
        import streamlit as st
        got = list(st.session_state.get(_KEY) or [])
    except Exception:                                           # noqa: BLE001
        return [], 0.0
    t0 = next((v for k, v in got if k == "_start"), None)
    total = (time.perf_counter() - t0) if t0 is not None else 0.0
    return sorted([(k, v) for k, v in got if k != "_start"], key=lambda x: -x[1]), total


def panel(page: str) -> None:
    """The owner's timing expander for this run of the page."""
    if not _owner():
        return
    try:
        import streamlit as st
        rows, total = steps()
        if not rows:
            return
        with st.expander(f"⏱️ Page timing — {page}: {total:.1f}s this load (only you see this)", expanded=False):
            st.markdown("\n".join(f"- **{k}**: {v:.2f}s" for k, v in rows))
            st.caption("Each step's time on this load, slowest first. Cached steps show near 0 on a second load — the "
                       "first load of the hour is the one to judge.")
    except Exception:                                           # noqa: BLE001
        pass
