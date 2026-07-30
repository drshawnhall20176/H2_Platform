"""
highlights.py — saved, named filter criteria that auto-flag matching plays on today's board.

Built directly on request, modeled on a real, existing workflow the community already uses
through a third-party tool (PropFinder): a person builds a NAMED profile ("Due for a Homer",
"Real-Price Locks") out of conditions on the model's own real fields, and every day the platform
tells them which plays on the current board actually match it — instead of them re-scanning the
whole slate by eye looking for the same pattern every single time.

STORAGE: SQLite at data/highlights.db, same dual-backend pattern as betlog.py (Postgres when
DATABASE_URL is configured, for durable cloud storage; SQLite otherwise). All SQL isolated here,
same reasoning as betlog.py's own docstring.

OWNERSHIP: owner=None (or "") is a SHARED "house" profile, visible to everyone. owner="<name>" is
personal to whoever typed that name when they built it — the same honest, no-real-login-yet
convention betlog.py's own "trader" field already established (see that column's own comment for
the full reasoning: this is a real step toward future multi-user support, not multi-user support
itself, since there's no login system asking "who are you" yet).

MATCHING: a profile's conditions are evaluated against the SAME real fields already on every
play from build_best_bets (ModelProb, Conviction, Market, Side, PriceSource, ConvictionSource,
LineSource, Due, AVG, SLG, OppERA, Grade computed on the fly via grading.conviction_to_grade) —
no new computation, no separate model, just naming and saving a real filter on data that already
exists. A play matches a profile only if it clears EVERY one of that profile's conditions (AND
logic) — the simplest, most predictable semantics for a first version; OR/grouping is real,
possible future scope, not built here.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "highlights.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS highlight_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    emoji      TEXT,
    sport      TEXT NOT NULL,
    owner      TEXT,
    conditions TEXT NOT NULL,
    created_ts TEXT NOT NULL
);
"""

_FIELDS = ["name", "emoji", "sport", "owner", "conditions", "created_ts"]


# ===========================================================================
# STORAGE — same dual-backend pattern as betlog.py; see that module's own
# docstring for the full reasoning. All SQL lives in this block.
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


def _sqlite_add(db_path, fields) -> int:
    vals = [fields.get(c) for c in _FIELDS]
    with _sqlite_conn(db_path) as con:
        cur = con.execute(
            f"INSERT INTO highlight_profiles ({','.join(_FIELDS)}) VALUES ({','.join('?' * len(_FIELDS))})", vals)
        return int(cur.lastrowid)


def _sqlite_list(db_path) -> List[Dict]:
    with _sqlite_conn(db_path) as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM highlight_profiles ORDER BY id DESC").fetchall()]


def _sqlite_delete(profile_id, db_path) -> None:
    with _sqlite_conn(db_path) as con:
        con.execute("DELETE FROM highlight_profiles WHERE id=?", [profile_id])


