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
             "lean", "gap", "flags", "kickoff", "ts", "source", "p_model", "p_market", "over_price", "under_price"]
# Nov 2: p_model / p_market (both P(over)) and both prices are stored so the weekly tuning report can fit how much
# the model should count against the books' line, per market (blend_weights).
_SNAP_ADDED = ("p_model", "p_market", "over_price", "under_price")
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
CREATE TABLE IF NOT EXISTS ufc_odds (
    id {pk},
    event_id TEXT, card_date TEXT, commence TEXT, payload TEXT, ts TEXT,
    UNIQUE (event_id)
);
CREATE TABLE IF NOT EXISTS game_picks (
    id {pk},
    sport TEXT, game_id TEXT, kickoff TEXT, payload TEXT, open_line REAL, close_line REAL,
    final_home REAL, final_away REAL, result TEXT, ts TEXT,
    UNIQUE (sport, game_id)
);
CREATE TABLE IF NOT EXISTS calibration (
    id {pk},
    sport TEXT, s REAL, details TEXT, approved_ts TEXT, active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS model_tuning (
    id {pk},
    sport TEXT, market TEXT, slot TEXT, factor REAL, reason TEXT, approved_ts TEXT, active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS results_archive (
    sport TEXT, rid TEXT, date TEXT, payload TEXT, ts TEXT,
    UNIQUE (sport, rid)
);
CREATE TABLE IF NOT EXISTS blob_cache (
    kind TEXT, k TEXT, payload TEXT, ts TEXT,
    UNIQUE (kind, k)
);
CREATE TABLE IF NOT EXISTS slate_snapshots (
    sport TEXT, date TEXT, ts TEXT, payload TEXT,
    UNIQUE (sport, date)
);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY, value TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS blend_weights (
    id {pk},
    sport TEXT, market TEXT, w REAL, details TEXT, approved_ts TEXT, active INTEGER DEFAULT 1
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
                for c in _SNAP_ADDED:
                    cur.execute(f"ALTER TABLE prop_snapshots ADD COLUMN IF NOT EXISTS {c} REAL")
            con.commit()
            yield con, "%s"
        return
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(_SNAP_SCHEMA.format(pk="INTEGER PRIMARY KEY AUTOINCREMENT"))
        have = {r[1] for r in con.execute("PRAGMA table_info(prop_snapshots)")}
        for c in _SNAP_ADDED:
            if c not in have:
                con.execute(f"ALTER TABLE prop_snapshots ADD COLUMN {c} REAL")
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
            "kickoff": kickoff, "ts": _now(), "source": source,
            "p_model": _f(row.get("p_model")), "p_market": _f(row.get("p_market")),
            "over_price": _f(row.get("over_price")), "under_price": _f(row.get("under_price"))}


def _f(x) -> Optional[float]:
    try:
        return None if x is None or x != x else float(x)
    except (TypeError, ValueError):
        return None


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
            if ph == "%s":                                      # Postgres: one round trip per 500 rows (Nov 4)
                from psycopg2.extras import execute_values
                keyed = {}
                for r in recs:                                  # one row per conflict key (last wins), as before
                    keyed[(r.get("sport"), r.get("slate_date"), r.get("game"), r.get("player"), r.get("market"))] = r
                execute_values(cur, sql.replace(f"VALUES ({marks})", "VALUES %s"),
                               [[r.get(c) for c in SNAP_COLS] for r in keyed.values()], page_size=500)
            else:
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


# --------------------------------------------------------------------------- UFC prices (ufc_review.py)
def save_ufc_odds(records: List[Dict], db_path: Optional[str] = None) -> int:
    """Upsert each bout's latest pre-fight prices (ufc_review.record_from_event) by event id."""
    recs = [r for r in records or [] if r and r.get("event_id")]
    if not recs or _test_run(db_path):
        return 0
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            for r in recs:
                cur.execute(
                    f"INSERT INTO ufc_odds (event_id, card_date, commence, payload, ts) VALUES ({ph},{ph},{ph},{ph},{ph}) "
                    f"ON CONFLICT (event_id) DO UPDATE SET card_date=excluded.card_date, commence=excluded.commence, "
                    f"payload=excluded.payload, ts=excluded.ts",
                    [r["event_id"], r.get("card_date"), r.get("commence"), json.dumps(r, default=str), _now()])
        return len(recs)
    except Exception:                                           # noqa: BLE001
        return 0


def load_ufc_odds(card_date: str, db_path: Optional[str] = None) -> List[Dict]:
    if db_path is None and not available():
        return []
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            cur.execute(f"SELECT payload FROM ufc_odds WHERE card_date={ph} ORDER BY commence", [card_date])
            out = []
            for r in cur.fetchall():
                try:
                    out.append(json.loads(r["payload"] if isinstance(r, (dict, sqlite3.Row)) else r[0]))
                except (TypeError, ValueError):
                    pass
            return out
    except Exception:                                           # noqa: BLE001
        return []


def ufc_card_dates(db_path: Optional[str] = None) -> List[str]:
    if db_path is None and not available():
        return []
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            cur.execute("SELECT DISTINCT card_date FROM ufc_odds WHERE card_date IS NOT NULL ORDER BY card_date")
            return [r["card_date"] if isinstance(r, (dict, sqlite3.Row)) else r[0] for r in cur.fetchall()]
    except Exception:                                           # noqa: BLE001
        return []


# --------------------------------------------------------------------------- game picks (game_picks.py)
def save_game_picks(records: List[Dict], db_path: Optional[str] = None) -> int:
    """Upsert pre-kickoff game projections: the first capture keeps its line as the OPEN; every later one (before
    kickoff) becomes the CLOSE and refreshes the projection and pick. Graded games are never touched."""
    recs = [r for r in records or [] if r and r.get("game_id")]
    if not recs or _test_run(db_path):
        return 0
    n = 0
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            for r in recs:
                cur.execute(f"SELECT payload, open_line, result FROM game_picks WHERE sport={ph} AND game_id={ph}",
                            [r["sport"], r["game_id"]])
                row = cur.fetchone()
                if row is None:
                    rec = dict(r, open_line=r["line"], open_total=r.get("line_total"), open_ts=_now(),
                               close_line=r["line"], close_total=r.get("line_total"), close_edge=r["edge"])
                    cur.execute(f"INSERT INTO game_picks (sport, game_id, kickoff, payload, open_line, close_line, ts) "
                                f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
                                [r["sport"], r["game_id"], r["kickoff"], json.dumps(rec, default=str), r["line"],
                                 r["line"], _now()])
                else:
                    payload = row["payload"] if isinstance(row, (dict, sqlite3.Row)) else row[0]
                    graded = row["result"] if isinstance(row, (dict, sqlite3.Row)) else row[2]
                    if graded:
                        continue
                    old = json.loads(payload or "{}")
                    rec = dict(old, **r)
                    rec.update(open_line=old.get("open_line", r["line"]), open_total=old.get("open_total"),
                               open_ts=old.get("open_ts"), close_line=r["line"], close_total=r.get("line_total"),
                               close_edge=r["edge"], close_ts=_now())
                    cur.execute(f"UPDATE game_picks SET payload={ph}, close_line={ph}, kickoff={ph}, ts={ph} "
                                f"WHERE sport={ph} AND game_id={ph}",
                                [json.dumps(rec, default=str), r["line"], r["kickoff"], _now(), r["sport"], r["game_id"]])
                n += 1
        return n
    except Exception:                                           # noqa: BLE001
        return 0


def load_game_picks(sport: str, ungraded: bool = False, db_path: Optional[str] = None) -> List[Dict]:
    if db_path is None and not available():
        return []
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            cur.execute(f"SELECT * FROM game_picks WHERE sport={ph}" + (" AND result IS NULL AND final_home IS NULL"
                                                                         if ungraded else "") + " ORDER BY kickoff",
                        [sport])
            out = []
            for r in _rows(cur):
                p = json.loads(r.get("payload") or "{}")
                p.update(final_home=r.get("final_home"), final_away=r.get("final_away"), result=r.get("result"))
                out.append(p)
            return out
    except Exception:                                           # noqa: BLE001
        return []


def grade_game_pick(sport: str, game_id: str, home_pts: float, away_pts: float, result: Optional[str],
                    db_path: Optional[str] = None) -> bool:
    if _test_run(db_path):
        return False
    try:
        with _conn(db_path) as (con, ph):
            con.cursor().execute(f"UPDATE game_picks SET final_home={ph}, final_away={ph}, result={ph}, ts={ph} "
                                 f"WHERE sport={ph} AND game_id={ph}",
                                 [float(home_pts), float(away_pts), result, _now(), sport, str(game_id)])
        return True
    except Exception:                                           # noqa: BLE001
        return False


# --------------------------------------------------------------------------- calibration (calibration.py)
def approve_calibration(sport: str, s: float, details: Optional[Dict] = None, db_path: Optional[str] = None) -> bool:
    """Turn on an honest-chance factor for a sport (replacing the active one)."""
    if _test_run(db_path):
        return False
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            cur.execute(f"UPDATE calibration SET active=0 WHERE sport={ph}", [sport])
            cur.execute(f"INSERT INTO calibration (sport, s, details, approved_ts, active) VALUES ({ph},{ph},{ph},{ph},1)",
                        [sport, float(s), json.dumps(details or {}, default=str), _now()])
        import calibration as CAL
        CAL.clear_cache()
        return True
    except Exception:                                           # noqa: BLE001
        return False


def list_calibration(active_only: bool = True, db_path: Optional[str] = None) -> List[Dict]:
    if db_path is None and not available():
        return []
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            cur.execute("SELECT * FROM calibration" + (" WHERE active=1" if active_only else "") + " ORDER BY id")
            return _rows(cur)
    except Exception:                                           # noqa: BLE001
        return []


def retire_calibration(cal_id: int, db_path: Optional[str] = None) -> bool:
    try:
        with _conn(db_path) as (con, ph):
            con.cursor().execute(f"UPDATE calibration SET active=0 WHERE id={ph}", [cal_id])
        import calibration as CAL
        CAL.clear_cache()
        return True
    except Exception:                                           # noqa: BLE001
        return False


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


# --------------------------------------------------------------------------- blend weights (Nov 2)
# How much the model counts against the books' no-vig line, per sport + market, fitted by the weekly tuning report
# and turned on only by the owner. props_engine.MODEL_WEIGHT is the default where none is approved.
def approve_blend(sport: str, market: str, w: float, details: Optional[Dict] = None, db_path: Optional[str] = None) -> bool:
    if _test_run(db_path):
        return False
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            cur.execute(f"UPDATE blend_weights SET active=0 WHERE sport={ph} AND market={ph}", [sport, market])
            cur.execute(f"INSERT INTO blend_weights (sport, market, w, details, approved_ts, active) "
                        f"VALUES ({ph},{ph},{ph},{ph},{ph},1)", [sport, market, float(w), json.dumps(details or {}), _now()])
        import blend_weights as BW
        BW.clear_cache()
        return True
    except Exception:                                           # noqa: BLE001
        return False


def list_blend(active_only: bool = True, db_path: Optional[str] = None) -> List[Dict]:
    if db_path is None and not available():
        return []
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            cur.execute("SELECT * FROM blend_weights" + (" WHERE active=1" if active_only else "") + " ORDER BY id")
            return _rows(cur)
    except Exception:                                           # noqa: BLE001
        return []


def retire_blend(blend_id: int, db_path: Optional[str] = None) -> bool:
    try:
        with _conn(db_path) as (con, ph):
            con.cursor().execute(f"UPDATE blend_weights SET active=0 WHERE id={ph}", [blend_id])
        import blend_weights as BW
        BW.clear_cache()
        return True
    except Exception:                                           # noqa: BLE001
        return False


# --------------------------------------------------------------------------- owner settings (Nov 3)
def get_setting(key: str, default=None, db_path: Optional[str] = None):
    """A saved JSON value (e.g. the Progression Plan's bankroll settings), or `default`."""
    if db_path is None and not available():
        return default
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            cur.execute(f"SELECT value FROM app_settings WHERE key={ph}", [key])
            row = cur.fetchone()
        return default if not row else json.loads(row[0])
    except Exception:                                           # noqa: BLE001
        return default


def save_setting(key: str, value, db_path: Optional[str] = None) -> bool:
    if _test_run(db_path):
        return False
    try:
        with _conn(db_path) as (con, ph):
            con.cursor().execute(
                f"INSERT INTO app_settings (key, value, ts) VALUES ({ph},{ph},{ph}) "
                f"ON CONFLICT (key) DO UPDATE SET value=excluded.value, ts=excluded.ts",
                [key, json.dumps(value, default=str), _now()])
        return True
    except Exception:                                           # noqa: BLE001
        return False


# --------------------------------------------------------------------------- built slates (Nov 4)
# A sport's built slate (every rostered player's recent games: hundreds of ESPN requests) saved once, so a restarted app
# or another page loads it in one read instead of rebuilding it. slate_store.py decides when a saved one is fresh.
def save_slate(sport: str, date: str, payload: str, db_path: Optional[str] = None) -> bool:
    if _test_run(db_path):
        return False
    try:
        with _conn(db_path) as (con, ph):
            con.cursor().execute(
                f"INSERT INTO slate_snapshots (sport, date, ts, payload) VALUES ({ph},{ph},{ph},{ph}) "
                f"ON CONFLICT (sport, date) DO UPDATE SET ts=excluded.ts, payload=excluded.payload",
                [sport, date, _now(), payload])
        return True
    except Exception:                                           # noqa: BLE001
        return False


def load_slate(sport: str, date: str, db_path: Optional[str] = None) -> Optional[Dict]:
    """{"ts", "payload"} or None."""
    if db_path is None and not available():
        return None
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            cur.execute(f"SELECT ts, payload FROM slate_snapshots WHERE sport={ph} AND date={ph}", [sport, date])
            row = cur.fetchone()
        return None if not row else {"ts": row[0], "payload": row[1]}
    except Exception:                                           # noqa: BLE001
        return None


# --------------------------------------------------------------------------- finished-game data (Nov 4)
# Things that never change once a game is over (a box score's player lines), kept so a restarted app reads them in
# one query instead of re-fetching hundreds of games from ESPN.
def load_blobs(kind: str, keys: List[str], db_path: Optional[str] = None) -> Dict[str, str]:
    keys = [str(k) for k in keys or []]
    if not keys or (db_path is None and not available()):
        return {}
    out: Dict[str, str] = {}
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            for i in range(0, len(keys), 500):
                part = keys[i:i + 500]
                cur.execute(f"SELECT k, payload FROM blob_cache WHERE kind={ph} AND k IN ({','.join([ph] * len(part))})",
                            [kind] + part)
                out.update({str(r[0]): r[1] for r in cur.fetchall()})
    except Exception:                                           # noqa: BLE001
        return out
    return out


def save_blobs(kind: str, items: Dict[str, str], db_path: Optional[str] = None) -> int:
    if not items or _test_run(db_path):
        return 0
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            ts = _now()
            for k, v in items.items():
                cur.execute(f"INSERT INTO blob_cache (kind, k, payload, ts) VALUES ({ph},{ph},{ph},{ph}) "
                            f"ON CONFLICT (kind, k) DO UPDATE SET payload=excluded.payload, ts=excluded.ts",
                            [kind, str(k), v, ts])
        return len(items)
    except Exception:                                           # noqa: BLE001
        return 0


# --------------------------------------------------------------------------- results archive (Nov 3)
# Completed tennis matches and international basketball games, kept so the models refit daily without re-crawling.
def save_results(sport: str, rows: List[Dict], db_path: Optional[str] = None) -> int:
    rows = [r for r in rows or [] if r and r.get("id")]
    if not rows or _test_run(db_path):
        return 0
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            sql = (f"INSERT INTO results_archive (sport, rid, date, payload, ts) VALUES ({ph},{ph},{ph},{ph},{ph}) "
                   f"ON CONFLICT (sport, rid) DO UPDATE SET date=excluded.date, payload=excluded.payload, ts=excluded.ts")
            now = _now()
            vals = [(sport, str(r["id"]), str(r.get("date") or ""), json.dumps(r, default=str), now) for r in rows]
            if ph == "%s":                                      # Postgres: one round trip per 500 rows, not per row
                from psycopg2.extras import execute_values
                execute_values(cur, "INSERT INTO results_archive (sport, rid, date, payload, ts) VALUES %s "
                                    "ON CONFLICT (sport, rid) DO UPDATE SET date=excluded.date, payload=excluded.payload, "
                                    "ts=excluded.ts", vals, page_size=500)
            else:
                cur.executemany(sql, vals)
        return len(rows)
    except Exception:                                           # noqa: BLE001
        return 0


def load_results(sport: str, since: Optional[str] = None, db_path: Optional[str] = None) -> List[Dict]:
    if db_path is None and not available():
        return []
    try:
        with _conn(db_path) as (con, ph):
            cur = con.cursor()
            if since:
                cur.execute(f"SELECT payload FROM results_archive WHERE sport={ph} AND date>={ph} ORDER BY date",
                            [sport, since])
            else:
                cur.execute(f"SELECT payload FROM results_archive WHERE sport={ph} ORDER BY date", [sport])
            return [json.loads(r["payload"] if isinstance(r, (dict, sqlite3.Row)) else r[0]) for r in cur.fetchall()]
    except Exception:                                           # noqa: BLE001
        return []
