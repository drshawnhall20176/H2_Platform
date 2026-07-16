"""
line_history.py — storage for REAL LINE MOVEMENT HISTORY (every slate line over time, not just
your own logged bets).

DIFFERENT JOB FROM betlog.py's close_odds tracking: betlog answers "did I beat the closing line on
MY bet?" — one number, captured once, per bet. This module answers "how did this specific
player-prop line move today?" — a genuine time series, for every player/market/book on the slate,
whether or not anyone bet it. That's the data a future line-movement chart (Matchup Lab's own
stock-candlestick analog, distinct from its existing recent-form trend chart) needs and doesn't
have yet — the recent-form chart plots the model's own trailing average against a single CURRENT
line; this is about the LINE ITSELF moving, which needs its own accumulated history to exist
before it can be drawn at all.

STORAGE: same dual-backend pattern as betlog.py, deliberately — SQLite at data/line_history.db for
local/dev, Postgres (Supabase) when DATABASE_URL is configured, so this survives Streamlit Cloud
reboots the same way bets do. A SEPARATE table and file from bets.db, not reusing betlog.py's
schema — this is market data (many rows per slate, not tied to a person's decisions), a different
shape and a different growth rate than a personal bet log.

DE-DUPLICATED ON WRITE: record_snapshot only inserts a new row when the (line, price) for a given
(sport, player, market, side, book) combination actually CHANGED since the last snapshot recorded
for that exact combination — an unchanged line at the next capture doesn't add a redundant row.
Without this, a script running several times a day would mostly write identical repeats; with it,
every stored row represents a real, meaningful movement, which is also what keeps a future chart
readable (points where the line moved) instead of noisy (points every time someone happened to run
the capture).
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, List, Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "line_history.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS line_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at   TEXT NOT NULL,
    sport         TEXT NOT NULL,
    game          TEXT,
    player        TEXT NOT NULL,
    market        TEXT NOT NULL,
    side          TEXT NOT NULL,
    line          REAL,
    price         INTEGER,
    book          TEXT NOT NULL,
    commence_time TEXT
);
"""

_FIELDS = ["captured_at", "sport", "game", "player", "market", "side", "line",
           "price", "book", "commence_time"]


# ===========================================================================
# STORAGE — SQLite for local/dev, Postgres (Supabase) for durable cloud storage.
# Same auto-selection and identical-signatures-across-backends pattern as betlog.py; see that
# module's own comment for the full reasoning. Kept as its own small implementation here (not a
# shared helper) so this file has zero import-time dependency on betlog.py — line history is
# conceptually independent of the bet log and should stay swappable/removable on its own.
# ===========================================================================
def _database_url() -> Optional[str]:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url.strip()
    try:                                    # avoid importing streamlit during offline tests
        import streamlit as st
        val = st.secrets.get("DATABASE_URL")            # type: ignore[attr-defined]
        return str(val).strip() if val else None
    except Exception:
        return None


_DATABASE_URL = _database_url()
USING_POSTGRES = bool(_DATABASE_URL)


