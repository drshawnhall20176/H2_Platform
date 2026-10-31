"""
model_store.py — what the model said at kickoff, and the adjustments the owner approved (Oct 30).

Two tables, in the same database as the Bet Log (Postgres when DATABASE_URL is set, else SQLite at data/model.db):

  prop_snapshots  every priced props row the platform showed before a game started -- projection, the volume behind
                  it, the line, the side, the chance, cushion, Use tag, price, flags. One row per (sport, date, game,
                  player, market); later views before kickoff overwrite earlier ones, so the snapshot is the LAST read
                  before the game. The Postgame Review grades these against the box score.
  model_tuning    adjustments approved on the Postgame Review page: a multiplier on one market's projections
                  (optionally one slot) for one sport. The props models read them through model_tuning.factor.

Every function fails soft: a database that can't be reached never breaks a page.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "model.db")

SNAP_COLS = ["sport", "slate_date", "game", "team", "opp", "player", "player_id", "market", "slot", "grp",
             "projection", "proj_opp", "line", "side", "chance", "cushion", "use_tag", "price", "book", "ev",
             "lean", "gap", "flags", "kickoff", "ts", "source"]
_SNAP_SCHEMA = """
CREATE TABLE IF NOT EXISTS prop_snapshots (
    id {pk},
    sport TEXT, slate_date TEXT, game TEXT, team TEXT, opp TEXT, player TEXT, player_id TEXT, market TEXT,
    slot TEXT, grp TEXT, projection REAL, proj_opp REAL, line REAL, side TEXT, chance REAL, cushion REAL,
    use_tag TEXT, price REAL, book TEXT, ev REAL, lean TEXT, gap TEXT, flags TEXT, kickoff TEXT, ts TEXT,
    source TEXT,
    UNIQUE (sport, slate_date, game, player, market)
);
CREATE TABLE IF NOT EXISTS odds_archive (
    id {pk},
    sport TEXT, slate_date TEXT, home TEXT, away TEXT, markets TEXT, payload TEXT, kickoff TEXT, ts TEXT,
    UNIQUE (sport, slate_date, home, away, markets)
);
CREATE TABLE IF NOT EXISTS daily_reviews (
    id {pk},
    sport TEXT, morning TEXT, report TEXT, ts TEXT,
    UNIQUE (sport, morning)
);
CREATE TABLE IF NOT EXISTS model_tuning (
    id {pk},
    sport TEXT, market TEXT, slot TEXT, factor REAL, reason TEXT, approved_ts TEXT, active INTEGER DEFAULT 1
);
"""
SAVE_EVERY_S = 600            # the same game + market is re-saved at most every 10 minutes per process
_last_save: Dict = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pg() -> bool:
    try:
        import betlog as B
        return bool(B.USING_POSTGRES)
    except Exception:                                           # noqa: BLE001
        return False


def available() -> bool:
    """Is there a store to read (Postgres configured, or the local SQLite file exists)?"""
    if "PYTEST_CURRENT_TEST" in os.environ:
        return False
    return _pg() or os.path.exists(DB_PATH)


@contextmanager
def _conn(db_path: Optional[str] = None):
    db_path = db_path or DB_PATH
    """(connection, placeholder). Postgres through the Bet Log's connection; SQLite otherwise."""
    if _pg() and db_path == DB_PATH:
        import betlog as B
        with B._pg_conn() as con:
            with con.cursor() as cur:
                cur.execute(_SNAP_SCHEMA.format(pk="SERIAL PRIMARY KEY"))
            con.commit()
            yield con, "%s"
        return
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(_SNAP_SCHEMA.format(pk="INTEGER PRIMARY KEY AUTOINCREMENT"))
        yield con, "?"
        con.commit()
    finally:
        con.close()


