"""
book_check.py -- each Test-list pick against what a chosen sportsbook (and pick'em app) is offering right now (Nov 26).

Owner: "a separate column that will compare model book needs vs what the book is currently offering and gives me a go /
no go indicator ... the sports book and pick'em drop down ... so I can scroll through the different books to identify
the best option."

Prices come from the same feeds the boards use -- no new kind of call:
  * props      -- best_bets_data.recent_offers (the warm-up job's saved fetch when under 45 minutes old, else one live
                  fetch cached 5 minutes): every sportsbook's price at every posted line, plus the pick'em apps' lines;
  * game lines -- odds_api.fetch_sport_game_lines: spread, total and moneyline for every game of a sport in ONE request
                  (3 credits), cached 5 minutes.

The verdict at a book (same line as the pick):  edge = earned chance - the book price's break-even
    ✅ Go       edge >= +1 point
    🟡 Thin     0 to +1 point (a coin-flip margin -- shop for a better price)
    ⛔ No go    below break-even
A book posting a different line gets 🔁 with the number and whether it's better or worse for the pick's side (the
chance was read at the pick's line, so a different line is a re-check, never a silent Go). Close-gap picks carry no
chance of their own yet: 📝 Paper, with the price shown so the test can be logged at a real number.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

GO, THIN, NOGO, PAPER, NONE, OTHER = "✅ Go", "🟡 Thin", "⛔ No go", "📝 Paper", "— Not posted", "🔁"
GO_EDGE = 0.01


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def implied(price) -> Optional[float]:
    p = _f(price)
    if p is None or -100 < p < 100:
        return None
    return 100 / (p + 100) if p > 0 else -p / (-p + 100)


def _norm(s) -> str:
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", " ", s)
    return " ".join(s.split())


# --------------------------------------------------------------------------- props
def prop_quotes(offers: Iterable[Dict], player: str, market_key: str, side: str) -> Dict[float, Dict]:
    """{line: {"books": {book: price}, "apps": {app: {...}}}} for one player's market, the pick's side."""
    side = "under" if str(side or "").lower().startswith("u") else "over"
    who = _norm(player)
    out: Dict[float, Dict] = {}
    for o in offers or []:
        if o.get("market") != market_key or _norm(o.get("player")) != who or o.get("point") is None:
            continue
        pt = float(o["point"])
        slot = out.setdefault(pt, {"books": {}, "apps": {}})
        slot["books"].update({b: p for b, p in (o.get(side) or {}).items() if p is not None})
        for app, sides in (o.get("pickem") or {}).items():
            if sides.get(side) is not None or sides:
                slot["apps"][app] = sides.get(side) or {}
    return out


def better_line(side: str, pick_line: float, other: float) -> bool:
    """Is `other` a better number than `pick_line` for this side? Over / a spread side: lower is better for Over,
    higher (more points) is better for a spread side. Under: higher is better."""
    s = str(side or "").lower()
    if s.startswith("o"):
        return other < pick_line
    return other > pick_line                                     # under, or a team's spread line


# --------------------------------------------------------------------------- game lines
_MKT = {"Spread": "spreads", "Total": "totals", "Moneyline": "h2h"}


def _team_match(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    return bool(a and b) and (a == b or a.startswith(b) or b.startswith(a))


def find_event(events: Iterable[Dict], home: str, away: str) -> Optional[Dict]:
    for e in events or []:
        if _team_match(e.get("home_team"), home) and _team_match(e.get("away_team"), away):
            return e
    return None


def game_quotes(event: Optional[Dict], market: str, side: str, home: str, away: str) -> Dict[Optional[float], Dict]:
    """{line: {"books": {book: price}}} for one game pick. side: home / away / over / under."""
    out: Dict[Optional[float], Dict] = {}
    if not event:
        return out
    key = _MKT.get(market)
    want = {"home": event.get("home_team"), "away": event.get("away_team")}.get(side)
    for bm in event.get("bookmakers") or []:
        book = bm.get("key")
        for mk in bm.get("markets") or []:
            if mk.get("key") != key:
                continue
            for oc in mk.get("outcomes") or []:
                name = str(oc.get("name") or "")
                if key == "totals":
                    if name.lower() != side:
                        continue
                elif name != want:
                    continue
                pt = _f(oc.get("point")) if key != "h2h" else None
                if oc.get("price") is None:
                    continue
                out.setdefault(pt, {"books": {}})["books"][book] = oc["price"]
    return out


# --------------------------------------------------------------------------- verdicts
def verdict(chance: Optional[float], price, kind_paper: bool = False) -> Tuple[str, Optional[float]]:
    need = implied(price)
    if price is None or need is None:
        return NONE, None
    if kind_paper or chance is None:
        return PAPER, None
    edge = float(chance) - need
    return (GO if edge >= GO_EDGE else THIN if edge >= 0 else NOGO), edge


def at_book(quotes: Dict, line: Optional[float], book: str, side: str) -> Dict:
    """The chosen book's quote for the pick: same line if posted, else its nearest line (flagged)."""
    same = (quotes.get(line) or {}).get("books", {}) if line in quotes or line is None else {}
    if book in same:
        return {"price": same[book], "line": line, "same": True}
    others = [(pt, q["books"][book]) for pt, q in quotes.items() if book in q.get("books", {}) and pt is not None]
    if not others or line is None:
        return {"price": None, "line": None, "same": False}
    pt, price = min(others, key=lambda x: abs(x[0] - line))
    return {"price": price, "line": pt, "same": False, "better": better_line(side, line, pt)}


