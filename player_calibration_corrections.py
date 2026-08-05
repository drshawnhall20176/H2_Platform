"""
player_calibration_corrections.py — persistent storage for FITTED PLAYER-LEVEL calibration
corrections, added directly on request: a real, second, STACKED correction layer on top of
calibration_corrections.py's own market-level one. retro.fit_player_calibration turns real
accumulated grading_history into a real, shrunk per-player gap (a specific hitter who's been a
genuine "HR or bust" read, surfacing as a top play far more consistently than that real pattern
justifies -- the market-wide correction can't reach this, since it corrects every player in a
market the same way); this module stores it so the live prediction pipeline
(projections.build_best_bets, the ONE shared source every page already draws its plays from) can
look it up and apply it automatically, stacked on top of the market-level correction, everywhere
at once.

WHY A SEPARATE MODULE FROM calibration_corrections.py, NOT ONE SHARED TABLE: the two real shapes
genuinely differ (market-level: slope+intercept, fit via a real bucketed regression; player-level:
a single real shrunk gap, fit by reusing retro.player_calibration's own already-trusted average-
vs-actual comparison directly -- a player's own real settled-play count is far too thin for the
bucketed regression the market-level correction needs). Forcing both into one table with a pile of
nullable, differently-meaning columns would be genuinely confusing, not a real simplification.

APPEND-ONLY, ON PURPOSE -- NOT REPLACED, same real reason calibration_corrections.py's own
docstring already gives: every real refit is its own permanent audit entry. latest_fit() reads the
most recent row for ONE (sport, player_id); latest_fits_for_sport() reads the most recent row for
EVERY player at once (a real, necessary addition market-level never needed -- there are only ~17
real markets platform-wide, cheap to look up individually in a loop, but a full slate can carry
hundreds of distinct players, so build_best_bets needs one real bulk query, not hundreds of
individual ones, to stay fast).

STORAGE: same dual-backend pattern as every other storage module in this codebase, deliberately --
SQLite at data/player_calibration_corrections.db for local/dev, Postgres (Supabase) when
DATABASE_URL is configured, so a real fitted correction survives Streamlit Cloud reboots the same
way everything else already does.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, List, Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "player_calibration_corrections.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS player_calibration_fits (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    fitted_at      TEXT NOT NULL,
    sport          TEXT NOT NULL,
    player_id      INTEGER NOT NULL,
    player         TEXT,
    n              INTEGER NOT NULL,
    weight         REAL,
    raw_gap        REAL,
    shrunk_gap     REAL NOT NULL,
    min_n_used     INTEGER
);
"""

_FIELDS = ["fitted_at", "sport", "player_id", "player", "n", "weight", "raw_gap",
           "shrunk_gap", "min_n_used"]


# ===========================================================================
# STORAGE — SQLite for local/dev, Postgres (Supabase) for durable cloud storage.
# Same auto-selection and identical-signatures-across-backends pattern as every other storage
# module in this codebase; see calibration_corrections.py's own comment for the full reasoning.
# Kept as its own small implementation here so this file has zero import-time dependency on the
# others -- swappable/removable on its own, same real reason as always.
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
            f"INSERT INTO player_calibration_fits ({','.join(_FIELDS)}) VALUES ({','.join('?' * len(_FIELDS))})",
            vals)
        return int(cur.lastrowid)


def _sqlite_latest(db_path, sport, player_id) -> Optional[Dict]:
    with _sqlite_conn(db_path) as con:
        row = con.execute(
            "SELECT * FROM player_calibration_fits WHERE sport=? AND player_id=? ORDER BY id DESC LIMIT 1",
            (sport, player_id)).fetchone()
        return dict(row) if row else None


def _sqlite_latest_for_sport(db_path, sport) -> Dict[int, Dict]:
    with _sqlite_conn(db_path) as con:
        rows = con.execute("""
            SELECT t1.* FROM player_calibration_fits t1
            INNER JOIN (
                SELECT player_id, MAX(id) AS max_id FROM player_calibration_fits
                WHERE sport=? GROUP BY player_id
            ) t2 ON t1.id = t2.max_id
            """, (sport,)).fetchall()
        return {r["player_id"]: dict(r) for r in rows}


def _sqlite_history(db_path, sport, player_id) -> List[Dict]:
    q = "SELECT * FROM player_calibration_fits WHERE sport=?"
    params: List = [sport]
    if player_id is not None:
        q += " AND player_id=?"
        params.append(player_id)
    q += " ORDER BY id ASC"
    with _sqlite_conn(db_path) as con:
        return [dict(r) for r in con.execute(q, params).fetchall()]


