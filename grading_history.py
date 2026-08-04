"""
grading_history.py — persistent storage for every graded PLAY the model has ever made, not just
the ones someone happened to log as a real bet.

WHY THIS EXISTS: retro.grade_slate already grades every play on a slate against real results
(Hit True/False/None) every single time Command Center or Retrospective loads — and retro.
_calibration/retro.player_calibration already know how to turn a pile of graded plays into a real
calibration read. None of that has ever been the problem. The problem is that the grading gets
thrown away the moment the page session ends: Command Center's own "yesterday's catches" panel
and Retrospective's own hit/miss view both recompute yesterday's grading fresh on every visit,
and neither one saves it anywhere. Checked directly against the real bets.db: 41 rows total, one
market, zero real closing-line data — because that table only ever captured what a person chose
to log as an actual bet, never what the model itself predicted across every market, every day,
whether anyone bet it or not. That's a tiny, biased sample to learn anything real from.

THIS MODULE IS STORAGE ONLY, deliberately, not a second, competing calibration engine. It exists
to make retro.py's own already-trusted grading queryable across real accumulated TIME instead of
one session at a time — record_graded_slate saves grade_slate's own output; fetch_graded_plays
reads it back in the exact shape retro._calibration and retro.player_calibration already expect,
so real historical calibration is just "fetch_graded_plays(...) -> retro._calibration(...)", no
new statistical logic invented here. Keeping the two jobs separate (retro.py decides what
"graded" means; this module just remembers it) means a future change to how grading itself works
doesn't require touching storage, and vice versa.

NOT A SUBSTITUTE FOR STATISTICAL DISCIPLINE: this module will happily hand back 12 rows if that's
all that exists for a market. Every caller is responsible for its own real sample-size floor
before treating anything pulled from here as a signal worth acting on — the exact same discipline
retro.player_calibration's own min_plays=8 default already enforces one level up. Recording data
is always safe; concluding something from too little of it is not, and that responsibility
doesn't move to this module just because the data now persists.

STORAGE: same dual-backend pattern as betlog.py/line_history.py, deliberately — SQLite at
data/grading_history.db for local/dev, Postgres (Supabase) when DATABASE_URL is configured, so
this survives Streamlit Cloud reboots the same way bets and line history already do. A SEPARATE
table and file from both — this is per-PLAY model-accuracy history (every play, every market,
independent of whether it was ever bet), a different shape and a different real question than
either "what did I bet" (betlog.py) or "how did this line move" (line_history.py).

IDEMPOTENT PER (slate_date, sport), NOT per-row: record_graded_slate deletes any existing rows
for that exact (slate_date, sport) before inserting the fresh set, in one transaction. Grading
naturally happens for a WHOLE day at once (grade_slate takes the whole day's plays list), so
replacing the whole day's rows atomically is the real unit of idempotency here — a person
revisiting Retrospective for the same date five times writes the same real rows five times over
without this, silently multiplying every count going into calibration and quietly corrupting it
in a way that wouldn't show up as an error anywhere. A fine-grained per-row upsert would need a
uniqueness key fragile to exactly the kind of real-world duplicate plays (same player, same
market, same side, same line, two different games in a doubleheader) this schema doesn't rule out
being genuinely valid twice in one day.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, List, Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "grading_history.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS graded_plays (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    graded_at    TEXT NOT NULL,
    slate_date   TEXT NOT NULL,
    sport        TEXT NOT NULL,
    market       TEXT NOT NULL,
    player       TEXT,
    player_id    INTEGER,
    side         TEXT,
    line         REAL,
    model_prob   REAL,
    conviction   REAL,
    hit          INTEGER,
    actual_value REAL,
    rank         INTEGER,
    of_total     INTEGER
);
"""

_FIELDS = ["graded_at", "slate_date", "sport", "market", "player", "player_id", "side", "line",
           "model_prob", "conviction", "hit", "actual_value", "rank", "of_total"]