def best_at_line(quotes: Dict, line: Optional[float], books: Iterable[str]) -> Optional[Tuple[str, float]]:
    """The best price any of `books` posts at the pick's exact line."""
    q = (quotes.get(line) or {}).get("books", {})
    have = [(b, p) for b, p in q.items() if b in set(books) and _f(p) is not None]
    if not have:
        return None
    return max(have, key=lambda bp: (100 / (-bp[1]) if bp[1] < 0 else bp[1] / 100))


def judge(row: Dict, quotes: Dict, book: str, books: Iterable[str]) -> Dict:
    """Book columns for one Test-list row."""
    line, side = row.get("line"), row.get("side") or ""
    q = at_book(quotes, line, book, side)
    paper = row.get("kind", "").startswith("🧪 Close")
    if q["price"] is None:
        v, edge = NONE, None
    elif not q["same"]:
        tag = "better" if q.get("better") else "worse"
        v, edge = f"{OTHER} Book has {q['line']:g} ({tag})", None
        if not paper and not q.get("better"):
            v = f"{NOGO} — line {q['line']:g} is worse"
    else:
        v, edge = verdict(row.get("chance"), q["price"], paper)
    best = best_at_line(quotes, line, books)
    return {"book_price": q["price"], "book_line": q["line"], "book_need": implied(q["price"]) if q["same"] else None,
            "book_edge": edge, "book_verdict": v, "best_book": best[0] if best else None,
            "best_price": best[1] if best else None}


def judge_app(row: Dict, quotes: Dict, app: str, app_need: Optional[float]) -> str:
    """The pick'em app column: is the pick on the app at the same line, and does its chance clear the entry's
    per-pick break-even?"""
    if row.get("open_as") == "game":
        return "— Props only"
    line, side = row.get("line"), row.get("side") or ""
    lines = [pt for pt, q in quotes.items() if app in q.get("apps", {})]
    if not lines:
        return NONE
    if line in lines:
        ch = _f(row.get("chance"))
        if ch is None or app_need is None:
            return f"On the app at {line:g}"
        return f"{GO} ({ch:.0%} vs {app_need:.1%})" if ch >= app_need else f"{NOGO} ({ch:.0%} vs {app_need:.1%})"
    pt = min(lines, key=lambda x: abs(x - (line or 0)))
    return f"{OTHER} App has {pt:g} ({'better' if better_line(side, line, pt) else 'worse'})"


# --------------------------------------------------------------------------- comparing two quotes (Nov 26)
def _dec(price) -> Optional[float]:
    p = _f(price)
    if p is None or -100 < p < 100:
        return None
    return 1 + (p / 100 if p > 0 else 100 / -p)


def compare(new_price, new_line, old_price, old_line, side: str, same_word: str = "= same") -> str:
    """How quote `new` stands against quote `old` for the pick's side: ▲ better / ▼ worse, price and line.
    A better line beats any price change; a worse line is worse whatever the price."""
    if new_price is None or old_price is None:
        return "—"
    nl, ol = _f(new_line), _f(old_line)
    if nl is not None and ol is not None and nl != ol:
        better = better_line(side, ol, nl)
        return f"{'▲' if better else '▼'} line {nl:g} vs {ol:g} ({'better' if better else 'worse'})"
    dn, do = _dec(new_price), _dec(old_price)
    if dn is None or do is None or abs(dn - do) < 1e-9:
        return same_word
    return f"{'▲' if dn > do else '▼'} {float(new_price):+.0f} vs {float(old_price):+.0f}"
