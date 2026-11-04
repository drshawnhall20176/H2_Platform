"""
slate_store.py — save each sport's built slate so the app doesn't rebuild it after every restart (Nov 4).

Why: building one NBA slate means every rostered player's recent games -- a few hundred ESPN requests. Streamlit's
caches live in memory, so every restart (each update to the app restarts it) and every cold page paid that cost again,
and the Analyst Desk took minutes to open. Now a built slate is saved to the database; the next caller -- another page,
a restarted app, the other session -- reads it back in one query while it's fresh:

    today / future slates   fresh for FRESH_S (an hour: rosters and injury news move during the day)
    past slates             always fresh (those games are over)

The warm-slates workflow rebuilds today's slates every hour, so a fresh copy is usually waiting. Only the default
call (build_slate(date_str), which every page uses) is saved; a call with other arguments builds as before.

    build_slate = slate_store.persisted("NBA")(build_slate)       # at the bottom of an engine module
"""
from __future__ import annotations

import base64
import functools
import os
import pickle
import threading
import time
import zlib
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Tuple

FRESH_S = 3600
_mem: Dict[Tuple[str, str], Tuple[float, bytes]] = {}
_locks: Dict[Tuple[str, str], threading.Lock] = {}
_guard = threading.Lock()


def _today_et() -> str:
    import pytz
    return datetime.now(pytz.timezone("US/Eastern")).date().isoformat()


def _fresh(saved_at: float, date_str: str) -> bool:
    return date_str < _today_et() or (time.time() - saved_at) < FRESH_S


def encode(value) -> bytes:
    return zlib.compress(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL), 6)


def decode(blob: bytes):
    return pickle.loads(zlib.decompress(blob))


def _off() -> bool:
    return bool(os.environ.get("SLATE_STORE_OFF")) or "PYTEST_CURRENT_TEST" in os.environ


def load(sport: str, date_str: str) -> Optional[bytes]:
    """A fresh saved slate (compressed), from this process or the database; None when there isn't one."""
    hit = _mem.get((sport, date_str))
    if hit and _fresh(hit[0], date_str):
        return hit[1]
    try:
        import model_store as MS
        row = MS.load_slate(sport, date_str)
    except Exception:                                           # noqa: BLE001
        row = None
    if not row:
        return None
    try:
        ts = datetime.fromisoformat(str(row["ts"]))
        saved_at = (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).timestamp()
        if not _fresh(saved_at, date_str):
            return None
        blob = base64.b64decode(row["payload"])
    except Exception:                                           # noqa: BLE001
        return None
    _mem[(sport, date_str)] = (saved_at, blob)
    return blob


def save(sport: str, date_str: str, value) -> None:
    try:
        blob = encode(value)
    except Exception:                                           # noqa: BLE001 -- something unpicklable: just don't save
        return
    _mem[(sport, date_str)] = (time.time(), blob)
    try:
        import model_store as MS
        MS.save_slate(sport, date_str, base64.b64encode(blob).decode())
    except Exception:                                           # noqa: BLE001 -- saving is a bonus, never a failure
        pass


def persisted(sport: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(date_str, *args, **kwargs):
            if args or kwargs or _off():
                return fn(date_str, *args, **kwargs)
            key = (sport, str(date_str))
            blob = load(*key)
            if blob is not None:
                return decode(blob)                             # a fresh copy each call: callers may edit rows
            with _guard:
                lock = _locks.setdefault(key, threading.Lock())
            with lock:                                          # two pages opening at once build it once
                blob = load(*key)
                if blob is not None:
                    return decode(blob)
                value = fn(date_str)
                rows = value[0] if isinstance(value, tuple) and value else value
                if rows:                                        # never save an empty slate (a failed fetch)
                    save(sport, str(date_str), value)
                return value
        wrapper.uncached = fn
        return wrapper
    return deco
