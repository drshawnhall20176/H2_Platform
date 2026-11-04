"""
settle_analyst.py — grade the Analyst Record on a schedule (Nov 4). Run by the settle-analyst workflow.

Calls were only graded when someone opened the Analyst Desk for that sport, so sports nobody opened stopped grading
(Nov 4: 1,158 calls open -- NFL Nov 1, NBA Oct 20, NHL Oct 31, MLB, NCAAF). This grades every open earlier day for
every sport the record has, with the same settle_open_days the page uses (newest first; a day whose results aren't
published yet waits).

    python settle_analyst.py [--max-days 20]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

import pytz


def main(argv=None) -> int:
    import analyst_ledger as AL
    import sports
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-days", type=int, default=20)
    a = ap.parse_args(argv)
    today = datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
    rows = AL.fetch_calls()
    total = 0
    for sport in sorted({r["sport"] for r in rows}):
        open_days = sorted({r["date"] for r in rows if r["sport"] == sport and not r.get("settled_at") and r["date"] < today})
        if not open_days:
            print(f"{sport}: nothing open")
            continue
        try:
            eng = sports.get(sport).engine
            res = AL.settle_open_days(sport, open_days, eng.get_player_results, max_days=a.max_days,
                                      max_tries=a.max_days + 10)
        except Exception as exc:                                # noqa: BLE001 -- one sport never stops the rest
            print(f"{sport}: failed ({type(exc).__name__}: {str(exc)[:120]})")
            continue
        total += res["settled"]
        print(f"{sport}: graded {res['settled']} ({res['hits']} hits, {res['voids']} void) on "
              f"{[d for d, _ in res['days']]}; waiting {sorted(res['waiting'])}"
              + (f"; errors {res.get('errors')}" if res.get("errors") else ""))
    print(f"total graded: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
