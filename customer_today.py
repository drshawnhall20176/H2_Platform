"""
customer_today.py — what the customer's Today page shows (Nov 16).

One short answer to "what should I look at today?", across every in-season sport, built only from what the platform
already saved (the day's props boards and the Game Lab records): it spends no Odds API credits and writes nothing.

Every pick carries its pick type's own 30-day record and a plain standing:
  ✅ Winning record     that pick type has 20+ graded picks in the last 30 days and has won at least half
  🆕 Too new to judge   fewer than 20 graded picks -- shown only when the customer asks for them
Pick types that have been losing are never shown (the same rule Home applies for the owner).
A game line is listed only when it is playable: a tested pick, or a lean whose kind has won 55%+.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

import pick_records as PR

WINNING, NEW = "✅ Winning record", "🆕 Too new to judge"
PROPS_SPORTS = ("NBA", "NFL", "NHL", "NCAAF", "NCAAMB", "WNBA", "MLB")
TOP_N = 40
DISCLAIMER = ("Analysis, not betting advice. These are likelihoods, not certainties, and a past record does not "
              "guarantee future results. 21+ where legal. If gambling stops being fun, call 1-800-GAMBLER.")


def standing(verdict: Optional[str]) -> Optional[str]:
    """The customer's label for a pick type's record; None = not shown (losing)."""
    return WINNING if verdict == "ok" else NEW if verdict in ("new", None) else None


def _price(v) -> str:
    try:
        return f"{float(v):+.0f}"
    except (TypeError, ValueError):
        return "—"


def _tkey(t, parse: Optional[Callable] = None):
    d = parse(t) if parse else None
    return (0, d.hour * 60 + d.minute) if d else (1, 0)


def money_picks(rows: List[Dict], parse_time: Optional[Callable] = None, now=None, n: int = 8) -> List[Dict]:
    """Nov 19 (owner: "a separate section of best money picks on the Today page"): today's 💰 Money picks
    (props_engine.is_money) that haven't started, biggest edge first, one per player.
    [{sport, pick, chance, edge, price, game, time}]"""
    out, seen = [], set()
    for r in sorted((r for r in rows or [] if r.get("kind") == "Prop" and r.get("money")),
                    key=lambda r: -(r.get("edge") or 0)):
        if r.get("player") in seen:
            continue
        if parse_time is not None and now is not None:
            t = parse_time(r.get("time"))
            if t is not None and t <= now:
                continue
        seen.add(r.get("player"))
        out.append({"sport": r.get("sport"), "pick": r.get("pick"), "chance": r.get("chance"), "edge": r.get("edge"),
                    "price": _price(r.get("price")) + (f" · {r['book']}" if r.get("book") and r.get("price") is not None
                                                       else ""),
                    "game": r.get("game") or "", "time": r.get("time") or "", "lock": bool(r.get("lock"))})
        if len(out) >= n:
            break
    return out


def prop_picks(rows: List[Dict], include_new: bool = False, sports: Optional[List[str]] = None,
               records_for: Optional[Callable] = None, parse_time: Optional[Callable] = None,
               top_n: int = TOP_N) -> List[Dict]:
    """Table rows for the day's prop picks: the strongest first within each start time, earliest games first."""
    rows = [dict(r) for r in rows or [] if r.get("kind") == "Prop" and (not sports or r.get("sport") in sports)]
    PR.annotate_props(rows, records_for or PR.tag_records)
    keep = []
    for r in rows:
        st = standing(r.get("verdict"))
        if st is None or (st == NEW and not include_new):
            continue
        keep.append((r, st))
    keep.sort(key=lambda x: (x[1] != WINNING, 0 if x[0].get("lock") else 1, -(x[0].get("chance") or 0)))
    keep = keep[:top_n]
    keep.sort(key=lambda x: _tkey(x[0].get("time"), parse_time))                      # stable: strength kept
    return [{"Time": r.get("time") or "", "Sport": r.get("sport"), "Pick": r.get("pick"),
             "Chance": r.get("chance"),
             "Best price": _price(r.get("price")) + (f" · {r['book']}" if r.get("book") and r.get("price") is not None else ""),
             "Record (30 days)": r.get("record") or "—", "Standing": st, "Game": r.get("game") or ""}
            for r, st in keep]


def line_picks(rows: List[Dict], sports: Optional[List[str]] = None, records_for: Optional[Callable] = None,
               parse_time: Optional[Callable] = None) -> List[Dict]:
    """Table rows for the day's playable game lines (tested picks and 55%+ leans). Tracking-only rows never show."""
    import props_engine as PE
    rows = [r for r in rows or [] if not sports or r.get("sport") in sports]
    PR.annotate_leans(rows, records_for or PR.lean_records)
    out = []
    for r in rows:
        if not r.get("best") or PR.lean_use(r) == PE.USE_PASS:
            continue
        tested = bool(r.get("best_tested"))
        out.append({"_t": _tkey(r.get("time"), parse_time), "_tested": not tested,
                    "Time": r.get("time") or "", "Sport": r.get("sport"), "Game": r.get("game"), "Pick": r.get("best"),
                    "Chance": r.get("best_chance") if tested else None,
                    "Best price": _price(r.get("best_price")) if tested else "—",
                    "Record (30 days)": r.get("lean_record") or "—",
                    "Basis": "Tested rule" if tested else "Lean, 55%+ record"})
    out.sort(key=lambda x: (x["_t"], x["_tested"]))
    return [{k: v for k, v in x.items() if not k.startswith("_")} for x in out]


def summary(props: List[Dict], lines: List[Dict]) -> Dict:
    sports_ = sorted({r["Sport"] for r in props + lines if r.get("Sport")})
    return {"picks": len(props), "winning": sum(r["Standing"] == WINNING for r in props), "lines": len(lines),
            "sports": sports_}


def top_cards(rows: List[Dict], records_for: Optional[Callable] = None, n: int = 4) -> List[Dict]:
    """Nov 16: the day's strongest player picks across every sport, as cards for the top of Home: pick types with a
    winning 30-day record only, locks first, then the highest chance, one per player.
    [{sport, pick, chance, price, game, time, record, lock}]"""
    rows = [dict(r) for r in rows or [] if r.get("kind") == "Prop"]
    PR.annotate_props(rows, records_for or PR.tag_records)
    rows = [r for r in rows if standing(r.get("verdict")) == WINNING]
    rows.sort(key=lambda r: (0 if r.get("lock") else 1, -(r.get("chance") or 0)))
    out, seen = [], set()
    for r in rows:
        who = (r.get("sport"), r.get("player") or r.get("pick"))
        if who in seen:
            continue
        seen.add(who)
        out.append({"sport": r.get("sport"), "pick": r.get("pick"), "chance": r.get("chance"),
                    "price": _price(r.get("price")) + (f" · {r['book']}" if r.get("book") and r.get("price") is not None else ""),
                    "game": r.get("game") or "", "time": r.get("time") or "", "record": r.get("record") or "",
                    "lock": bool(r.get("lock")), "money": bool(r.get("money")), "move": r.get("move") or ""})
        if len(out) >= n:
            break
    return out
