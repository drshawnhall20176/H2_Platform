"""
cache_guard.py — keep the app inside Streamlit Community Cloud's memory (Nov 20).

Owner: "my platform loves to crash Streamlit's resource requirements." Streamlit restarts an app that runs out of memory.
Most of what this platform holds in memory is st.cache_data results -- 228 cached functions, nearly all keyed by
sport x date x book x settings, and (until now) all but a few with no limit on how many results they keep. Results past
their ttl are only dropped when that same function is called again, so a busy day piles up boards, slates and game
logs for every combination anyone opened.

Two guards, installed by streamlit_app.py before anything else is imported:
  1. install(): every st.cache_data without its own max_entries keeps at most DEFAULT_MAX_ENTRIES results (oldest
     dropped first) -- the same answer for the next visitor, a ceiling on the pile.
  2. watchdog(): before each page run, if the process is using more than the limit (H2_MEM_LIMIT_MB, default 1800 MB),
     clear the data caches and collect garbage -- the next visitor waits for a rebuild instead of everyone getting the
     "Oh no" page. At most once a minute; each clear is printed to the app log with the memory before and after.
"""
from __future__ import annotations

import gc
import os
import time

DEFAULT_MAX_ENTRIES = 300          # per-player / per-team caches hold hundreds of small results a slate
_STATE = {"last": 0.0, "clears": 0}


def install() -> None:
    import streamlit as st
    if getattr(st.cache_data, "_h2_guard", False):
        return
    orig = st.cache_data

    class _Guarded:
        _h2_guard = True

        def __call__(self, func=None, **kw):
            kw.setdefault("max_entries", DEFAULT_MAX_ENTRIES)
            return orig(func, **kw) if func is not None else orig(**kw)

        def __getattr__(self, name):                            # .clear() and anything else
            return getattr(orig, name)

    st.cache_data = _Guarded()


def rss_mb() -> float | None:
    """The process's resident memory in MB (Linux), or None."""
    try:
        with open("/proc/self/statm") as fh:
            pages = int(fh.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / 1e6
    except Exception:                                           # noqa: BLE001 -- not Linux
        return None


def limit_mb() -> float:
    try:
        return float(os.environ.get("H2_MEM_LIMIT_MB") or 1800)
    except ValueError:
        return 1800.0


def watchdog(now: float | None = None, rss=None, clear=None) -> bool:
    """Clear the data caches if memory is over the limit. True when it cleared."""
    now = time.time() if now is None else now
    used = rss_mb() if rss is None else rss
    if used is None or used < limit_mb() or now - _STATE["last"] < 60:
        return False
    if clear is None:
        import streamlit as st
        clear = st.cache_data.clear
    clear()
    gc.collect()
    _STATE["last"] = now
    _STATE["clears"] += 1
    after = rss_mb()
    print(f"[cache_guard] memory {used:.0f} MB over {limit_mb():.0f} MB: data caches cleared"
          + (f", now {after:.0f} MB" if after is not None else "") + f" (clear #{_STATE['clears']})")
    return True


# --------------------------------------------------------------------------- the reload race (Nov 20)
# Streamlit Cloud reloads the code in place when a change is pushed ("Updated app!"). A page that is importing a module
# at that instant can find it half-replaced and crash -- the owner's log: "'NoneType' object has no attribute
# '__dict__'" importing sports.py right after an update. That's a timing accident, not a bug in the page, so the page
# is simply run again once.
def is_reload_race(exc: BaseException) -> bool:
    msg = str(exc)
    return (isinstance(exc, AttributeError) and "'NoneType' object has no attribute '__dict__'" in msg) or \
        (isinstance(exc, ImportError) and "partially initialized module" in msg)


def safe_import(name: str, tries: int = 3):
    """importlib.import_module, retried when a code reload catches it half-way."""
    import importlib
    import sys
    for i in range(tries):
        try:
            return importlib.import_module(name)
        except (AttributeError, ImportError) as exc:
            if not is_reload_race(exc) or i == tries - 1:
                raise
            sys.modules.pop(name, None)
            time.sleep(0.3 * (i + 1))
