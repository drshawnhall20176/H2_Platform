"""
ledger_close.py — the closing price of every SHOWN pick, captured just before its game starts (Nov 22).

Owner, Nov 22 (after upgrading the Odds API plan): yes to capturing closing lines more often in the last hour. The
shown-picks ledger (pick_ledger.py) used to take a pick's close from the last hourly board rebuild before the game --
up to an hour early, and only for props on a saved board. Closing-line value is the evidence phase 1 rests on, so
the close should be the price right before the start.

close_watch.py (one long run, started three or four times a day) now also wakes for every game with a ledger pick --
the strongest list, the 💰 props and the 💰 game lines -- at CAPTURE_LEADS minutes before the start (60, 30, 15, 5),
fetches that one game's odds, and saves each pick's current line and price at the pick's own book (KEY). Each capture
overwrites the one before, so the last one before the start is the close. The morning grading (pick_ledger.grade_day)
uses it, and falls back to the old hourly read only when no capture landed.

The rules that choose picks don't change -- only when the close is read -- so no rule version changes.
"""
from __future__ import annotations

import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

KEY = "LEDGER_CLOSE:{day}"
CAPTURE_LEADS = (60, 30, 15, 5)
GAME_KEYS = {"Moneyline": "h2h", "Spread": "spreads"}
SPORTS = ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB", "WNBA")


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return "".join(c for c in s.lower() if c.isalnum())


def _words(s) -> List[str]:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return [w for w in "".join(c if c.isalnum() else " " for c in s).split() if w]


def same_team(label: str, name: str) -> bool:
    """"Miami" ~ "Miami Hurricanes", "San José St Spartans" ~ "San Jose State Spartans", NFL "MIN" ~ "Minnesota
    Vikings" (the NFL board names teams by abbreviation)."""
    lab = str(label or "").strip()
    if 1 < len(lab) <= 3 and lab.isupper():
        try:
            import position_lines as PLN
            full = PLN.NFL_TEAMS.get(lab)
        except Exception:                                       # noqa: BLE001
            full = None
        return bool(full) and _norm(full) == _norm(name)
    a, b = _norm(label), _norm(name)
    if not a or not b:
        return False
    if a == b or b.startswith(a) or a.startswith(b):
        return True
    wa, wb = _words(label), _words(name)
    return len(wa) > 1 and len(wb) > 1 and wa[0] == wb[0] and wa[-1] == wb[-1]


