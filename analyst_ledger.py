"""
analyst_ledger.py — the Analyst Desk's permanent record of every call it publishes.

THE RULE THAT MAKES THE RECORD WORTH ANYTHING: a call is LOCKED the first time it is published.
record_calls inserts a row only if that exact (date, sport, player, market, side) is not already
there — a later page view with a moved line or a re-run model never rewrites it, and a play whose
game has already started (or whose date is in the past) is never logged at all, so a call can't be
"published" with hindsight. The row keeps the angles that fired, the line and the model's stated
chance as of first publication. After the game, settle_day grades it against real results with the
same retro.grade_play the rest of the platform uses.

NOT A SECOND GRADING ENGINE: retro.py decides what "hit" means; this module remembers calls and
attaches that verdict. Same dual-backend pattern as grading_history.py / line_history.py — SQLite
at data/analyst_ledger.db locally, Postgres (Supabase) when DATABASE_URL is configured, so the
record survives Streamlit Cloud reboots.

HONEST LIMITS: a game with only a bare date (no kickoff clock) can't be checked against the
clock, so it is logged on the day if the date is today or later; and a player with no stat line
(did not play) settles as a void (hit NULL, excluded from every rate) rather than a loss.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "analyst_ledger.db")

_COLS = ["logged_at", "call_date", "sport", "game", "game_date", "player", "player_id", "team",
         "market", "side", "line", "model_prob", "conviction", "price", "price_book",
         "angles", "cautions", "score", "gem", "chalk", "why"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyst_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at   TEXT NOT NULL,
    call_date   TEXT NOT NULL,
    sport       TEXT NOT NULL,
    game        TEXT,
    game_date   TEXT,
    player      TEXT NOT NULL,
    player_id   TEXT,
    team        TEXT,
    market      TEXT NOT NULL,
    side        TEXT NOT NULL,
    line        REAL,
    model_prob  REAL,
    conviction  REAL,
    price       REAL,
    price_book  TEXT,
    angles      TEXT,
    cautions    TEXT,
    score       REAL,
    gem         INTEGER,
    chalk       INTEGER,
    why         TEXT,
    hit         INTEGER,
    actual      REAL,
    settled_at  TEXT,
    last_line   REAL,
    last_price  REAL,
    marked_at   TEXT,
    published_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_analyst_call ON analyst_calls (call_date, sport, player, market, side);
CREATE TABLE IF NOT EXISTS analyst_posts (
    kind TEXT NOT NULL, sport TEXT NOT NULL, post_date TEXT NOT NULL, posted_at TEXT NOT NULL,
    PRIMARY KEY (kind, sport, post_date)
);
"""

# Columns added after the first release: an existing database gets them with ALTER TABLE.
_MARK_COLS = (("last_line", "REAL"), ("last_price", "REAL"), ("marked_at", "TEXT"), ("published_at", "TEXT"))

