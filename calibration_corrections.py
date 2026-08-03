"""
calibration_corrections.py — persistent storage for FITTED calibration corrections, the
mechanism that actually closes the feedback loop: retro.fit_market_calibration turns real
accumulated grading_history into a real (slope, intercept) correction; this module stores it so
the live prediction pipeline (projections.build_best_bets, the ONE shared source every page --
Top Leans, Graded Picks, Suggested Parlays, Speculative Basket -- already draws its plays from)
can look it up and apply it to tomorrow's own ModelProb, automatically, everywhere at once.

WHY A SEPARATE MODULE FROM grading_history.py: that module stores raw graded PLAYS (many rows a
day, the input); this module stores fitted CORRECTIONS (one row per (sport, market) per time a
weekly refit runs, the output). Different shape, different growth rate, different real question
("what happened" vs "what did we learn and change") -- the same real distinction line_history.py's
own docstring already draws between itself and betlog.py, applied here to a third real case.

APPEND-ONLY, ON PURPOSE -- NOT REPLACED LIKE grading_history's own per-day rows: every real refit
is its own permanent audit entry, never overwritten. latest_fit() reads the most recent row per
(sport, market) for live use; fit_history() returns every one ever made, oldest first. That
history IS the real, subscriber-facing story this whole mechanism exists to make possible: not
"we retrain nightly," but "here is every real adjustment we've made, when, on how much evidence."
Deleting or overwriting a past fit would quietly erase the one thing this table is actually for.

STORAGE: same dual-backend pattern as betlog.py/line_history.py/grading_history.py, deliberately
-- SQLite at data/calibration_corrections.db for local/dev, Postgres (Supabase) when DATABASE_URL
is configured, so a real fitted correction survives Streamlit Cloud reboots the same way bets,
line history, and graded-play history already do.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, List, Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "calibration_corrections.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calibration_fits (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    fitted_at      TEXT NOT NULL,
    sport          TEXT NOT NULL,
    market         TEXT NOT NULL,
    slope          REAL NOT NULL,
    intercept      REAL NOT NULL,
    raw_slope      REAL,
    raw_intercept  REAL,
    n              INTEGER NOT NULL,
    weight         REAL,
    min_n_used     INTEGER
);
"""

_FIELDS = ["fitted_at", "sport", "market", "slope", "intercept", "raw_slope", "raw_intercept",
           "n", "weight", "min_n_used"]


# ===========================================================================
# STORAGE — SQLite for local/dev, Postgres (Supabase) for durable cloud storage.
# Same auto-selection and identical-signatures-across-backends pattern as betlog.py/
# line_history.py/grading_history.py; see any of those modules' own comments for the full
# reasoning. Kept as its own small implementation here so this file has zero import-time
# dependency on the others -- swappable/removable on its own, same real reason as always.
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


def _sqlite_insert(db_path, fields) -> int:
    vals = [fields.get(c) for c in _FIELDS]
    with _sqlite_conn(db_path) as con:
        cur = con.execute(
            f"INSERT INTO calibration_fits ({','.join(_FIELDS)}) VALUES ({','.join('?' * len(_FIELDS))})",
            vals)
        return int(cur.lastrowid)


def _sqlite_latest(db_path, sport, market) -> Optional[Dict]:
    with _sqlite_conn(db_path) as con:
        row = con.execute(
            "SELECT * FROM calibration_fits WHERE sport=? AND market=? ORDER BY id DESC LIMIT 1",
            (sport, market)).fetchone()
        return dict(row) if row else None


def _sqlite_history(db_path, sport, market) -> List[Dict]:
    q = "SELECT * FROM calibration_fits WHERE sport=?"
    params: List = [sport]
    if market is not None:
        q += " AND market=?"
        params.append(market)
    q += " ORDER BY id ASC"
    with _sqlite_conn(db_path) as con:
        return [dict(r) for r in con.execute(q, params).fetchall()]