_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS highlight_profiles (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL, emoji TEXT, sport TEXT NOT NULL, owner TEXT,
    conditions TEXT NOT NULL, created_ts TEXT NOT NULL
);
"""


@contextmanager
def _pg_conn():
    import psycopg2
    dsn = _DATABASE_URL or ""
    try:
        kwargs = {} if "sslmode" in dsn else {"sslmode": "require"}
        con = psycopg2.connect(dsn, **kwargs)
    except psycopg2.ProgrammingError:
        from urllib.parse import urlparse, unquote
        p = urlparse(dsn)
        con = psycopg2.connect(
            host=p.hostname, port=p.port or 5432,
            dbname=(p.path or "/postgres").lstrip("/"),
            user=unquote(p.username or ""), password=unquote(p.password or ""),
            sslmode="require",
        )
    try:
        with con.cursor() as cur:
            cur.execute(_PG_SCHEMA)
        con.commit()
        yield con
        con.commit()
    finally:
        con.close()


def _pg_add(fields) -> int:
    vals = [fields.get(c) for c in _FIELDS]
    ph = ",".join(["%s"] * len(_FIELDS))
    with _pg_conn() as con, con.cursor() as cur:
        cur.execute(f"INSERT INTO highlight_profiles ({','.join(_FIELDS)}) VALUES ({ph}) RETURNING id", vals)
        return int(cur.fetchone()[0])


def _pg_list() -> List[Dict]:
    from psycopg2.extras import RealDictCursor
    with _pg_conn() as con, con.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM highlight_profiles ORDER BY id DESC")
        return [dict(r) for r in cur.fetchall()]


def _pg_delete(profile_id) -> None:
    with _pg_conn() as con, con.cursor() as cur:
        cur.execute("DELETE FROM highlight_profiles WHERE id=%s", [profile_id])


# ---- public API -------------------------------------------------------------
def add_profile(name: str, sport: str, conditions: List[Dict], emoji: str = "⭐",
                owner: Optional[str] = None, db_path: str = DB_PATH) -> int:
    """Save a new profile. conditions is a list of {"field", "op", "value"} dicts, ANDed
    together. owner=None/"" makes it a shared house profile visible to everyone; a real name
    makes it personal to whoever typed that name (see this module's own docstring for the
    honest reasoning on why that's a typed name, not a real login)."""
    fields = {
        "name": name, "emoji": emoji, "sport": sport, "owner": owner or None,
        "conditions": json.dumps(conditions),
        "created_ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return _pg_add(fields) if USING_POSTGRES else _sqlite_add(db_path, fields)


def list_profiles(sport: str, owner: Optional[str] = None, db_path: str = DB_PATH) -> List[Dict]:
    """All SHARED (house) profiles for this sport, plus this owner's own PERSONAL profiles if a
    name is given. Every returned dict's "conditions" is already decoded back into a real list,
    not the raw JSON string. owner=None returns only the shared house profiles."""
    rows = _pg_list() if USING_POSTGRES else _sqlite_list(db_path)
    out = []
    for r in rows:
        if r.get("sport") != sport:
            continue
        is_shared = not r.get("owner")
        is_mine = owner and r.get("owner") == owner
        if is_shared or is_mine:
            r = dict(r)
            try:
                r["conditions"] = json.loads(r["conditions"])
            except (TypeError, ValueError):
                r["conditions"] = []
            out.append(r)
    return out


def delete_profile(profile_id: int, db_path: str = DB_PATH) -> None:
    _pg_delete(profile_id) if USING_POSTGRES else _sqlite_delete(profile_id, db_path)


# ---- matching -----------------------------------------------------------------
_OPS = {
    ">=": lambda a, b: a is not None and a >= b,
    "<=": lambda a, b: a is not None and a <= b,
    ">":  lambda a, b: a is not None and a > b,
    "<":  lambda a, b: a is not None and a < b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "in": lambda a, b: a in (b or []),
}
SUPPORTED_OPS = list(_OPS.keys())   # public, ordered view for building selectors in the UI layer

# Fields a condition can reference, and where each one comes from -- either a direct key
# already on every play from build_best_bets, or "grade" (computed on the fly here, since
# the letter grade isn't itself stored on the play, only the Conviction/_ceiling it's derived
# from). Kept as an explicit allowlist rather than "any key on the dict" so a malformed or
# stale saved condition (e.g. referencing a field a future refactor renames) fails visibly in
# matches_profile below, not silently as a KeyError deep in a Streamlit callback.
CONDITION_FIELDS = [
    "Market", "Side", "ModelProb", "Conviction", "PriceSource", "ConvictionSource",
    "LineSource", "OppERA", "Due", "AVG", "SLG", "Grade",
]


def _play_value(play: Dict, field: str):
    if field == "Grade":
        import grading
        g = grading.conviction_to_grade(play.get("Conviction"), play.get("_ceiling"))
        return g["letter"] if g else None
    return play.get(field)


def matches_profile(play: Dict, profile: Dict) -> bool:
    """True only if `play` clears EVERY condition in profile["conditions"] (AND logic). A
    condition referencing an unknown field, or an unknown operator, is treated as NOT matching
    (fails closed, not open) rather than raising -- a malformed saved profile should never crash
    the page a person is trying to use, it should just correctly show zero matches for that one
    broken condition."""
    for cond in profile.get("conditions", []):
        field, op, value = cond.get("field"), cond.get("op"), cond.get("value")
        if field not in CONDITION_FIELDS or op not in _OPS:
            return False
        try:
            if not _OPS[op](_play_value(play, field), value):
                return False
        except TypeError:
            return False
    return True


def matches_for_profile(plays: List[Dict], profile: Dict) -> List[Dict]:
    """Every play on the current board that matches this one profile."""
    return [p for p in plays if matches_profile(p, profile)]


def highlights_by_profile(plays: List[Dict], profiles: List[Dict]) -> List[Dict]:
    """[{**profile, "matches": [...]}] for every profile, run once against the same plays list.
    Profiles with zero matches are still included (not silently dropped) -- an empty, honestly-
    reported result is different information from the profile not existing at all."""
    return [{**profile, "matches": matches_for_profile(plays, profile)} for profile in profiles]


# ---- starter / house profiles -------------------------------------------------
# A few pre-built, real, immediately-testable profiles for MLB -- every condition below
# references a field that's genuinely computed and real, not a placeholder. Modeled loosely on
# the kind of named profiles the community already builds by hand in PropFinder (Insane/Elite/
# Fly Ball/Line Drive), translated onto this platform's own real fields rather than copied
# blind -- PropFinder's profiles lean on recent batted-ball data this platform doesn't compute
# the same way; these lean on what IS real and available here (Due/barrels, real captured
# prices, real market-based grading).
STARTER_PROFILES_MLB = [
    {
        "name": "Due for a Homer", "emoji": "💣", "sport": "MLB", "owner": None,
        "conditions": [
            {"field": "Market", "op": "==", "value": "Batter HR"},
            {"field": "Due", "op": ">=", "value": 0.02},
        ],
    },
    {
        "name": "Real-Price Locks", "emoji": "🎯", "sport": "MLB", "owner": None,
        "conditions": [
            {"field": "PriceSource", "op": "==", "value": "book"},
            {"field": "Grade", "op": "in", "value": ["A", "B"]},
        ],
    },
    {
        "name": "High Confidence", "emoji": "🚀", "sport": "MLB", "owner": None,
        "conditions": [
            {"field": "Grade", "op": "in", "value": ["A", "B"]},
            {"field": "ModelProb", "op": ">=", "value": 0.75},
        ],
    },
    {
        "name": "Beat-Up Starter", "emoji": "🔥", "sport": "MLB", "owner": None,
        "conditions": [
            {"field": "OppERA", "op": ">=", "value": 4.75},
            {"field": "Grade", "op": "in", "value": ["A", "B", "C"]},
        ],
    },
]


def ensure_starter_profiles(sport: str = "MLB", db_path: str = DB_PATH) -> None:
    """Seed the starter house profiles for this sport if none exist yet -- idempotent, safe to
    call on every page load. Only seeds when there are genuinely ZERO shared profiles for this
    sport yet, so it never overwrites or duplicates anything a real person has already built or
    edited by hand."""
    existing = list_profiles(sport, owner=None, db_path=db_path)
    if existing:
        return
    starters = STARTER_PROFILES_MLB if sport == "MLB" else []
    for p in starters:
        add_profile(p["name"], p["sport"], p["conditions"], emoji=p["emoji"], owner=None,
                   db_path=db_path)