def _rows(cur) -> List[Dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# --------------------------------------------------------------------------- snapshots
def snapshot_record(sport: str, slate_date: str, game: str, row: Dict, market: str, team=None, opp=None,
                    kickoff: Optional[str] = None, source: str = "") -> Optional[Dict]:
    """A props row -> a snapshot record, or None when it has nothing to grade (no line, no projection, ruled out)."""
    import props_engine as PE
    proj, line = row.get("projection"), row.get("line")
    if proj is None or line is None or row.get("out"):
        return None
    side = row.get("side")
    if side not in ("Over", "Under", "Yes"):
        side = "Over" if proj > PE.threshold(line) else "Under"
    if side == "Yes":
        side = "Over"
    pf = row.get("p_final")
    chance = None if pf is None else (pf if side == "Over" else 1 - pf)
    try:
        tag, _why = PE.use_tag(row, side, line, chance)
    except Exception:                                           # noqa: BLE001
        tag = None
    price = row.get("over_price") if side == "Over" else row.get("under_price")
    book = (row.get("book") or {}).get("book") if isinstance(row.get("book"), dict) else row.get("book")
    return {"sport": sport, "slate_date": slate_date, "game": game, "team": str(team if team is not None else
                                                                               row.get("team_name") or ""),
            "opp": str(opp if opp is not None else row.get("opp_name") or ""), "player": row.get("player"),
            "player_id": None if row.get("pid") is None else str(row.get("pid")), "market": market,
            "slot": row.get("slot"), "grp": row.get("group") or "", "projection": float(proj),
            "proj_opp": None if row.get("opp") is None else float(row["opp"]), "line": float(line), "side": side,
            "chance": chance, "cushion": PE.cushion(proj, line, side), "use_tag": tag,
            "price": price, "book": book, "ev": row.get("ev") if side == row.get("side") else None,
            "lean": row.get("lean"), "gap": row.get("gap"), "flags": json.dumps(row.get("flags") or []),
            "kickoff": kickoff, "ts": _now(), "source": source}


def started(kickoff: Optional[str]) -> bool:
    """Has the game started (a snapshot taken now would see in-game lines)?"""
    if not kickoff:
        return False
    try:
        k = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
        if k.tzinfo is None:
            k = k.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= k
    except ValueError:
        return False


def _test_run(db_path: Optional[str]) -> bool:
    """The test suite never writes the real store (tests pass their own db_path)."""
    return (db_path or DB_PATH) == DB_PATH and db_path is None and "PYTEST_CURRENT_TEST" in os.environ


def save(records: Iterable[Optional[Dict]], db_path: Optional[str] = None, throttle_key=None) -> int:
    """Upsert snapshot records (the last pre-kickoff view wins). Returns how many were written; 0 on any failure."""
    if _test_run(db_path):
        return 0
    recs = [r for r in records if r and not started(r.get("kickoff"))]
    if not recs:
        return 0
    if throttle_key is not None:
        last = _last_save.get(throttle_key)
        if last is not None and time.time() - last < SAVE_EVERY_S:
            return 0
    try:
        with _conn(db_path) as (con, ph):
            cols = ",".join(SNAP_COLS)
            marks = ",".join([ph] * len(SNAP_COLS))
            upd = ",".join(f"{c}=excluded.{c}" for c in SNAP_COLS if c not in ("sport", "slate_date", "game", "player",
                                                                              "market"))
            sql = (f"INSERT INTO prop_snapshots ({cols}) VALUES ({marks}) ON CONFLICT (sport, slate_date, game, player, "
                   f"market) DO UPDATE SET {upd}")
            cur = con.cursor()
            for r in recs:
                cur.execute(sql, [r.get(c) for c in SNAP_COLS])
        if throttle_key is not None:
            _last_save[throttle_key] = time.time()
        return len(recs)
    except Exception:                                           # noqa: BLE001
        return 0


def save_rows(sport: str, slate_date: str, game: str, rows: Iterable[Dict], market: str, team=None, opp=None,
              kickoff: Optional[str] = None, source: str = "", db_path: Optional[str] = None) -> int:
    recs = [snapshot_record(sport, slate_date, game, r, market, team, opp, kickoff, source) for r in rows or []]
    return save(recs, db_path, throttle_key=(sport, slate_date, game, market, str(team), source))


def save_reads(sport: str, slate_date: str, reads: Dict, kickoffs: Optional[Dict] = None, db_path: Optional[str] = None) -> int:
    """The pick pages' reads ({(pid, market key): row}, slate_props) -> snapshots, at most every 10 minutes."""
    key = (sport, slate_date, "reads")
    last = _last_save.get(key)
    if last is not None and time.time() - last < SAVE_EVERY_S:
        return 0
    kickoffs = kickoffs or {}
    recs = []
    for row in (reads or {}).values():
        recs.append(snapshot_record(sport, slate_date, row.get("game") or "", row, row.get("market") or "",
                                    row.get("team_id"), row.get("opp_id"),
                                    kickoffs.get(row.get("game")) or row.get("game_date"), "slate"))
    n = save(recs, db_path)
    _last_save[key] = time.time()
    return n


def load_snapshots(sport: Optional[str] = None, dates: Optional[List[str]] = None, db_path: Optional[str] = None) -> List[Dict]:
    if db_path is None and not available():
        return []
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            where, args = [], []
            if sport:
                where.append(f"sport={ph}")
                args.append(sport)
            if dates:
                where.append("slate_date IN (" + ",".join([ph] * len(dates)) + ")")
                args += list(dates)
            cur.execute("SELECT * FROM prop_snapshots" + (" WHERE " + " AND ".join(where) if where else "")
                        + " ORDER BY slate_date DESC, game, player, market", args)
            return _rows(cur)
    except Exception:                                           # noqa: BLE001
        return []


def snapshot_dates(sport: str, db_path: Optional[str] = None) -> List[str]:
    if db_path is None and not available():
        return []
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            cur.execute(f"SELECT DISTINCT slate_date FROM prop_snapshots WHERE sport={ph} ORDER BY slate_date DESC",
                        [sport])
            return [r[0] if not isinstance(r, dict) else r["slate_date"] for r in cur.fetchall()]
    except Exception:                                           # noqa: BLE001
        return []


# --------------------------------------------------------------------------- odds archive
# Oct 31: the books' feed drops a game once it's played, so a past date used to come back with no lines at all.
# Every successful pre-kickoff fetch is kept here (the latest pre-kickoff one wins), so an analyst opening an old
# date sees the lines the board had -- and it costs no Odds API credits to look back.
def _odds_key(markets) -> str:
    return ",".join(sorted(m for m in (markets or ()) if m))


def save_odds(sport: str, slate_date: str, home: str, away: str, markets, got: Optional[Dict],
              kickoff: Optional[str] = None, db_path: Optional[str] = None) -> bool:
    """Keep one fetch_game result ({"offers", "lines", ...}). Skips empty/error results and in-game fetches."""
    if _test_run(db_path) or not got or got.get("error") or not (got.get("offers") or got.get("lines")):
        return False
    if started(kickoff):
        return False
    payload = json.dumps({"offers": got.get("offers") or [], "lines": got.get("lines") or {}}, default=str)
    try:
        with _conn(db_path) as (con, ph):
            con.cursor().execute(
                f"INSERT INTO odds_archive (sport, slate_date, home, away, markets, payload, kickoff, ts) "
                f"VALUES ({','.join([ph] * 8)}) ON CONFLICT (sport, slate_date, home, away, markets) DO UPDATE SET "
                f"payload=excluded.payload, kickoff=excluded.kickoff, ts=excluded.ts",
                [sport, slate_date, str(home), str(away), _odds_key(markets), payload, kickoff, _now()])
        return True
    except Exception:                                           # noqa: BLE001
        return False


def load_odds(sport: str, slate_date: str, home: str, away: str, markets,
              db_path: Optional[str] = None) -> Optional[Dict]:
    """The archived {"offers", "lines", "archived_ts", "error": None} for this game + markets, or None."""
    if db_path is None and not available():
        return None
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            cur.execute(f"SELECT payload, ts FROM odds_archive WHERE sport={ph} AND slate_date={ph} AND home={ph} "
                        f"AND away={ph} AND markets={ph}", [sport, slate_date, str(home), str(away), _odds_key(markets)])
            row = cur.fetchone()
    except Exception:                                           # noqa: BLE001
        return None
    if not row:
        return None
    payload, ts = (row["payload"], row["ts"]) if isinstance(row, (dict, sqlite3.Row)) else (row[0], row[1])
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return None
    return {"offers": data.get("offers") or [], "lines": data.get("lines") or {}, "error": None, "archived_ts": ts}


# --------------------------------------------------------------------------- morning reports (daily_review.py)
def save_daily_review(sport: str, morning: str, report: Dict, db_path: Optional[str] = None) -> bool:
    """Keep one sport's 3:30 AM report (re-running a morning replaces it)."""
    if _test_run(db_path):
        return False
    try:
        with _conn(db_path) as (con, ph):
            con.cursor().execute(
                f"INSERT INTO daily_reviews (sport, morning, report, ts) VALUES ({ph},{ph},{ph},{ph}) "
                f"ON CONFLICT (sport, morning) DO UPDATE SET report=excluded.report, ts=excluded.ts",
                [sport, morning, json.dumps(report, default=str), _now()])
        return True
    except Exception:                                           # noqa: BLE001
        return False


def load_daily_review(sport: str, morning: str, db_path: Optional[str] = None) -> Optional[Dict]:
    if db_path is None and not available():
        return None
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            cur.execute(f"SELECT report FROM daily_reviews WHERE sport={ph} AND morning={ph}", [sport, morning])
            row = cur.fetchone()
    except Exception:                                           # noqa: BLE001
        return None
    if not row:
        return None
    try:
        return json.loads(row["report"] if isinstance(row, (dict, sqlite3.Row)) else row[0])
    except (TypeError, ValueError):
        return None


def daily_review_mornings(sport: str, db_path: Optional[str] = None) -> List[str]:
    if db_path is None and not available():
        return []
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            cur.execute(f"SELECT morning FROM daily_reviews WHERE sport={ph} ORDER BY morning DESC", [sport])
            return [r["morning"] if isinstance(r, (dict, sqlite3.Row)) else r[0] for r in cur.fetchall()]
    except Exception:                                           # noqa: BLE001
        return []


# --------------------------------------------------------------------------- tuning (approved adjustments)
def list_tuning(active_only: bool = True, db_path: Optional[str] = None) -> List[Dict]:
    if db_path is None and not available():
        return []
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            cur.execute("SELECT * FROM model_tuning" + (" WHERE active=1" if active_only else "") + " ORDER BY id")
            return _rows(cur)
    except Exception:                                           # noqa: BLE001
        return []


def approve_tuning(sport: str, market: str, factor: float, reason: str, slot: str = "", db_path: Optional[str] = None) -> bool:
    """Turn on a multiplier (replacing any active one for the same sport / market / slot)."""
    if _test_run(db_path):
        return False
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            cur.execute(f"UPDATE model_tuning SET active=0 WHERE sport={ph} AND market={ph} AND slot={ph}",
                        [sport, market, slot or ""])
            cur.execute(f"INSERT INTO model_tuning (sport, market, slot, factor, reason, approved_ts, active) "
                        f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},1)",
                        [sport, market, slot or "", float(factor), reason, _now()])
        import model_tuning as MT
        MT.clear_cache()
        return True
    except Exception:                                           # noqa: BLE001
        return False


def retire_tuning(tuning_id: int, db_path: Optional[str] = None) -> bool:
    try:
        with _conn(db_path) as (con, ph):
            con.cursor().execute(f"UPDATE model_tuning SET active=0 WHERE id={ph}", [tuning_id])
        import model_tuning as MT
        MT.clear_cache()
        return True
    except Exception:                                           # noqa: BLE001
        return False