_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyst_calls (
    id          BIGSERIAL PRIMARY KEY,
    logged_at   TEXT NOT NULL, call_date TEXT NOT NULL, sport TEXT NOT NULL, game TEXT, game_date TEXT,
    player TEXT NOT NULL, player_id TEXT, team TEXT, market TEXT NOT NULL, side TEXT NOT NULL,
    line REAL, model_prob REAL, conviction REAL, price REAL, price_book TEXT, angles TEXT,
    cautions TEXT, score REAL, gem INTEGER, chalk INTEGER, why TEXT,
    hit INTEGER, actual REAL, settled_at TEXT,
    last_line REAL, last_price REAL, marked_at TEXT, published_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_analyst_call ON analyst_calls (call_date, sport, player, market, side);
CREATE TABLE IF NOT EXISTS analyst_posts (
    kind TEXT NOT NULL, sport TEXT NOT NULL, post_date TEXT NOT NULL, posted_at TEXT NOT NULL,
    PRIMARY KEY (kind, sport, post_date)
);
"""


def _database_url() -> Optional[str]:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url.strip()
    try:
        import streamlit as st
        val = st.secrets.get("DATABASE_URL")            # type: ignore[attr-defined]
        return str(val).strip() if val else None
    except Exception:
        return None


_DATABASE_URL = _database_url()
USING_POSTGRES = bool(_DATABASE_URL)


@contextmanager
def _sqlite_conn(db_path: str):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(_SCHEMA)
        have = {r[1] for r in con.execute("PRAGMA table_info(analyst_calls)")}
        for col, typ in _MARK_COLS:
            if col not in have:
                con.execute(f"ALTER TABLE analyst_calls ADD COLUMN {col} {typ}")
        yield con
        con.commit()
    finally:
        con.close()


_PG_READY = False             # the schema is checked/migrated ONCE per process, not on every query
_PG_LOCK_ID = 7352001         # advisory-lock key that serialises schema changes across app instances


def _pg_ensure_schema(con) -> None:
    """Make sure the tables and columns exist, touching the schema only when something is actually missing.
    The old code ran CREATE TABLE and four ALTER TABLE ... IF NOT EXISTS on EVERY query; ALTER TABLE takes a table
    lock even when it changes nothing, so two sessions (the app, the public app, the scheduled job, several reruns)
    could deadlock on each other (psycopg2.errors.DeadlockDetected). Now: read the catalog first (no lock), and when a
    change is needed take one advisory lock so only one session makes it at a time."""
    global _PG_READY
    if _PG_READY:
        return
    with con.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'analyst_calls' AND table_schema = current_schema()")
        have = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT to_regclass('analyst_posts')")
        posts = cur.fetchone()[0]
        if posts is None or any(col not in have for col, _typ in _MARK_COLS):
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_PG_LOCK_ID,))
            cur.execute(_PG_SCHEMA)
            for col, typ in _MARK_COLS:
                cur.execute(f"ALTER TABLE analyst_calls ADD COLUMN IF NOT EXISTS {col} {typ}")
    con.commit()
    _PG_READY = True


@contextmanager
def _pg_conn():
    import psycopg2
    dsn = _DATABASE_URL or ""
    kwargs = {} if "sslmode" in dsn else {"sslmode": "require"}
    con = psycopg2.connect(dsn, **kwargs)
    try:
        _pg_ensure_schema(con)
        yield con
        con.commit()
    finally:
        con.close()


PG_RETRIES = 3                # a query that loses a deadlock/serialization race is simply tried again


def _run(db_path: Optional[str], sql: str, params: tuple = (), fetch: bool = False):
    """Run one statement on the active backend. `sql` is written with ? placeholders."""
    if USING_POSTGRES:
        import time
        from psycopg2 import errors
        from psycopg2.extras import RealDictCursor
        for attempt in range(PG_RETRIES):
            try:
                with _pg_conn() as con, con.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql.replace("?", "%s"), params)
                    return [dict(r) for r in cur.fetchall()] if fetch else cur.rowcount
            except (errors.DeadlockDetected, errors.SerializationFailure):
                if attempt == PG_RETRIES - 1:
                    raise
                time.sleep(0.2 * (attempt + 1))
    path = db_path if db_path is not None else DB_PATH
    with _sqlite_conn(path) as con:
        cur = con.execute(sql, params)
        return [dict(r) for r in cur.fetchall()] if fetch else cur.rowcount


def _run_many(db_path: Optional[str], jobs: List[Tuple[str, tuple]]) -> List[int]:
    """Run several write statements on ONE connection and return each one's row count. On the cloud database every
    connection is a network handshake, so a card of 300 calls written one connection each took minutes; on one
    connection it is a single round trip's worth of setup. A deadlock retries the whole batch (nothing was committed)."""
    if not jobs:
        return []
    if USING_POSTGRES:
        import time
        from psycopg2 import errors
        from psycopg2.extras import RealDictCursor
        for attempt in range(PG_RETRIES):
            try:
                with _pg_conn() as con, con.cursor(cursor_factory=RealDictCursor) as cur:
                    counts = []
                    for sql, params in jobs:
                        cur.execute(sql.replace("?", "%s"), params)
                        counts.append(cur.rowcount)
                    return counts
            except (errors.DeadlockDetected, errors.SerializationFailure):
                if attempt == PG_RETRIES - 1:
                    raise
                time.sleep(0.2 * (attempt + 1))
    path = db_path if db_path is not None else DB_PATH
    with _sqlite_conn(path) as con:
        return [con.execute(sql, params).rowcount for sql, params in jobs]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def loggable(call: Dict, today_str: str, now: Optional[datetime] = None) -> bool:
    """Only calls that are genuinely pre-game can be locked: dated today or later, and — when the
    kickoff is known — still in the future."""
    if str(call.get("date") or "") < today_str:
        return False
    gd = call.get("game_date")
    if gd and len(str(gd)) > 10:
        try:
            import sports
            dt = sports.game_dt(gd)
            if dt is not None:
                now = now or datetime.now(timezone.utc)
                if dt <= now:
                    return False
        except Exception:                      # noqa: BLE001 — an unreadable time is "unknown", not "started"
            pass
    return True


def record_calls(calls: List[Dict], today_str: str, now: Optional[datetime] = None,
                 db_path: Optional[str] = None) -> int:
    """Insert every loggable call that is not already in the ledger. Returns how many were NEW."""
    logged_at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    jobs: List[Tuple[str, tuple]] = []
    for c in calls:
        if not loggable(c, today_str, now):
            continue
        vals = (logged_at, c["date"], c["sport"], c.get("game"), c.get("game_date"), c["player"],
                None if c.get("player_id") is None else str(c["player_id"]), c.get("team"),
                c["market"], c["side"], c.get("line"), c.get("model_prob"), c.get("conviction"),
                c.get("price"), c.get("price_book"),
                json.dumps([a["angle"] for a in c.get("angles", [])]),
                json.dumps(c.get("cautions") or []), c.get("score"),
                1 if c.get("gem") else 0, 1 if c.get("chalk") else 0, c.get("why"))
        sql = (f"INSERT INTO analyst_calls ({','.join(_COLS)}) VALUES ({','.join('?' * len(_COLS))}) "
               f"ON CONFLICT (call_date, sport, player, market, side) DO NOTHING")
        jobs.append((sql, vals))
    return sum(1 for n in _run_many(db_path, jobs) if n)


def mark_calls(calls: List[Dict], today_str: str, now: Optional[datetime] = None,
               db_path: Optional[str] = None) -> int:
    """Record the latest PRE-GAME line/price seen for calls already in the ledger, so the market's move
    since the call was locked can be measured later (the closing line is the last mark before the
    game starts). Only unsettled, still-pre-game calls are marked, and only at the book the call was
    locked at: a price at some other book says nothing about that call. The locked line/price/
    probability are never touched. Returns how many rows were updated."""
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    jobs: List[Tuple[str, tuple]] = []
    for c in calls:
        if not loggable(c, today_str, now):
            continue
        line = c.get("line")
        if c.get("book_state") == "posted":
            price = c.get("price")
        elif c.get("book_state") == "other_line" and line is not None and c.get("book_lines"):
            line = min((float(x) for x in c["book_lines"]), key=lambda x: abs(x - float(line)))
            price = None                          # the line itself moved; no like-for-like price
        else:
            continue
        book = c.get("price_book")
        if book is None or line is None:
            continue
        jobs.append(("UPDATE analyst_calls SET last_line=?, last_price=?, marked_at=? "
                     "WHERE call_date=? AND sport=? AND player=? AND market=? AND side=? "
                     "AND settled_at IS NULL AND price_book=?",
                     (line, price, stamp, c["date"], c["sport"], c["player"], c["market"], c["side"], book)))
    return sum(1 for n in _run_many(db_path, jobs) if n)


def mark_published(calls: List[Dict], posted_at: Optional[datetime] = None, db_path: Optional[str] = None) -> int:
    """Stamp calls as PUBLISHED — actually shown to the audience (posted to Discord) — as opposed to merely
    flagged by the model. Only rows already in the ledger are stamped, only once (the first publication
    time stands), and nothing else about the row changes. Returns how many rows were stamped."""
    stamp = (posted_at or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    jobs = [("UPDATE analyst_calls SET published_at=? WHERE call_date=? AND sport=? AND player=? "
             "AND market=? AND side=? AND published_at IS NULL",
             (stamp, c["date"], c["sport"], c["player"], c["market"], c["side"])) for c in calls]
    return sum(1 for n in _run_many(db_path, jobs) if n)


# ---------------------------------------------------------------------------
# Post claims (the scheduled publisher posts each card and recap once)
# ---------------------------------------------------------------------------
def claim_post(kind: str, sport: str, date_str: str, now: Optional[datetime] = None, db_path: Optional[str] = None) -> bool:
    """Claim the right to publish one (kind, sport, date) message. True for the first caller, False for every
    later one — so two overlapping runs, or a re-run, can never post the same card twice. A caller whose post
    then fails gives the claim back with release_post."""
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return bool(_run(db_path, "INSERT INTO analyst_posts (kind, sport, post_date, posted_at) VALUES (?, ?, ?, ?) "
                              "ON CONFLICT (kind, sport, post_date) DO NOTHING", (kind, sport, date_str, stamp)))


def release_post(kind: str, sport: str, date_str: str, db_path: Optional[str] = None) -> None:
    _run(db_path, "DELETE FROM analyst_posts WHERE kind=? AND sport=? AND post_date=?", (kind, sport, date_str))


def posted(kind: str, sport: str, date_str: str, db_path: Optional[str] = None) -> bool:
    return bool(_run(db_path, "SELECT 1 AS x FROM analyst_posts WHERE kind=? AND sport=? AND post_date=?",
                     (kind, sport, date_str), fetch=True))


# Fields that fix a call at the moment it was locked. The fingerprint covers ONLY these (never a result,
# never a later market mark), so it can be published the day it is made and checked against the full
# list long afterwards.
FINGERPRINT_FIELDS = ("logged_at", "call_date", "sport", "player", "market", "side", "line", "model_prob", "price", "price_book")


def _fp_cell(v) -> str:
    return "" if v is None else str(v)


def fingerprint_rows(rows: List[Dict]) -> List[List[str]]:
    """The canonical, sorted table behind the fingerprint (also what the record page's CSV contains)."""
    table = [[_fp_cell(r.get(f)) for f in FINGERPRINT_FIELDS] for r in rows]
    return sorted(table, key=lambda t: (t[1], t[2], t[3], t[4], t[5], t[0]))


def record_fingerprint(rows: List[Dict]) -> str:
    """SHA-256 (first 16 hex characters) of the locked-fields table: one line per call, fields joined with
    '|', lines joined with '\n', in the order fingerprint_rows returns. Empty record -> ''."""
    import hashlib
    table = fingerprint_rows(rows)
    if not table:
        return ""
    text = "\n".join("|".join(t) for t in table)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def _shape(r: Dict) -> Dict:
    r = dict(r)
    for k in ("angles", "cautions"):
        try:
            r[k] = json.loads(r.get(k) or "[]")
        except (TypeError, ValueError):
            r[k] = []
    r["gem"] = bool(r.get("gem"))
    r["chalk"] = bool(r.get("chalk"))
    r["date"] = r.get("call_date")
    return r


def fetch_calls(sport: Optional[str] = None, since: Optional[str] = None, settled_only: bool = False,
                db_path: Optional[str] = None) -> List[Dict]:
    q, params = "SELECT * FROM analyst_calls WHERE 1=1", []
    if sport:
        q += " AND sport=?"
        params.append(sport)
    if since:
        q += " AND call_date>=?"
        params.append(since)
    if settled_only:
        q += " AND hit IS NOT NULL"
    q += " ORDER BY call_date ASC, id ASC"
    return [_shape(r) for r in _run(db_path, q, tuple(params), fetch=True)]


def unsettled_dates(sport: str, before_date: str, db_path: Optional[str] = None) -> List[str]:
    rows = _run(db_path, "SELECT DISTINCT call_date FROM analyst_calls WHERE sport=? AND call_date<? "
                         "AND settled_at IS NULL ORDER BY call_date ASC", (sport, before_date), fetch=True)
    return [r["call_date"] for r in rows]


# ---------------------------------------------------------------------------
# Settling
# ---------------------------------------------------------------------------
def settle_day(sport: str, date_str: str, results: Dict, db_path: Optional[str] = None,
               now: Optional[datetime] = None) -> Dict:
    """Grade every unsettled call for (sport, date) against `results` (the sport engine's
    get_player_results(date) mapping). An EMPTY results mapping means the data isn't in yet, so
    nothing is touched and the day stays open. A player missing from a non-empty mapping settles
    as a void (hit NULL, settled_at set). Returns {"settled": n, "hits": h, "voids": v}."""
    import retro as R
    out = {"settled": 0, "hits": 0, "voids": 0}
    if not results:
        return out
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    rows = _run(db_path, "SELECT id, player_id, market, side, line FROM analyst_calls "
                         "WHERE sport=? AND call_date=? AND settled_at IS NULL", (sport, date_str), fetch=True)
    jobs: List[Tuple[str, tuple]] = []
    for r in rows:
        actuals = R._result_for(results, r.get("player_id"))
        hit = R.grade_play(r["market"], r["side"], r["line"], actuals) if r.get("line") is not None else None
        actual = (actuals or {}).get(R.MARKET_STAT.get(r["market"])) if actuals else None
        jobs.append(("UPDATE analyst_calls SET hit=?, actual=?, settled_at=? WHERE id=?",
                     (None if hit is None else (1 if hit else 0), actual, stamp, r["id"])))
        out["settled"] += 1
        if hit is None:
            out["voids"] += 1
        elif hit:
            out["hits"] += 1
    _run_many(db_path, jobs)
    return out


def settle_open_days(sport: str, dates: List[str], results_for: Callable[[str], Dict], *, max_days: int = 3,
                     max_tries: int = 12, db_path: Optional[str] = None) -> Dict:
    """Grade earlier open days, NEWEST first, skipping any day whose results aren't published.

    Why not the oldest three: a day whose results never arrive (a feed that was down that week, a sport whose per-game
    stats haven't been loaded) used to sit at the front of the queue and block every newer day behind it, so a sport
    could lock hundreds of calls and never grade one. Now a day with no results is only "waiting": it costs a try,
    not a slot, and the days after it still get graded. `max_days` bounds the days actually graded per call and
    `max_tries` the days looked at, so a cold page stays quick.

    Returns {"settled", "hits", "voids", "days": [(date, result)], "waiting": [dates with no results yet]}."""
    out: Dict = {"settled": 0, "hits": 0, "voids": 0, "days": [], "waiting": []}
    graded_days = tries = 0
    for d in sorted(set(dates), reverse=True):
        if graded_days >= max_days or tries >= max_tries:
            break
        tries += 1
        try:
            res = settle_day(sport, d, results_for(d), db_path=db_path)
        except Exception as exc:                                # noqa: BLE001 — one bad day must not block the others
            out["waiting"].append(d)
            out.setdefault("errors", []).append(f"{d}: {str(exc)[:80]}")
            continue
        if res["settled"]:
            graded_days += 1
            out["settled"] += res["settled"]
            out["hits"] += res["hits"]
            out["voids"] += res["voids"]
            out["days"].append((d, res))
        else:
            out["waiting"].append(d)
    return out
