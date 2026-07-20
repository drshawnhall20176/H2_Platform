"""
betlog.py — the proof layer's data store and analytics.
 
Records every bet, tracks Closing Line Value (CLV), settles results, and computes
calibration. This is what turns "I have a model" into "here's documented evidence it
beats the market."
 
STORAGE: SQLite at data/bets.db. Persists locally (where you'll log bets). On Streamlit
Community Cloud the filesystem is ephemeral, so for durable cloud storage swap the four
functions below the SCHEMA for a Postgres/Supabase backend — all SQL is isolated here,
so nothing else in the app changes.
 
CLV is the headline metric: did you get a better price than the line's CLOSE? It's the
best-known early predictor of long-term winning and shows up in weeks, not seasons.
"""
 
from __future__ import annotations
 
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, List, Optional
 
from odds_api import american_to_decimal
 
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "bets.db")
 
_SCHEMA = """
CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_placed  TEXT NOT NULL,
    slate_date TEXT,
    game       TEXT,
    player     TEXT,
    player_id  INTEGER,
    market     TEXT,
    side       TEXT,
    line       REAL,
    entry_odds INTEGER,
    model_prob REAL,
    stake      REAL,
    book       TEXT,
    close_odds INTEGER,
    result     TEXT,
    notes      TEXT,
    ticket     TEXT,
    sport      TEXT,
    trader     TEXT
);
"""
# player_id: added directly on request, for automated result settlement -- retro.py's existing,
# already-tested grade_play/get_player_results (the same machinery Retrospective/Media Room/
# Podcast Studio already use to grade the model's own picks against real results) matches by
# numeric player ID, not name, since name matching is genuinely fragile (accents, suffixes,
# nicknames, two players sharing a surname). A bet logged with only a text player name can't be
# reliably auto-matched to its real result; one logged with player_id can. Populated
# automatically by quick_log.py (every play it logs already carries PlayerId from build_best_
# bets), optional everywhere else (older bets, or ones logged manually via the Bet Log page
# itself, simply won't auto-settle until this is backfilled or entered by hand) -- same
# gradual-rollout posture as "trader" below, not a breaking requirement.
#
# trader: a real, deliberate first step toward future multi-user support, not multi-user support
# itself — there's no login system asking "who are you" yet (see sports.require_trading_access,
# a single shared password, not per-person identity), so nothing currently POPULATES this
# reliably. Added now specifically so a future real login system doesn't need a schema migration
# on top of everything else it'll need to build — the column already exists, even though nothing
# meaningfully fills it in yet. Optional on every call (add_bet/update_bet), same as every other
# field here.

_FIELDS = ["ts_placed", "slate_date", "game", "player", "player_id", "market", "side", "line",
           "entry_odds", "model_prob", "stake", "book", "close_odds", "result", "notes",
           "ticket", "sport", "trader"]
 
 
# ===========================================================================
# STORAGE — SQLite for local/dev, Postgres (Supabase) for durable cloud storage.
#
# Auto-selected: if a DATABASE_URL is configured (Streamlit secret or env var) we use
# Postgres, so bets survive reboots and redeploys. Otherwise SQLite at data/bets.db —
# which persists locally but is EPHEMERAL on Streamlit Cloud (wiped on every reboot).
# All SQL lives in this block; the public functions keep identical signatures, so no
# other file in the app changes regardless of which backend is active.
# ===========================================================================
def _database_url() -> Optional[str]:
    """Postgres/Supabase connection string, or None to use local SQLite. Checked in order:
    the DATABASE_URL environment variable, then a DATABASE_URL entry in Streamlit secrets."""
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
USING_POSTGRES = bool(_DATABASE_URL)        # True on the cloud once DATABASE_URL is set
 
 
# ---- SQLite backend (local development and the test suite) -----------------
@contextmanager
def _sqlite_conn(db_path: str = DB_PATH):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(_SCHEMA)
        cols = [r[1] for r in con.execute("PRAGMA table_info(bets)").fetchall()]
        if "ticket" not in cols:            # migrate DBs that predate the ticket column
            con.execute("ALTER TABLE bets ADD COLUMN ticket TEXT")
        if "sport" not in cols:             # migrate DBs that predate multi-sport
            con.execute("ALTER TABLE bets ADD COLUMN sport TEXT")
        if "trader" not in cols:            # migrate DBs that predate multi-user support
            con.execute("ALTER TABLE bets ADD COLUMN trader TEXT")
        if "player_id" not in cols:         # migrate DBs that predate automated result settlement
            con.execute("ALTER TABLE bets ADD COLUMN player_id INTEGER")
        yield con
        con.commit()
    finally:
        con.close()
 
 