# ===========================================================================
# STORAGE — SQLite for local/dev, Postgres (Supabase) for durable cloud storage.
# Same auto-selection and identical-signatures-across-backends pattern as betlog.py/
# line_history.py; see either module's own comment for the full reasoning. Kept as its own small
# implementation here (not a shared helper) so this file has zero import-time dependency on
# either — grading history is conceptually independent of both and should stay swappable/
# removable on its own, the same real reason line_history.py gives for doing the same thing.
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
        # Migration for a real DB created before rank/of_total existed (added directly on
        # request, for retro.catch_rate_by_rank) -- same exact ALTER-TABLE-if-missing pattern
        # betlog.py's own connection setup already uses for this identical class of schema
        # growth, not a new approach invented here.
        cols = [r[1] for r in con.execute("PRAGMA table_info(graded_plays)").fetchall()]
        if "rank" not in cols:
            con.execute("ALTER TABLE graded_plays ADD COLUMN rank INTEGER")
        if "of_total" not in cols:
            con.execute("ALTER TABLE graded_plays ADD COLUMN of_total INTEGER")
        yield con
        con.commit()
    finally:
        con.close()


def _sqlite_replace_day(db_path, slate_date, sport, rows) -> int:
    with _sqlite_conn(db_path) as con:
        con.execute("DELETE FROM graded_plays WHERE slate_date=? AND sport=?", (slate_date, sport))
        n = 0
        for fields in rows:
            vals = [fields.get(c) for c in _FIELDS]
            con.execute(
                f"INSERT INTO graded_plays ({','.join(_FIELDS)}) VALUES ({','.join('?' * len(_FIELDS))})",
                vals)
            n += 1
        return n


def _sqlite_fetch(db_path, sport, market, since_date) -> List[Dict]:
    q = "SELECT * FROM graded_plays WHERE sport=?"
    params: List = [sport]
    if market is not None:
        q += " AND market=?"
        params.append(market)
    if since_date is not None:
        q += " AND slate_date>=?"
        params.append(since_date)
    q += " ORDER BY slate_date ASC, id ASC"
    with _sqlite_conn(db_path) as con:
        return [dict(r) for r in con.execute(q, params).fetchall()]


# ---- Postgres / Supabase backend (durable cloud storage) -------------------
_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS graded_plays (
    id           BIGSERIAL PRIMARY KEY,
    graded_at    TEXT NOT NULL,
    slate_date   TEXT NOT NULL,
    sport        TEXT NOT NULL,
    market       TEXT NOT NULL,
    player TEXT, player_id INTEGER, side TEXT, line REAL, model_prob REAL, conviction REAL,
    hit INTEGER, actual_value REAL
);
ALTER TABLE graded_plays ADD COLUMN IF NOT EXISTS rank INTEGER;
ALTER TABLE graded_plays ADD COLUMN IF NOT EXISTS of_total INTEGER;
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


def _pg_replace_day(slate_date, sport, rows) -> int:
    with _pg_conn() as con, con.cursor() as cur:
        cur.execute("DELETE FROM graded_plays WHERE slate_date=%s AND sport=%s", (slate_date, sport))
        n = 0
        ph = ",".join(["%s"] * len(_FIELDS))
        for fields in rows:
            vals = [fields.get(c) for c in _FIELDS]
            cur.execute(f"INSERT INTO graded_plays ({','.join(_FIELDS)}) VALUES ({ph})", vals)
            n += 1
        return n


def _pg_fetch(sport, market, since_date) -> List[Dict]:
    from psycopg2.extras import RealDictCursor
    q = "SELECT * FROM graded_plays WHERE sport=%s"
    params: List = [sport]
    if market is not None:
        q += " AND market=%s"
        params.append(market)
    if since_date is not None:
        q += " AND slate_date>=%s"
        params.append(since_date)
    q += " ORDER BY slate_date ASC, id ASC"
    with _pg_conn() as con, con.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(q, params)
        return [dict(r) for r in cur.fetchall()]


