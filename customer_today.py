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
import props_engine as PE

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
        out.append({"sport": r.get("sport"), "pick": r.get("pick"), "chance": r.get("chance"), "_inj": r.get("_inj"), "edge": r.get("edge"),
                    "price": _price(r.get("price")) + (f" · {r['book']}" if r.get("book") and r.get("price") is not None
                                                       else ""),
                    "game": r.get("game") or "", "time": r.get("time") or "", "lock": bool(r.get("lock")),
                    "stake": PE.stake_units(r.get("chance"), r.get("price"))})
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
    return [{"Time": r.get("time") or "", "Sport": r.get("sport"), "Pick": _q(r),
             "Chance": r.get("chance"),
             "Best price": _price(r.get("price")) + (f" · {r['book']}" if r.get("book") and r.get("price") is not None else ""),
             "Record (30 days)": r.get("record") or "—", "Standing": st, "Game": r.get("game") or ""}
            for r, st in keep]


def _q(r: Dict) -> str:
    """Nov 25: a pick on a player now listed questionable says so (injury_check.screen tags the row)."""
    return f"{r.get('pick')} ⚠️ questionable" if r.get("_inj") == "questionable" else r.get("pick")


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
                    "price": _price(r.get("price")) + (f" · {_book_name(r['book'])}" if r.get("book") and r.get("price") is not None else ""),
                    "game": r.get("game") or "", "time": r.get("time") or "", "record": r.get("record") or "",
                    "lock": bool(r.get("lock")), "money": bool(r.get("money")), "move": r.get("move") or ""})
        if len(out) >= n:
            break
    return out


def has_games(key: str, day: str):
    """Nov 25 (owner: on Today, sport buttons only for sports with games that day): True / False from the sport's own
    schedule; None when it couldn't be read (the sport then stays on the bar rather than vanish on a feed hiccup)."""
    import sports
    from datetime import datetime as _dt
    try:
        if key in sports.LAB_SPORTS:
            import lab_schedule as LS
            return bool(LS.rows(key, LS.load(key), _dt.strptime(day, "%Y-%m-%d").date()))
        if key == "UFC":                                        # Nov 25: fight days only (the free events list)
            import ufc_engine as UE
            k = odds_key()
            return None if not k else day in UE.card_dates(k)
        if key == "NFL":                                        # Nov 25: its schedule is the whole season
            import nfl_engine as NE
            d = _dt.strptime(day, "%Y-%m-%d").date()
            season = d.year if d.month >= 3 else d.year - 1
            return any(str(g.get("game_date") or "")[:10] == day for g in NE.get_schedule(season) or [])
        return bool(sports.get(key).engine.get_schedule(day))
    except Exception:                                           # noqa: BLE001
        return None


def has_games_many(keys, day: str, workers: int = 8) -> Dict[str, Optional[bool]]:
    """has_games for several sports at once -- each sport's feed is its own wait (NBA's stats feed can hang for its
    full timeout), so they run side by side. A sport whose check fails gets None (it stays on the bar)."""
    keys = list(keys or [])
    if not keys:
        return {}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(workers, len(keys))) as ex:
        futs = {k: ex.submit(has_games, k, day) for k in keys}
        out = {}
        for k, f in futs.items():
            try:
                out[k] = f.result(timeout=20)
            except Exception:                                   # noqa: BLE001
                out[k] = None
        return out


def odds_key():
    import os
    try:
        import streamlit as st
        k = st.secrets.get("ODDS_API_KEY")
    except Exception:                                           # noqa: BLE001
        k = None
    return k or os.environ.get("ODDS_API_KEY")


def _book_name(k) -> str:
    """Nov 25: "draftkings" -> "DraftKings" on the cards."""
    try:
        import odds_api as O
        return O.book_label(k)
    except Exception:                                           # noqa: BLE001
        return str(k)


def empty_reason(off: List[str], with_reads: Dict[str, int], when: str = "today") -> str:
    """Nov 26 (owner): why Today has no player picks, in one plain line -- never a silent 0 that looks like a failure.
    `off`: in-season prop sports with no games on the day; `with_reads`: {sport: props the model read}."""
    bits = []
    if off:
        bits.append(f"{_join(off)} {'has' if len(off) == 1 else 'have'} no games {when}")
    if with_reads:
        n = sum(with_reads.values())
        bits.append(f"the model read {n:,} {_join(sorted(with_reads))} prop{'s' if n != 1 else ''}, and none earned a "
                    "bet — they're tracking only")
    if not bits:
        return f"No pick clears the bar {when}, and the boards haven't been built yet — they fill through the day."
    return (f"No pick clears the bar {when}: " + "; ".join(bits) + ". Every read is on the game cards (Game Labs) and "
            "in the Test list.")


def _join(xs: List[str]) -> str:
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]