def _when(e: Dict) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(e.get("commence_time")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def match_event(game: str, events: Sequence[Dict], kick: Optional[datetime] = None, game_id=None) -> Optional[Dict]:
    """The Odds API event for a ledger game label ("Away @ Home"): by id when the row carries one, else both teams'
    names, and the start within 3 hours when the row has a time (two "Miami"s on one slate)."""
    if game_id:
        for e in events:
            if str(e.get("id")) == str(game_id):
                return e
    g = str(game or "")
    sep = " @ " if " @ " in g else " vs " if " vs " in g else None
    if not sep:
        return None
    away, home = (x.strip() for x in g.split(sep, 1))
    hits = []
    for e in events:
        if not (same_team(away, e.get("away_team")) and same_team(home, e.get("home_team"))) and \
                not (same_team(away, e.get("home_team")) and same_team(home, e.get("away_team"))):
            continue
        w = _when(e)
        if kick and w and abs((w - kick).total_seconds()) > 3 * 3600:
            continue
        hits.append(e)
    return hits[0] if len(hits) == 1 else None


def _book_ok(book, bm: Dict) -> bool:
    b = _norm(book)
    return bool(b) and b in (_norm(bm.get("key")), _norm(bm.get("title")))


def _pick_point(cands: List[Tuple[float, Optional[int], Optional[int]]], line) -> Optional[Tuple]:
    """(point, side price, other side price): the pick's own line when the book still has it, else the book's main
    line (both sides posted, prices closest to even)."""
    if not cands:
        return None
    if line is not None:
        for c in cands:
            if c[0] is not None and float(c[0]) == float(line):
                return c
    both = [c for c in cands if c[1] is not None and c[2] is not None] or cands

    def gap(c):
        try:
            import betlog as B
            return abs(1 / B.american_to_decimal(c[1]) - 1 / B.american_to_decimal(c[2])) if c[2] is not None else 9
        except Exception:                                       # noqa: BLE001
            return 9
    return min(both, key=gap)


def prop_close(row: Dict, event_json: Dict, market_key: str) -> Optional[Dict]:
    """{"line", "price", "book"} -- the pick's book's line and price for its side right now. A pick'em pick (no
    sportsbook price) takes its pick'em book's line."""
    who, side = _norm(row.get("player")), str(row.get("side") or "")
    if not who or side not in ("Over", "Under"):
        return None
    cands = []
    for bm in event_json.get("bookmakers") or []:
        if not _book_ok(row.get("book"), bm):
            continue
        pts: Dict[float, Dict[str, Optional[int]]] = {}
        for mk in bm.get("markets") or []:
            if mk.get("key") != market_key:
                continue
            for oc in mk.get("outcomes") or []:
                if _norm(oc.get("description")) != who or oc.get("point") is None:
                    continue
                pts.setdefault(float(oc["point"]), {})[str(oc.get("name") or "").title()] = oc.get("price")
        other = "Under" if side == "Over" else "Over"
        cands = [(p, v.get(side), v.get(other)) for p, v in pts.items() if side in v]
        break
    c = _pick_point(cands, row.get("line"))
    if not c:
        return None
    return {"line": c[0], "price": int(c[1]) if c[1] is not None else None, "book": row.get("book")}


def game_close(row: Dict, event_json: Dict) -> Optional[Dict]:
    """{"line", "price", "book"} for a game-line pick: its side's moneyline, or its spread (its own number when the
    book still has it, else the book's current number). The pick's book when it's posted, else the best price."""
    key = GAME_KEYS.get(row.get("money_market"))
    s = str(row.get("money_side") or "").lower()
    team = event_json.get("away_team") if s == "away" else event_json.get("home_team") if s == "home" else None
    if not key or not team:
        return None
    by_book = []
    for bm in event_json.get("bookmakers") or []:
        for mk in bm.get("markets") or []:
            if mk.get("key") != key:
                continue
            for oc in mk.get("outcomes") or []:
                if _norm(oc.get("name")) == _norm(team) and oc.get("price") is not None:
                    by_book.append((bm, oc.get("point"), int(oc["price"])))
    if not by_book:
        return None
    own = [x for x in by_book if _book_ok(row.get("book"), x[0])]
    pool = own or by_book
    line = row.get("money_line")
    if key == "spreads":
        same = [x for x in pool if x[1] is not None and line is not None and float(x[1]) == float(line)]
        if same:
            pool = same
        elif not own:                                           # no book on our number: the most common number now
            pts = [x[1] for x in pool if x[1] is not None]
            common = max(set(pts), key=pts.count) if pts else None
            pool = [x for x in pool if x[1] == common] or pool
    import betlog as B
    bm, pt, pr = max(pool, key=lambda x: B.american_to_decimal(x[2]) or 0)
    return {"line": pt if key == "spreads" else None, "price": pr, "book": bm.get("title") or bm.get("key")}


# --------------------------------------------------------------------------- what to watch
def ledger_rows(day: str, get=None) -> List[Dict]:
    """Every pick on `day`'s ledgers (strongest list, 💰 props, 💰 game lines), one per pick key + book, each tagged
    with its ledger key."""
    import pick_ledger as PL
    out, seen = [], set()
    targets = [("strong", "ALL")] + [("money", s) for s in SPORTS] + [("games", s) for s in SPORTS]
    for kind, sp in targets:
        for k, r in (PL.load(kind, sp, day, get)["rows"] or {}).items():
            tag = (k, _norm(r.get("book")) if isinstance(r.get("book"), str) else "")
            if tag in seen:
                continue
            seen.add(tag)
            out.append(dict(r, _key=k, sport=r.get("sport") or r.get("league") or sp, _day=day))
    return out


def kickoff(r: Dict) -> Optional[datetime]:
    import pick_ledger as PL
    if r.get("kickoff"):
        try:
            k = datetime.fromisoformat(str(r["kickoff"]).replace("Z", "+00:00"))
            return k if k.tzinfo else k.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return PL.kick(r.get("_day"), r.get("time"))


def markets_for(rows_: Sequence[Dict], sport_key: str) -> Tuple[List[str], List[str]]:
    """(prop market keys, game market keys) the rows need."""
    import sports
    try:
        mm = sports.get(sport_key).market_map
    except Exception:                                           # noqa: BLE001
        mm = {}
    props = sorted({mm[r["market"]] for r in rows_ if not r.get("money_market") and r.get("market") in mm})
    games = sorted({GAME_KEYS[r["money_market"]] for r in rows_ if r.get("money_market") in GAME_KEYS})
    return props, games


def close_for(r: Dict, js: Dict, sport_key: str) -> Optional[Dict]:
    import sports
    if r.get("money_market"):
        return game_close(r, js)
    try:
        mk = sports.get(sport_key).market_map.get(r.get("market"))
    except Exception:                                           # noqa: BLE001
        mk = None
    return prop_close(r, js, mk) if mk else None


# --------------------------------------------------------------------------- storage
def cap_key(r: Dict) -> str:
    b = r.get("book")
    return f"{r.get('_key')}|{_norm(b) if isinstance(b, str) else ''}"


def load(day: str, get=None) -> Dict:
    if get is None:
        import model_store as MS
        get = MS.get_setting
    try:
        return get(KEY.format(day=day), None) or {}
    except Exception:                                           # noqa: BLE001
        return {}


def save_caps(day: str, caps: Dict[str, Dict], get=None, save=None) -> None:
    if not caps:
        return
    cur = dict(load(day, get))
    cur.update(caps)
    if save is None:
        import model_store as MS
        save = MS.save_setting
    save(KEY.format(day=day), cur)


def captured(day: str, row_key: str, book, caps: Optional[Dict] = None, get=None) -> Optional[Dict]:
    """The last pre-game capture for a ledger pick (pick_ledger grading), or None."""
    caps = load(day, get) if caps is None else caps
    return caps.get(f"{row_key}|{_norm(book) if isinstance(book, str) else ''}")


def slate_days(now: datetime) -> List[str]:
    """Today's slate in New York, and yesterday's until 6 AM (late West Coast games belong to it)."""
    import pytz
    et = now.astimezone(pytz.timezone("US/Eastern"))
    d = et.date()
    return [d.isoformat()] + ([(d - timedelta(days=1)).isoformat()] if et.hour < 6 else [])