def _sqlite_add_bet(db_path, fields) -> int:
    vals = [fields.get(c) for c in _FIELDS]
    with _sqlite_conn(db_path) as con:
        cur = con.execute(
            f"INSERT INTO bets ({','.join(_FIELDS)}) VALUES ({','.join('?' * len(_FIELDS))})", vals)
        return int(cur.lastrowid)
 
 
def _sqlite_list(db_path) -> List[Dict]:
    with _sqlite_conn(db_path) as con:
        return [dict(r) for r in con.execute("SELECT * FROM bets ORDER BY id DESC").fetchall()]
 
 
def _sqlite_update(bet_id, db_path, fields) -> None:
    sets = ", ".join(f"{k}=?" for k in fields)
    with _sqlite_conn(db_path) as con:
        con.execute(f"UPDATE bets SET {sets} WHERE id=?", [*fields.values(), bet_id])
 
 
def _sqlite_delete(bet_id, db_path) -> None:
    with _sqlite_conn(db_path) as con:
        con.execute("DELETE FROM bets WHERE id=?", [bet_id])
 
 
# ---- Postgres / Supabase backend (durable cloud storage) ------------------
# Same columns and semantics as SQLite; differences are dialect only: BIGSERIAL id,
# %s placeholders, RETURNING id for the new row, and RealDictCursor for dict rows.
_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS bets (
    id BIGSERIAL PRIMARY KEY,
    ts_placed  TEXT NOT NULL,
    slate_date TEXT, game TEXT, player TEXT, player_id INTEGER, market TEXT, side TEXT,
    line REAL, entry_odds INTEGER, model_prob REAL, stake REAL, book TEXT,
    close_odds INTEGER, result TEXT, notes TEXT, ticket TEXT, sport TEXT, trader TEXT
);
ALTER TABLE bets ADD COLUMN IF NOT EXISTS sport TEXT;
ALTER TABLE bets ADD COLUMN IF NOT EXISTS trader TEXT;
ALTER TABLE bets ADD COLUMN IF NOT EXISTS player_id INTEGER;
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
            cur.execute("ALTER TABLE bets ADD COLUMN IF NOT EXISTS ticket TEXT")
        con.commit()
        yield con
        con.commit()
    finally:
        con.close()
 
 
def _pg_add_bet(fields) -> int:
    vals = [fields.get(c) for c in _FIELDS]
    ph = ",".join(["%s"] * len(_FIELDS))
    with _pg_conn() as con, con.cursor() as cur:
        cur.execute(f"INSERT INTO bets ({','.join(_FIELDS)}) VALUES ({ph}) RETURNING id", vals)
        return int(cur.fetchone()[0])
 
 
def _pg_list() -> List[Dict]:
    from psycopg2.extras import RealDictCursor
    with _pg_conn() as con, con.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM bets ORDER BY id DESC")
        return [dict(r) for r in cur.fetchall()]
 
 
def _pg_update(bet_id, fields) -> None:
    sets = ", ".join(f"{k}=%s" for k in fields)
    with _pg_conn() as con, con.cursor() as cur:
        cur.execute(f"UPDATE bets SET {sets} WHERE id=%s", [*fields.values(), bet_id])
 
 
def _pg_delete(bet_id) -> None:
    with _pg_conn() as con, con.cursor() as cur:
        cur.execute("DELETE FROM bets WHERE id=%s", [bet_id])
 
 