# ---- Postgres / Supabase backend (durable cloud storage) -------------------
_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS player_calibration_fits (
    id             BIGSERIAL PRIMARY KEY,
    fitted_at      TEXT NOT NULL,
    sport          TEXT NOT NULL,
    player_id      INTEGER NOT NULL,
    player TEXT, n INTEGER NOT NULL, weight REAL, raw_gap REAL,
    shrunk_gap REAL NOT NULL, min_n_used INTEGER
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
        cur.execute(f"INSERT INTO player_calibration_fits ({','.join(_FIELDS)}) VALUES ({ph}) RETURNING id", vals)
        return int(cur.fetchone()[0])


def _pg_latest(sport, player_id) -> Optional[Dict]:
    from psycopg2.extras import RealDictCursor
    with _pg_conn() as con, con.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM player_calibration_fits WHERE sport=%s AND player_id=%s "
                    "ORDER BY id DESC LIMIT 1", (sport, player_id))
        row = cur.fetchone()
        return dict(row) if row else None


def _pg_latest_for_sport(sport) -> Dict[int, Dict]:
    from psycopg2.extras import RealDictCursor
    with _pg_conn() as con, con.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT t1.* FROM player_calibration_fits t1
            INNER JOIN (
                SELECT player_id, MAX(id) AS max_id FROM player_calibration_fits
                WHERE sport=%s GROUP BY player_id
            ) t2 ON t1.id = t2.max_id
            """, (sport,))
        return {r["player_id"]: dict(r) for r in cur.fetchall()}


def _pg_history(sport, player_id) -> List[Dict]:
    from psycopg2.extras import RealDictCursor
    q = "SELECT * FROM player_calibration_fits WHERE sport=%s"
    params: List = [sport]
    if player_id is not None:
        q += " AND player_id=%s"
        params.append(player_id)
    q += " ORDER BY id ASC"
    with _pg_conn() as con, con.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(q, params)
        return [dict(r) for r in cur.fetchall()]


# ---- public API — identical signatures, dispatches to the active backend ---
def record_fit(sport: str, player_id: int, fit: Dict, min_n_used: Optional[int] = None,
              db_path: Optional[str] = None, fitted_at: Optional[str] = None) -> int:
    """Persist ONE real player-level fit -- pass retro.fit_player_calibration's own per-player
    dict directly (player, n, weight, raw_gap, shrunk_gap already match this table's own columns,
    no separate mapping needed). Always appends a new row, never replaces -- see this module's own
    docstring for why that's the real, deliberate design, not an oversight.

    db_path defaults to None, resolved to the module-level DB_PATH INSIDE this function body --
    same deliberate reason every sibling storage module's own docstring already gives: a caller
    that monkeypatches this module's DB_PATH (every test in this file does exactly that) must
    still be honored even when db_path isn't passed explicitly."""
    db_path = db_path if db_path is not None else DB_PATH
    fitted_at = fitted_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    fields = {"fitted_at": fitted_at, "sport": sport, "player_id": player_id,
              "player": fit.get("player"), "n": fit["n"], "weight": fit.get("weight"),
              "raw_gap": fit.get("raw_gap"), "shrunk_gap": fit["shrunk_gap"],
              "min_n_used": min_n_used}
    if USING_POSTGRES:
        return _pg_insert(fields)
    return _sqlite_insert(db_path, fields)


def latest_fit(sport: str, player_id: int, db_path: Optional[str] = None) -> Optional[Dict]:
    """The CURRENTLY ACTIVE correction for ONE (sport, player_id) -- the most recent real fit
    ever recorded, or None if this player has never accumulated enough real evidence to fit one.
    Prefer latest_fits_for_sport below for a real board build (one query for every player, not
    one per player) -- this single-player lookup exists for the rare real caller that only needs
    one specific player, not a whole slate's worth.

    Same dynamic db_path resolution as record_fit, for the same reason."""
    db_path = db_path if db_path is not None else DB_PATH
    if USING_POSTGRES:
        return _pg_latest(sport, player_id)
    return _sqlite_latest(db_path, sport, player_id)


def latest_fits_for_sport(sport: str, db_path: Optional[str] = None) -> Dict[int, Dict]:
    """{player_id: latest real fit} for EVERY player with a real correction on file for `sport`,
    in ONE real query -- the real reason this module exists as more than a copy of calibration_
    corrections.py: a full slate can carry hundreds of distinct real players, and build_best_bets
    needs to check all of them, not query one at a time. Real, empty dict when no player has
    cleared the real floor yet for this sport (the common case until real volume accumulates),
    never a guessed correction.

    Same dynamic db_path resolution as record_fit, for the same reason."""
    db_path = db_path if db_path is not None else DB_PATH
    if USING_POSTGRES:
        return _pg_latest_for_sport(sport)
    return _sqlite_latest_for_sport(db_path, sport)


def fit_history(sport: str, player_id: Optional[int] = None, db_path: Optional[str] = None) -> List[Dict]:
    """Every real fit ever recorded for `sport`, oldest first -- optionally narrowed to one
    player. THE real audit trail: what changed, when, on how much evidence.

    Same dynamic db_path resolution as record_fit, for the same reason."""
    db_path = db_path if db_path is not None else DB_PATH
    if USING_POSTGRES:
        return _pg_history(sport, player_id)
    return _sqlite_history(db_path, sport, player_id)
