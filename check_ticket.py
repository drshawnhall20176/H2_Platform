"""check_ticket.py — the Slip Lab ticket checker from the command line / a workflow (Nov 2).

  python check_ticket.py --sport NFL --legs "Jaxon Smith-Njigba | Receiving Yards | 80+ ; Cooper Kupp | Receptions | 3+" --price 1200
Legs separated by ";" or newlines (parlay_check.parse format). Prints each leg's read, the ticket's chances, the
weakest leg and the warnings, with the sport's approved honest-chance factor applied.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

import pytz


def main(argv=None) -> int:
    import best_bets_data as BBD
    import calibration as CAL
    import parlay_check as PC
    import props_engine as PE
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", default="NFL")
    ap.add_argument("--date", default="")
    ap.add_argument("--book", default="draftkings")
    ap.add_argument("--legs", required=True)
    ap.add_argument("--price", default="")
    a = ap.parse_args(argv)
    date_str = a.date or datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
    legs, bad = PC.parse(a.legs.replace(";", "\n"))
    reads = BBD.load_slate_reads(a.sport, date_str, a.book) or {}
    read = [PC.read_leg(l, reads, a.sport) for l in legs]
    price = float(a.price) if a.price.strip() else None
    res = PC.check(read, price)
    out = [f"## Ticket check — {a.sport} {date_str} · honest-chance factor {CAL.factor(a.sport):.2f}", ""]
    out += [f"- couldn't read: {b}" for b in bad]
    out += ["| Leg | Chance (honest) | Model raw | Projection | Cushion | From | Notes |", "|---|---|---|---|---|---|---|"]
    for l in read:
        out.append(f"| {'⚠️ ' if l is res['weakest'] else ''}{l['player']} {l['market']} {l['side']} {l['line']:g} | "
                   f"{l['p']:.0%} | {l['p_raw']:.0%} | {'—' if l.get('projection') is None else format(l['projection'], '.1f')} | "
                   f"{PE.cushion_text(l.get('cushion'))} | {l['source']} | {' · '.join(l['flags']) or '—'} |")
    out += ["", f"**Cashes:** {res['p_all']:.1%} · **Misses by exactly one:** {res['p_miss_one']:.1%} · "
                f"**Fair price:** {'—' if res['fair_american'] is None else format(res['fair_american'], '+d')}"
                + ("" if res["ev"] is None else f" · **Value at {price:+.0f}:** {res['ev']:+.0%}")]
    w = res["weakest"]
    if w is not None:
        out.append(f"**Weakest leg:** {w['player']} {w['market']} {w['side']} {w['line']:g} ({w['p']:.0%}) — without it the "
                   f"ticket is {res['p_all'] / max(w['p'], 1e-9):.1%} to cash.")
    out += [f"- ⚠️ {x}" for x in res["warnings"]]
    text = "\n".join(out)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