# ---- SQLite backend (local development and the test suite) -----------------
@contextmanager
def _sqlite_conn(db_path: str = DB_PATH):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(_SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _sqlite_latest(db_path, sport, player, market, side, book) -> Optional[Dict]:
    with _sqlite_conn(db_path) as con:
        row = con.execute(
            "SELECT * FROM line_snapshots WHERE sport=? AND player=? AND market=? AND side=? "
            "AND book=? ORDER BY id DESC LIMIT 1",
            (sport, player, market, side, book)).fetchone()
        return dict(row) if row else None


def _sqlite_insert(db_path, fields) -> int:
    vals = [fields.get(c) for c in _FIELDS]
    with _sqlite_conn(db_path) as con:
        cur = con.execute(
            f"INSERT INTO line_snapshots ({','.join(_FIELDS)}) VALUES ({','.join('?' * len(_FIELDS))})",
            vals)
        return int(cur.lastrowid)


def _sqlite_series(db_path, sport, player, market, side=None, book=None) -> List[Dict]:
    q = "SELECT * FROM line_snapshots WHERE sport=? AND player=? AND market=?"
    params: List = [sport, player, market]
    if side is not None:
        q += " AND side=?"
        params.append(side)
    if book is not None:
        q += " AND book=?"
        params.append(book)
    q += " ORDER BY id ASC"
    with _sqlite_conn(db_path) as con:
        return [dict(r) for r in con.execute(q, params).fetchall()]


# ---- Postgres / Supabase backend (durable cloud storage) -------------------
_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS line_snapshots (
    id            BIGSERIAL PRIMARY KEY,
    captured_at   TEXT NOT NULL,
    sport         TEXT NOT NULL,
    game          TEXT, player TEXT NOT NULL, market TEXT NOT NULL, side TEXT NOT NULL,
    line REAL, price INTEGER, book TEXT NOT NULL, commence_time TEXT
);
"""


@contextmanager
def _pg_conn():
    import psycopg2                          # imported lazily so offline paths never need it
    dsn = _DATABASE_URL or ""
    kwargs = {} if "sslmode" in dsn else {"sslmode": "require"}   # Supabase requires SSL
    con = psycopg2.connect(dsn, **kwargs)
    try:
        with con.cursor() as cur:
            cur.execute(_PG_SCHEMA)
        con.commit()
        yield con
        con.commit()
    finally:
        con.close()


def _pg_latest(sport, player, market, side, book) -> Optional[Dict]:
    from psycopg2.extras import RealDictCursor
    with _pg_conn() as con, con.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM line_snapshots WHERE sport=%s AND player=%s AND market=%s AND side=%s "
            "AND book=%s ORDER BY id DESC LIMIT 1",
            (sport, player, market, side, book))
        row = cur.fetchone()
        return dict(row) if row else None


def _pg_insert(fields) -> int:
    vals = [fields.get(c) for c in _FIELDS]
    ph = ",".join(["%s"] * len(_FIELDS))
    with _pg_conn() as con, con.cursor() as cur:
        cur.execute(f"INSERT INTO line_snapshots ({','.join(_FIELDS)}) VALUES ({ph}) RETURNING id", vals)
        return int(cur.fetchone()[0])


def _pg_series(sport, player, market, side=None, book=None) -> List[Dict]:
    from psycopg2.extras import RealDictCursor
    q = "SELECT * FROM line_snapshots WHERE sport=%s AND player=%s AND market=%s"
    params: List = [sport, player, market]
    if side is not None:
        q += " AND side=%s"
        params.append(side)
    if book is not None:
        q += " AND book=%s"
        params.append(book)
    q += " ORDER BY id ASC"
    with _pg_conn() as con, con.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(q, params)
        return [dict(r) for r in cur.fetchall()]


# ---- public API — identical signatures, dispatches to the active backend ---
def record_snapshot(sport: str, player: str, market: str, side: str, line: Optional[float],
                    price: Optional[int], book: str, game: Optional[str] = None,
                    commence_time: Optional[str] = None, db_path: Optional[str] = None,
                    captured_at: Optional[str] = None) -> bool:
    """Insert a new snapshot row ONLY IF (line, price) differ from the most recently stored
    snapshot for this exact (sport, player, market, side, book) — the de-duplication described in
    this module's docstring. Returns True if a new row was written (a real line movement, or the
    first time this combination was ever seen), False if skipped (unchanged since last capture).

    db_path defaults to None, resolved to the module-level DB_PATH INSIDE this function body
    (not as an early-bound default parameter) — a deliberate choice, not an oversight: a default
    of `db_path: str = DB_PATH` binds DB_PATH's value once, at function-definition time, so a
    caller that later monkeypatches LH.DB_PATH (every test in this codebase's own suite does
    exactly this) would silently keep writing to the ORIGINAL path. Resolving it here instead
    means callers that never pass db_path explicitly — like capture_line_snapshots.py's runner —
    still pick up whatever LH.DB_PATH currently is, in both production and tests."""
    db_path = db_path if db_path is not None else DB_PATH
    captured_at = captured_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    prior = (_pg_latest(sport, player, market, side, book) if USING_POSTGRES
            else _sqlite_latest(db_path, sport, player, market, side, book))
    if prior is not None and prior.get("line") == line and prior.get("price") == price:
        return False   # unchanged since the last capture — nothing new to record

    fields = {"captured_at": captured_at, "sport": sport, "game": game, "player": player,
              "market": market, "side": side, "line": line, "price": price, "book": book,
              "commence_time": commence_time}
    if USING_POSTGRES:
        _pg_insert(fields)
    else:
        _sqlite_insert(db_path, fields)
    return True


def line_series(sport: str, player: str, market: str, side: Optional[str] = None,
                book: Optional[str] = None, db_path: Optional[str] = None) -> List[Dict]:
    """Every recorded snapshot for (sport, player, market), oldest first — the actual time series
    a line-movement chart plots. Optionally narrowed to one side and/or one book (a line can move
    differently at different books; without narrowing, rows from every book/side are interleaved
    in capture order, not per-series order — narrow to one book for a single clean line).

    Same dynamic db_path resolution as record_snapshot, for the same reason — see that
    function's docstring."""
    db_path = db_path if db_path is not None else DB_PATH
    if USING_POSTGRES:
        return _pg_series(sport, player, market, side, book)
    return _sqlite_series(db_path, sport, player, market, side, book)
