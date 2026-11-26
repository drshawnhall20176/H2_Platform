"""
prop_moves.py -- the day's biggest pregame PROP line moves across the books, and quotes that look off (Nov 26).

Owner, Nov 26 ("build all 7", PropSeason pass 3, Lines tab):
  * Market watch: each player prop's line from today's first capture to the latest, per book (line_history, captured by
    the snapshot job). A move counts when two or more books moved the same way; the size is the books' median move.
    Only games that haven't started -- PropSeason's list mixes in live in-game lines (a -112 spread "moving" to
    +3500), which says nothing about the pregame market.
  * Looks off: a book whose price at a line is far from the other books' at the same line. Usually a stale quote the
    book hasn't refreshed, sometimes a posting error -- either way not a real better price, so the Test list's "best
    price" leaves it out (book_check.best_at_line).
"""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Dict, Iterable, List, Optional, Tuple

OFF_GAP = 0.08          # a book's implied chance 8+ points from the other books' median at the same line
MIN_BOOKS = 3           # need at least this many books at a line to call one of them off


def _ts(x) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def implied(price) -> Optional[float]:
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if -100 < p < 100:
        return None
    return 100 / (p + 100) if p > 0 else -p / (-p + 100)


def moves(index: Dict[Tuple[str, str], List[Dict]], now: Optional[datetime] = None, side: str = "Over",
          min_books: int = 2) -> List[Dict]:
    """[{player, market, game, open, now, delta, books, pct}] biggest first, pregame only."""
    now = now or datetime.now(timezone.utc)
    out = []
    for (player, market), rows in (index or {}).items():
        per_book: Dict[str, List[Dict]] = {}
        game = None
        for r in rows:
            if str(r.get("side") or "").lower() != side.lower() or r.get("line") is None:
                continue
            start = _ts(r.get("commence_time"))
            cap = _ts(r.get("captured_at"))
            if start is None or start <= now or (cap is not None and cap >= start):
                continue                                        # started games and in-game captures never count
            per_book.setdefault(str(r.get("book")), []).append(r)
            game = game or r.get("game")
        deltas = []
        opens, lasts = [], []
        for lst in per_book.values():
            lst.sort(key=lambda r: str(r.get("captured_at")))
            a, b = float(lst[0]["line"]), float(lst[-1]["line"])
            if a != b:
                deltas.append(b - a)
                opens.append(a)
                lasts.append(b)
        if len(deltas) < min_books:
            continue
        ups = sum(d > 0 for d in deltas)
        downs = len(deltas) - ups
        if min(ups, downs) > 0 and max(ups, downs) < min_books:
            continue                                            # books split -- no market move
        same = [d for d in deltas if (d > 0) == (ups >= downs)]
        if len(same) < min_books:
            continue
        d = median(same)
        o = median(opens)
        out.append({"player": player, "market": market, "game": game, "open": o, "now": o + d, "delta": d,
                    "books": len(same), "pct": abs(d) / max(abs(o), 1.0)})
    return sorted(out, key=lambda m: -m["pct"])


def looks_off(books: Dict[str, float], gap: float = OFF_GAP, min_books: int = MIN_BOOKS) -> Dict[str, float]:
    """{book: how far its implied chance sits from the others' median} for books that look off at one line/side."""
    imp = {b: implied(p) for b, p in (books or {}).items()}
    imp = {b: v for b, v in imp.items() if v is not None}
    if len(imp) < min_books:
        return {}
    out = {}
    for b, v in imp.items():
        others = [x for k, x in imp.items() if k != b]
        m = median(others)
        if abs(v - m) >= gap:
            out[b] = v - m
    return out


def text(m: Dict) -> str:
    arrow = "▲" if m["delta"] > 0 else "▼"
    return (f"{m['player']} · {m['market']} {m['open']:g} → {m['now']:g} {arrow} {m['delta']:+g} "
            f"({m['books']} books)")


def for_sports(sports_: Iterable[str], day: str, index_for=None, now: Optional[datetime] = None, n: int = 8) -> List[Dict]:
    """The day's biggest moves across the given sports."""
    out = []
    for sp in sports_:
        try:
            idx = index_for(sp, day) if index_for else __import__("line_history").sport_index(sp, since=day)
        except Exception:                                       # noqa: BLE001
            continue
        out += [dict(m, sport=sp) for m in moves(idx, now)]
    return sorted(out, key=lambda m: -m["pct"])[:n]
