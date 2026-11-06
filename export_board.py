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

USES = {"🔒 Most probable": (), "Most probable": (),
        "All playable": ("🎟️ Parlay + Single", "🎟️ Parlay leg", "🎯 Single only"),
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
        if show in ("Most probable", "🔒 Most probable"):
            import props_engine as PE
            if not PE.most_probable(p.get("ModelProb"), p.get("Cushion"), p.get("Gap")):
                continue
        # Nov 6: every row, not only the player-props model's -- the older fallback model's rows carry no Use tag (and
        # inflated chances: an 80% Draymond Green Pts+Ast lost Nov 5), so they slipped into "Parlay legs". They now
        # show only under "Everything".
        elif show != "Everything" and p.get("Use") not in USES[show]:
            continue
        if show != "Everything" and (p.get("Conviction") or 0) < min_conv:
            continue
        out.append(p)
    return sorted(out, key=lambda p: p.get("ModelProb") or 0, reverse=True)


def reads_table(sport: str, date_str: str, book: str, market: str, slot: str = "All slate") -> str:
    """Raw Player props reads for one market (every player with a book line, both sides) -- e.g. Anytime TD, where
    the board only lists a "Yes" the model makes 50%+. p_* are the Over / Yes probabilities; value = model vs the
    price (the model's chance x decimal odds - 1)."""
    import best_bets_data as BBD
    import props_engine as PE
    import sports
    reads = BBD.load_slate_reads(sport, date_str, book) or {}
    _rows, meta = sports.get(sport).engine.build_slate(date_str)
    when = {m["label"]: sports.game_dt(m.get("game_date")) for m in meta}
    out = []
    for (_pid, _mk), r in reads.items():
        if str(r.get("market")).lower() != market.lower() or r.get("line") is None or r.get("out"):
            continue
        dt = when.get(r.get("game"))
        if slot != "All slate" and sports.slot_of(dt) != slot:
            continue
        price = r.get("over_price")
        pm = r.get("p_model")
        val = None if (price is None or pm is None) else pm * PE.decimal(price) - 1 if hasattr(PE, "decimal") else None
        if val is None and price is not None and pm is not None:
            dec = 1 + (price / 100 if price > 0 else 100 / -price)
            val = pm * dec - 1
        out.append((r, dt, val))
    out.sort(key=lambda t: -(t[0].get("p_final") or 0))
    lines = [f"## {market} reads — {date_str} · {slot}\n",
             "| # | Time | Player | Team | Game | Proj | Model | Market | Blend | Price | Value | Lean | Flags | Line | Recent (newest first) | Min/opp | Season g |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, (r, dt, val) in enumerate(out, 1):
        f = lambda x: "—" if x is None else f"{x:.0%}"
        lines.append(f"| {i} | {dt.strftime('%I:%M %p').lstrip('0') if dt else 'TBD'} | {r.get('player')} | "
                     f"{r.get('team_name') or ''} | {r.get('game')} | "
                     f"{'—' if r.get('projection') is None else format(r['projection'], '.2f')} | {f(r.get('p_model'))} | "
                     f"{f(r.get('p_market'))} | {f(r.get('p_final'))} | "
                     f"{'—' if r.get('over_price') is None else format(r['over_price'], '+.0f')} | "
                     f"{'—' if val is None else format(val, '+.0%')} | {r.get('lean') or '—'} | "
                     f"{'; '.join(str(x) for x in (r.get('flags') or [])[:2]) or '—'} | {r.get('line')} | "
                     f"{','.join(format(float(v), 'g') for v in (r.get('values') or [])[:8])} | "
                     f"{'—' if r.get('opp') is None else format(float(r['opp']), '.1f')} | {r.get('season_games', '—')} |")
    return "\n".join(lines)


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
    ap.add_argument("--reads", default="", help="dump raw model reads for this market instead (e.g. Anytime TD)")
    a = ap.parse_args(argv)
    date_str = a.date or datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
    if a.reads:
        md = reads_table(a.sport, date_str, a.book, a.reads, a.slot)
        print(md)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
                f.write(md + "\n")
        with open(a.out, "w") as f:
            f.write(md)
        return 0
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