# ---- public API — identical signatures, dispatches to the active backend ---
def record_graded_slate(slate_date: str, sport: str, graded_plays: List[Dict],
                        db_path: Optional[str] = None, graded_at: Optional[str] = None) -> int:
    """Persist one day's worth of ALREADY-GRADED plays -- pass retro.grade_slate's own first
    return value (graded_plays) directly; each dict is expected to carry at least Market, Side,
    Line, ModelProb, Conviction, Player, PlayerId, Hit, Actual -- exactly grade_slate's own real
    output shape, no separate mapping required at the call site. Missing keys are stored as NULL
    rather than raising, so this stays safe to call even for a sport/market combination whose
    plays don't carry every field.

    Rank/OfTotal (ADDED DIRECTLY ON REQUEST, for retro.catch_rate_by_rank) are NOT part of grade_
    slate's own real output -- grade_slate only ever sees one market's worth of already-graded
    plays, and rank is inherently a cross-play, within-market comparison. The real caller is
    expected to merge retro.rank_within_market(plays)'s own output into each graded play's dict
    (as "Rank"/"OfTotal") BEFORE calling this -- see views/16_Retrospective.py's own real usage.
    Missing here too is fine, stored as NULL, same as every other optional field.

    Replaces (not appends to) any existing rows for this exact (slate_date, sport) -- see this
    module's own docstring for why per-day replacement, not per-row upsert, is the real
    idempotency unit here. Returns the number of rows written.

    db_path defaults to None, resolved to the module-level DB_PATH INSIDE this function body, not
    as an early-bound default parameter -- same deliberate reason line_history.record_snapshot's
    own docstring gives: a caller that monkeypatches this module's DB_PATH (every test in this
    file does exactly that) must still be honored even when db_path isn't passed explicitly."""
    db_path = db_path if db_path is not None else DB_PATH
    graded_at = graded_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    rows = []
    for p in graded_plays:
        hit = p.get("Hit")
        rows.append({
            "graded_at": graded_at, "slate_date": slate_date, "sport": sport,
            "market": p.get("Market"), "player": p.get("Player"), "player_id": p.get("PlayerId"),
            "side": p.get("Side"), "line": p.get("Line"), "model_prob": p.get("ModelProb"),
            "conviction": p.get("Conviction"),
            "hit": (1 if hit is True else 0 if hit is False else None),
            "actual_value": p.get("Actual"),
            "rank": p.get("Rank"), "of_total": p.get("OfTotal"),
        })

    if USING_POSTGRES:
        return _pg_replace_day(slate_date, sport, rows)
    return _sqlite_replace_day(db_path, slate_date, sport, rows)


def fetch_graded_plays(sport: str, market: Optional[str] = None, since_date: Optional[str] = None,
                       db_path: Optional[str] = None) -> List[Dict]:
    """Every persisted graded play for `sport`, oldest slate first -- optionally narrowed to one
    market and/or a start date (YYYY-MM-DD, inclusive). Returns rows shaped to match retro.py's
    own play-dict field names (Market, Side, Line, ModelProb, Conviction, Player, PlayerId, Hit,
    Actual) rather than this table's own column names, specifically so the result can be handed
    straight to retro._calibration or retro.player_calibration with no translation step -- real
    accumulated history exercised through the exact same, already-trusted grading logic, not a
    second calibration engine reinventing what "calibrated" means.

    hit comes back as True/False/None (not the stored 0/1/NULL) -- the same three-state contract
    grade_slate's own output already uses, so downstream code never has to know this passed
    through storage at all. Rank/OfTotal (ADDED DIRECTLY ON REQUEST, for retro.catch_rate_by_
    rank) come back as stored -- real ints when record_graded_slate was given real rank data,
    None otherwise (never guessed).

    Same dynamic db_path resolution as record_graded_slate, for the same reason."""
    db_path = db_path if db_path is not None else DB_PATH
    raw = (_pg_fetch(sport, market, since_date) if USING_POSTGRES
          else _sqlite_fetch(db_path, sport, market, since_date))

    out = []
    for r in raw:
        hit = r.get("hit")
        out.append({
            "Market": r.get("market"), "Side": r.get("side"), "Line": r.get("line"),
            "ModelProb": r.get("model_prob"), "Conviction": r.get("conviction"),
            "Player": r.get("player"), "PlayerId": r.get("player_id"),
            "Hit": (True if hit == 1 else False if hit == 0 else None),
            "Actual": r.get("actual_value"),
            "Rank": r.get("rank"), "OfTotal": r.get("of_total"),
            "_slate_date": r.get("slate_date"), "_graded_at": r.get("graded_at"),
        })
    return out