# ---- public API — identical signatures, dispatches to the active backend ---
def add_bet(db_path: str = DB_PATH, **fields) -> int:
    fields.setdefault("ts_placed", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return _pg_add_bet(fields) if USING_POSTGRES else _sqlite_add_bet(db_path, fields)
 
 
def list_bets(db_path: str = DB_PATH, settled: Optional[bool] = None,
              sport: Optional[str] = None) -> List[Dict]:
    rows = _pg_list() if USING_POSTGRES else _sqlite_list(db_path)
    if sport is not None:
        # Match the sport; treat legacy rows with no sport recorded as MLB (the original sport).
        rows = [b for b in rows if (b.get("sport") or "MLB") == sport]
    if settled is True:
        rows = [b for b in rows if b.get("result")]
    elif settled is False:
        rows = [b for b in rows if not b.get("result")]
    return rows
 
 
def update_bet(bet_id: int, db_path: str = DB_PATH, **fields) -> None:
    fields = {k: v for k, v in fields.items() if k in _FIELDS}
    if not fields:
        return
    if USING_POSTGRES:
        _pg_update(bet_id, fields)
    else:
        _sqlite_update(bet_id, db_path, fields)
 
 
def delete_bet(bet_id: int, db_path: str = DB_PATH) -> None:
    if USING_POSTGRES:
        _pg_delete(bet_id)
    else:
        _sqlite_delete(bet_id, db_path)
 
 
# ===========================================================================
# ANALYTICS (pure functions over lists of bet dicts — fully testable offline)
# ===========================================================================
def clv_pct(entry_odds, close_odds) -> Optional[float]:
    """Closing Line Value as a percent: how much better your price was than the close.
 
    (decimal_entry / decimal_close − 1) × 100. Positive = you beat the close."""
    if entry_odds is None or close_odds is None:
        return None
    return round((american_to_decimal(entry_odds) / american_to_decimal(close_odds) - 1) * 100, 2)
 
 
def _result(bet) -> str:
    """Normalized result string, robust to None, NaN (which pandas produces for empty cells
    when a DataFrame row is passed in), and non-string types from either backend."""
    r = bet.get("result")
    if r is None or (isinstance(r, float) and r != r):      # None or NaN
        return ""
    return str(r).strip().lower()
 
 
def _ticket(bet) -> str:
    """Normalized ticket tag, NaN/None-safe (empty string means an untagged single)."""
    t = bet.get("ticket")
    if t is None or (isinstance(t, float) and t != t):
        return ""
    return str(t).strip()
 
 
def bet_pnl(bet: Dict) -> Optional[float]:
    """Profit for a settled bet. Win pays net odds × stake; loss = −stake; push/void = 0."""
    result = _result(bet)
    stake = bet.get("stake") or 0.0
    odds = bet.get("entry_odds")
    if result == "win" and odds is not None:
        return round(stake * (american_to_decimal(odds) - 1), 2)
    if result == "loss":
        return round(-stake, 2)
    if result in ("push", "void"):
        return 0.0
    return None  # unsettled
 
 
def summary(bets: List[Dict]) -> Dict:
    settled = [b for b in bets if _result(b) in ("win", "loss")]
    wins = sum(1 for b in settled if _result(b) == "win")
    losses = sum(1 for b in settled if _result(b) == "loss")
    staked = sum(b.get("stake") or 0.0 for b in settled)
    profit = sum(bet_pnl(b) or 0.0 for b in settled)
    roi = (profit / staked * 100) if staked > 0 else None
 
    clvs = [clv_pct(b.get("entry_odds"), b.get("close_odds")) for b in bets]
    clvs = [c for c in clvs if c is not None]
    avg_clv = (sum(clvs) / len(clvs)) if clvs else None
    beat = (sum(1 for c in clvs if c > 0) / len(clvs) * 100) if clvs else None
 
    return {
        "n": len(bets), "settled": len(settled), "wins": wins, "losses": losses,
        "open": len(bets) - len(settled),
        "staked": round(staked, 2), "profit": round(profit, 2),
        "roi": round(roi, 2) if roi is not None else None,
        "clv_n": len(clvs),
        "avg_clv": round(avg_clv, 2) if avg_clv is not None else None,
        "beat_close_rate": round(beat, 1) if beat is not None else None,
    }
 
 
def calibration(bets: List[Dict], n_bins: int = 5) -> List[Dict]:
    """Bucket settled bets by model probability and compare predicted vs actual hit rate.
 
    Returns non-empty buckets: {lo, hi, predicted (mean model prob), actual (win rate), n}.
    Well-calibrated -> predicted ≈ actual in every bucket."""
    settled = [b for b in bets
               if _result(b) in ("win", "loss") and b.get("model_prob") is not None]
    if not settled:
        return []
    width = 1.0 / n_bins
    out = []
    for i in range(n_bins):
        lo, hi = i * width, (i + 1) * width
        # include 1.0 in the top bucket
        grp = [b for b in settled if (lo <= b["model_prob"] < hi) or (i == n_bins - 1 and b["model_prob"] == 1.0)]
        if not grp:
            continue
        predicted = sum(b["model_prob"] for b in grp) / len(grp)
        actual = sum(1 for b in grp if _result(b) == "win") / len(grp)
        out.append({"lo": round(lo, 2), "hi": round(hi, 2),
                    "predicted": round(predicted, 3), "actual": round(actual, 3), "n": len(grp)})
    return out
 
 
# ===========================================================================
# PARLAYS — group legs by ticket; compare the parlay to the same money bet straight
# ===========================================================================
def market_breakdown(bets: List[Dict]) -> List[Dict]:
    """Per-market performance for the track-record page: sample, record, hit rate, and avg CLV.
    Avg CLV per market is the most honest 'where do we actually have an edge' signal — it's
    forward-looking and doesn't need the settled sample to be large. Sorted best CLV first."""
    from collections import defaultdict
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for b in bets:
        groups[b.get("market") or "Unknown"].append(b)
 
    out = []
    for market, rows in groups.items():
        settled = [b for b in rows if _result(b) in ("win", "loss")]
        wins = sum(1 for b in settled if _result(b) == "win")
        clvs = [clv_pct(b.get("entry_odds"), b.get("close_odds")) for b in rows]
        clvs = [c for c in clvs if c is not None]
        out.append({
            "market": market,
            "bets": len(rows),
            "settled": len(settled),
            "wins": wins,
            "losses": len(settled) - wins,
            "hit_rate": (wins / len(settled)) if settled else None,
            "avg_clv": (sum(clvs) / len(clvs)) if clvs else None,
            "clv_n": len(clvs),
        })
    out.sort(key=lambda r: (r["avg_clv"] is not None, r["avg_clv"] if r["avg_clv"] is not None else -1e9),
             reverse=True)
    return out
 
 
def clv_series(bets: List[Dict]) -> List[Dict]:
    """Chronological cumulative-average CLV — the equity-curve-style proof line. Only bets with
    a closing line count. Returns [{n, clv, cum_avg}] in the order the bets were placed."""
    rows = sorted([b for b in bets if clv_pct(b.get("entry_odds"), b.get("close_odds")) is not None],
                  key=lambda b: b.get("ts_placed") or "")
    series, run = [], 0.0
    for i, b in enumerate(rows, 1):
        c = clv_pct(b.get("entry_odds"), b.get("close_odds"))
        run += c
        series.append({"n": i, "clv": round(c, 2), "cum_avg": round(run / i, 2)})
    return series
 
 
def _dec_to_american(d: Optional[float]) -> Optional[int]:
    if not d or d <= 1:
        return None
    return int(round((d - 1) * 100)) if d >= 2 else int(round(-100 / (d - 1)))
 
 
def parlay_decimal(legs: List[Dict]) -> Optional[float]:
    """Combined decimal odds of a parlay = product of each leg's decimal odds."""
    d = 1.0
    for b in legs:
        if b.get("entry_odds") is None:
            return None
        d *= american_to_decimal(b["entry_odds"])
    return d
 
 
def parlay_status(legs: List[Dict]) -> str:
    """'win' only if every leg won; 'loss' if any leg lost; else 'pending'."""
    res = [_result(b) for b in legs]
    if any(r == "loss" for r in res):
        return "loss"
    if legs and all(r == "win" for r in res):
        return "win"
    return "pending"
 
 
def group_tickets(bets: List[Dict]) -> Dict[str, List[Dict]]:
    """Bucket bets by their ticket tag. Untagged bets (singles) are ignored here."""
    out: Dict[str, List[Dict]] = {}
    for b in bets:
        t = _ticket(b)
        if t:
            out.setdefault(t, []).append(b)
    return out
 
 
def compare_parlay_vs_singles(legs: List[Dict], parlay_stake: float) -> Optional[Dict]:
    """The teaching tool: parlay outcome vs the SAME total money bet as straight singles.
 
    Apples-to-apples on risk — parlay_stake on the ticket vs parlay_stake split evenly
    across the legs as singles. Returns P&L for each path and the difference."""
    n = len(legs)
    if n == 0 or not parlay_stake or parlay_stake <= 0:
        return None
 
    pdec = parlay_decimal(legs)
    status = parlay_status(legs)
    if status == "win" and pdec is not None:
        parlay_pnl = round(parlay_stake * (pdec - 1), 2)
    elif status == "loss":
        parlay_pnl = round(-parlay_stake, 2)
    else:
        parlay_pnl = None  # not fully settled yet
 
    per = parlay_stake / n
    singles_pnl, settled = 0.0, 0
    leg_detail = []
    for b in legs:
        pnl = bet_pnl({**b, "stake": per})
        leg_detail.append({"player": b.get("player"), "market": b.get("market"),
                           "side": b.get("side"), "line": b.get("line"),
                           "entry_odds": b.get("entry_odds"), "result": b.get("result"),
                           "pnl": pnl})
        if pnl is not None:
            singles_pnl += pnl
            settled += 1
    singles_total = round(singles_pnl, 2) if settled == n else None
 
    return {
        "n": n, "parlay_decimal": round(pdec, 2) if pdec else None,
        "parlay_american": _dec_to_american(pdec), "status": status,
        "parlay_stake": round(parlay_stake, 2), "per_leg_stake": round(per, 2),
        "parlay_pnl": parlay_pnl, "singles_pnl": singles_total,
        "difference": (round(singles_total - parlay_pnl, 2)
                       if (singles_total is not None and parlay_pnl is not None) else None),
        "legs": leg_detail,
    }
