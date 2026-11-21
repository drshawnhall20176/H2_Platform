"""
backup.py — a nightly copy of the records (Nov 21).

Owner, Nov 21: yes to a nightly backup -- the pick records, rules state and grades live in one database, and one bad
write shouldn't be able to wipe the proof. Every night (backup workflow) this dumps, as gzipped JSON:

  * whole tables: bets (the Bet Log), app_settings (the shown-picks ledgers, rule fits, shut-off, health, settings),
    daily_reviews, game_picks, calibration, model_tuning, blend_weights;
  * prop_snapshots for the last SNAP_DAYS slates only (the older ones are in earlier nights' copies).

The workflow keeps each night's file for 90 days as a downloadable run artifact. `python backup.py OUTDIR` writes
OUTDIR/h2-backup-YYYY-MM-DD.json.gz and prints the row counts; `python backup.py --restore FILE TABLE [--apply]`
shows (or, with --apply, writes back) one table's rows from a copy -- rows are upserted, never deleted.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

TABLES = ("bets", "app_settings", "daily_reviews", "game_picks", "calibration", "model_tuning", "blend_weights")
SNAP_DAYS = 3
KEYS = {"app_settings": ["key"], "bets": ["id"]}


def _rows(cur, sql: str, args=()) -> List[Dict]:
    cur.execute(sql, list(args))
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def dump(today: Optional[str] = None) -> Dict:
    import model_store as MS
    import props_engine as PE
    today = today or PE._et_today()
    since = (date.fromisoformat(today) - timedelta(days=SNAP_DAYS)).isoformat()
    out: Dict = {"made": datetime.now(timezone.utc).isoformat(timespec="seconds"), "day": today, "tables": {}}
    with MS._conn() as (con, ph):
        cur = con.cursor()
        for t in TABLES:
            try:
                out["tables"][t] = _rows(cur, f"SELECT * FROM {t}")
            except Exception as exc:                            # noqa: BLE001 -- a missing table never stops the rest
                out["tables"][t] = {"error": f"{type(exc).__name__}: {exc}"}
                try:
                    con.rollback()
                except Exception:                               # noqa: BLE001
                    pass
        try:
            out["tables"]["prop_snapshots"] = _rows(cur, f"SELECT * FROM prop_snapshots WHERE slate_date >= {ph}",
                                                    [since])
        except Exception as exc:                                # noqa: BLE001
            out["tables"]["prop_snapshots"] = {"error": f"{type(exc).__name__}: {exc}"}
    return out


def write(outdir: str, today: Optional[str] = None) -> str:
    rec = dump(today)
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"h2-backup-{rec['day']}.json.gz")
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(rec, f, default=str)
    for t, rows in rec["tables"].items():
        print(f"{t}: {len(rows) if isinstance(rows, list) else rows}")
    print(f"wrote {path} ({os.path.getsize(path) / 1e6:.1f} MB)")
    return path


def read(path: str) -> Dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def restore(path: str, table: str, apply: bool = False) -> int:
    """Upserts one table's rows from a copy (never deletes). Without apply: only counts them."""
    import model_store as MS
    rows = read(path)["tables"].get(table)
    if not isinstance(rows, list):
        print(f"{table}: not in this copy ({rows})")
        return 0
    print(f"{table}: {len(rows)} rows in the copy" + ("" if apply else " (dry run: add --apply to write them)"))
    if not apply or not rows:
        return len(rows)
    keys = KEYS.get(table)
    if not keys:
        print(f"{table}: no restore key defined -- restore it by hand")
        return 0
    cols = list(rows[0].keys())
    with MS._conn() as (con, ph):
        cur = con.cursor()
        upd = ",".join(f"{c}=excluded.{c}" for c in cols if c not in keys)
        sql = (f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join([ph] * len(cols))}) "
               f"ON CONFLICT ({','.join(keys)}) DO UPDATE SET {upd}")
        for r in rows:
            cur.execute(sql, [r.get(c) for c in cols])
    print(f"{table}: {len(rows)} rows written")
    return len(rows)


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--restore":
        restore(argv[1], argv[2], apply="--apply" in argv)
        return 0
    write(argv[0] if argv else "backups")
    return 0


if __name__ == "__main__":
    sys.exit(main())