# ---- Postgres / Supabase backend (durable cloud storage) -------------------
_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS calibration_fits (
    id             BIGSERIAL PRIMARY KEY,
    fitted_at      TEXT NOT NULL,
    sport          TEXT NOT NULL,
    market         TEXT NOT NULL,
    slope REAL NOT NULL, intercept REAL NOT NULL, raw_slope REAL, raw_intercept REAL,
    n INTEGER NOT NULL, weight REAL, min_n_used INTEGER
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


def _pg_insert(fields) -> int:
    vals = [fields.get(c) for c in _FIELDS]
    ph = ",".join(["%s"] * len(_FIELDS))
    with _pg_conn() as con, con.cursor() as cur:
        cur.execute(f"INSERT INTO calibration_fits ({','.join(_FIELDS)}) VALUES ({ph}) RETURNING id", vals)
        return int(cur.fetchone()[0])


def _pg_latest(sport, market) -> Optional[Dict]:
    from psycopg2.extras import RealDictCursor
    with _pg_conn() as con, con.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM calibration_fits WHERE sport=%s AND market=%s "
                    "ORDER BY id DESC LIMIT 1", (sport, market))
        row = cur.fetchone()
        return dict(row) if row else None


def _pg_history(sport, market) -> List[Dict]:
    from psycopg2.extras import RealDictCursor
    q = "SELECT * FROM calibration_fits WHERE sport=%s"
    params: List = [sport]
    if market is not None:
        q += " AND market=%s"
        params.append(market)
    q += " ORDER BY id ASC"
    with _pg_conn() as con, con.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(q, params)
        return [dict(r) for r in cur.fetchall()]


# ---- public API — identical signatures, dispatches to the active backend ---
def record_fit(sport: str, market: str, fit: Dict, min_n_used: Optional[int] = None,
              db_path: Optional[str] = None, fitted_at: Optional[str] = None) -> int:
    """Persist ONE real fit -- pass retro.fit_market_calibration's own return dict directly
    (slope, intercept, raw_slope, raw_intercept, n, weight already match this table's own
    columns, no separate mapping needed). Always appends a new row, never replaces -- see this
    module's own docstring for why that's the real, deliberate design, not an oversight.

    db_path defaults to None, resolved to the module-level DB_PATH INSIDE this function body --
    same deliberate reason every sibling storage module's own docstring already gives: a caller
    that monkeypatches this module's DB_PATH (every test in this file does exactly that) must
    still be honored even when db_path isn't passed explicitly."""
    db_path = db_path if db_path is not None else DB_PATH
    fitted_at = fitted_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    fields = {"fitted_at": fitted_at, "sport": sport, "market": market,
              "slope": fit["slope"], "intercept": fit["intercept"],
              "raw_slope": fit.get("raw_slope"), "raw_intercept": fit.get("raw_intercept"),
              "n": fit["n"], "weight": fit.get("weight"), "min_n_used": min_n_used}
    if USING_POSTGRES:
        return _pg_insert(fields)
    return _sqlite_insert(db_path, fields)


def latest_fit(sport: str, market: str, db_path: Optional[str] = None) -> Optional[Dict]:
    """The CURRENTLY ACTIVE correction for (sport, market) -- the most recent real fit ever
    recorded, or None if this market has never accumulated enough real evidence to fit one. This
    is what projections.build_best_bets looks up and applies to today's own ModelProb.

    Same dynamic db_path resolution as record_fit, for the same reason."""
    db_path = db_path if db_path is not None else DB_PATH
    if USING_POSTGRES:
        return _pg_latest(sport, market)
    return _sqlite_latest(db_path, sport, market)


def fit_history(sport: str, market: Optional[str] = None, db_path: Optional[str] = None) -> List[Dict]:
    """Every real fit ever recorded for `sport`, oldest first -- optionally narrowed to one
    market. THE real audit trail: what changed, when, on how much evidence. This is what a
    subscriber-facing "here's what we've learned and adjusted" view reads from.

    Same dynamic db_path resolution as record_fit, for the same reason."""
    db_path = db_path if db_path is not None else DB_PATH
    if USING_POSTGRES:
        return _pg_history(sport, market)
    return _sqlite_history(db_path, sport, market)
