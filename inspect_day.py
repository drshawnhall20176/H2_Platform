"""
inspect_day.py — read-only look at one day from the database (Nov 2), for review without a browser:
the stored morning report, the Bet Log rows for that slate (with results), and every kickoff snapshot for one
market graded against ESPN's box scores. Run by the inspect-day workflow; prints to the log and run summary.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _out(text: str) -> None:
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(text + "\n")


def main(argv=None) -> int:
    import betlog as B
    import model_store as MS
    import postgame as PG
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", default="NFL")
    ap.add_argument("--date", required=True, help="slate date (the morning report is the next day)")
    ap.add_argument("--market", default="", help="grade every snapshot in this market")
    ap.add_argument("--part", default="all", help="report / bets / market / all")
    a = ap.parse_args(argv)
    from datetime import date, timedelta
    morning = (date.fromisoformat(a.date) + timedelta(days=1)).isoformat()
    if a.part in ("all", "report"):
        rep = MS.load_daily_review(a.sport, morning) or {}
        s = (rep.get("slates") or {}).get(a.date) or {}
        _out(f"## {a.sport} morning report {morning}\n")
        _out("```\n" + json.dumps({k: s.get(k) for k in ("counts", "model", "use", "most_probable", "markets",
                                                          "big_gap", "causes", "top_misses")}, indent=1, default=str)[:20000] + "\n```")
        _out("Suggestions:\n```\n" + json.dumps(rep.get("suggestions"), indent=1, default=str)[:8000] + "\n```")
    if a.part in ("all", "bets"):
        bets = [b for b in B.list_bets(sport=a.sport) if str(b.get("slate_date") or "")[:10] == a.date]
        _out(f"## Bet Log {a.sport} {a.date}: {len(bets)} rows\n")
        _out("| id | ticket | player | market | side | line | odds | stake | result | notes |\n|---|---|---|---|---|---|---|---|---|---|")
        for b in sorted(bets, key=lambda b: (str(b.get("ticket") or ""), b.get("id") or 0)):
            _out(f"| {b.get('id')} | {b.get('ticket') or ''} | {b.get('player') or '(ticket)'} | {b.get('market')} | "
                 f"{b.get('side')} | {b.get('line')} | {b.get('entry_odds')} | {b.get('stake')} | {b.get('result') or 'open'} | "
                 f"{(b.get('notes') or '')[:40]} |")
    if a.part in ("all", "market") and a.market:
        snaps = [s for s in MS.load_snapshots(a.sport, [a.date]) if str(s.get("market")).lower() == a.market.lower()]
        res = PG.fetch_results(a.sport, a.date, sorted({(s["team"], s["opp"]) for s in snaps}))
        graded = PG.grade(snaps, res)
        _out(f"## {a.market} snapshots {a.date}: {len(graded)}\n")
        _out("| player | team | game | line | side | proj | chance | price | actual | result | use | flags |\n|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r in sorted(graded, key=lambda r: -(float(r.get("projection") or 0))):
            _out(f"| {r.get('player')} | {r.get('team')} | {r.get('game')} | {r.get('line')} | {r.get('side')} | "
                 f"{r.get('projection')} | {r.get('chance')} | {r.get('price')} | {r.get('actual')} | {r.get('result')} | "
                 f"{r.get('use_tag') or ''} | {str(r.get('flags') or '')[:60]} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
