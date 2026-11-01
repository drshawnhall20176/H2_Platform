"""
export_board.py — the Best Bets board without a browser (Nov 1). Same loader as the page
(best_bets_data.load_generic_best_bets_board -> the Position Matchups player-props model at the books' lines), the
same filters (time slot, market group, side, Show), ranked the way the page ranks (Model %). Run by the
export-board workflow ("Run workflow" from a phone); prints a table to the run summary and saves a JSON artifact.

  python export_board.py --sport NFL --slot Afternoon --unit Offense --side Over --show "All playable" --top 25
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

import pytz

USES = {"All playable": ("🎟️ Parlay + Single", "🎟️ Parlay leg", "🎯 Single only"),
        "Singles": ("🎟️ Parlay + Single", "🎯 Single only"),
        "Parlay legs": ("🎟️ Parlay + Single", "🎟️ Parlay leg")}


def board(sport: str, date_str: str, book: str):
    import best_bets_data as BBD
    import sports
    plays, meta, _ = BBD.load_generic_best_bets_board(sport, date_str, book)
    when = {m["label"]: sports.game_dt(m.get("game_date")) for m in meta}
    for p in plays:
        dt = when.get(p["Game"])
        p["Slot"] = sports.slot_of(dt)
        p["Time"] = dt.strftime("%I:%M %p").lstrip("0") + " ET" if dt else "TBD"
    return plays


def pick(plays, slot="All slate", unit="All", side="All Sides", show="All playable", min_conv=1.0):
    import football_props as FP
    out = []
    for p in plays:
        if slot != "All slate" and p.get("Slot") != slot:
            continue
        if unit != "All" and (FP.market_unit(p.get("Market")) or "Offense") != unit:
            continue
        if side != "All Sides" and p.get("Side") != side:
            continue
        if show != "Everything" and p.get("Model") == "player-props" and p.get("Use") not in USES[show]:
            continue
        if show != "Everything" and (p.get("Conviction") or 0) < min_conv:
            continue
        out.append(p)
    return sorted(out, key=lambda p: p.get("ModelProb") or 0, reverse=True)


def _pct(x):
    return "—" if x is None else f"{x:+.0%}"


def table(rows) -> str:
    head = "| # | Time | Player | Team | Market | Pick | Proj | Model % | Cushion | Edge | Price | Use | Game |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|"
    lines = [head]
    for i, p in enumerate(rows, 1):
        pick_ = p["Side"] if p.get("Line") is None else f"{p['Side']} {p['Line']:g}"
        price = p.get("RealPrice")
        lines.append(f"| {i} | {p.get('Time')} | {p['Player']} | {p.get('Team') or ''} | {p['Market']} | {pick_} | "
                     f"{'—' if p.get('Projection') is None else format(p['Projection'], '.1f')} | "
                     f"{p['ModelProb']:.0%} | {_pct(p.get('Cushion'))} | "
                     f"{'—' if p.get('EV') is None else format(p['EV'], '+.1%')} | "
                     f"{'—' if price is None else f'{price:+.0f}'}{'' if not p.get('RealPriceBook') else ' ' + str(p['RealPriceBook'])} | "
                     f"{p.get('Use') or '—'} | {p['Game']} |")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", default="NFL")
    ap.add_argument("--date", default="")
    ap.add_argument("--book", default="draftkings")
    ap.add_argument("--slot", default="All slate")
    ap.add_argument("--unit", default="All")
    ap.add_argument("--side", default="All Sides")
    ap.add_argument("--show", default="All playable")
    ap.add_argument("--min-conv", type=float, default=1.0)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--market", default="", help="only this market (e.g. Anytime TD)")
    ap.add_argument("--out", default="board.json")
    a = ap.parse_args(argv)
    date_str = a.date or datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
    plays = board(a.sport, date_str, a.book)
    rows = pick(plays, a.slot, a.unit, a.side, a.show, a.min_conv)
    if a.market:
        rows = [p for p in rows if str(p.get("Market")).lower() == a.market.lower()]
    title = (f"## {a.sport} Best Bets — {date_str} · {a.slot} · {a.unit} · {a.side} · {a.show}\n\n"
             f"{len(plays)} plays on the board, {len(rows)} pass these filters; top {min(a.top, len(rows))} by Model %.\n\n")
    md = title + table(rows[:a.top])
    print(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(md + "\n")
    with open(a.out, "w") as f:
        json.dump({"date": date_str, "filters": vars(a), "plays": rows}, f, default=str, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
