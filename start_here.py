"""
start_here.py — a "Start here" shortlist above a full board (Nov 16).

The Best Bets board is every playable prop with eight filters above it: complete, and nothing tells a visitor where to
look first. This picks the few reads worth opening the page for, from the board the page already built (no extra
fetch, no credits):

  * only playable reads (a 🎟️ / 🎯 Use tag or 🔒 Most probable), none held for a news check, none carrying a warning
  * never a pick type whose last-30-day record is losing (the same rule Home applies)
  * pick types with a winning record first, then 🔒, then the highest chance; one read per player

Sports whose board has no Use tags (MLB / WNBA engines) fall back to the highest-chance reads with real conviction;
those carry no record, and the card says so.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

import pick_records as PR

N = 4
MIN_CONVICTION = 1.2
WINNING, NEW, NO_RECORD = "✅ Winning record", "🆕 Too new to judge", "No record for this pick type yet"


def _price(v, book=None) -> str:
    try:
        return f"{float(v):+.0f}" + (f" · {book}" if book else "")
    except (TypeError, ValueError):
        return "no price yet"


def shortlist(sport: str, plays: List[Dict], records_for: Optional[Callable] = None, n: int = N) -> List[Dict]:
    """[{pick, chance, price, game, time, lock, standing, record}] -- at most n, one per player."""
    import todays_best as TB
    clean = [p for p in plays or [] if p.get("Lean") != "Check news" and not p.get("Warnings")]
    rows = [dict(r) for r in TB.props_rows(sport, clean)]
    PR.annotate_props(rows, records_for or PR.tag_records)
    rows = [r for r in rows if r.get("verdict") not in PR.HIDE]
    rows.sort(key=lambda r: (r.get("verdict") != "ok", not r.get("lock"), -(r.get("chance") or 0)))
    out, seen = [], set()
    for r in rows:
        if r.get("player") in seen:
            continue
        seen.add(r.get("player"))
        out.append({"pick": r["pick"], "chance": r.get("chance"),
                    "price": ("pick'em only" if r.get("pickem_only") else _price(r.get("price"), r.get("book"))),
                    "game": r.get("game") or "", "time": r.get("time") or "", "lock": bool(r.get("lock")),
                    "standing": WINNING if r.get("verdict") == "ok" else NEW, "record": r.get("record") or ""})
        if len(out) >= n:
            return out
    if out:
        return out
    # no Use tags on this board: the strongest reads by chance, with real conviction behind them
    alt = sorted([p for p in clean if (p.get("Conviction") or 0) >= MIN_CONVICTION and p.get("ModelProb") is not None],
                 key=lambda p: -p["ModelProb"])
    for p in alt:
        if p.get("Player") in seen:
            continue
        seen.add(p.get("Player"))
        line = p.get("Line")
        out.append({"pick": f"{p.get('Player')} {p.get('Market')} {p.get('Side')}" + ("" if line is None else f" {line:g}"),
                    "chance": p.get("ModelProb"),
                    "price": _price(p.get("RealPrice"), p.get("RealPriceBook")) if p.get("RealPrice") is not None
                    else "no price yet", "game": p.get("Game") or "", "time": p.get("Time") or "", "lock": False,
                    "standing": NO_RECORD, "record": ""})
        if len(out) >= n:
            break
    return out
