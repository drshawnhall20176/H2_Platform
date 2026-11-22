"""
show_picks.py — what the show talks about, by the platform's own rules (Nov 22).

Owner, Nov 22: yes to overhauling the Media Room and Podcast Studio. Both pages picked their selections with their own
older logic (model conviction or raw EV), so a show could headline a play the Command Center was telling members to
skip -- a ⚪ No edge read, a market the automatic shut-off had pulled -- and open with "the board" graded as a whole
instead of the picks the platform actually showed. On air that contradicts the record. So:

  * platform_plays -- only the plays the platform stands behind (the same filter as Today's best and the strongest
    list: a playable Use tag, 🔒 or 💰, never a ⚪ No edge unless 💰), each carrying its EARNED chance (shown as the
    chance, the model's own kept as RawProb) and its earned edge (earned chance less what the price needs), which is
    what the show ranks by -- the strongest list's own order;
  * ledger_review -- yesterday's picks AS SHOWN for one sport (strongest list, 💰 props, 💰 game lines), graded, with
    how many beat the closing line;
  * running_record -- the same since the current record began (investor.ERA).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence

RANK = "EarnedEdge"


def platform_plays(sport: str, plays: Sequence[Dict]) -> List[Dict]:
    import props_engine as PE
    import props_money as PM
    import todays_best as TB
    out = []
    tagged = any("Use" in p for p in plays or [])           # a board without Use tags (no priced read) isn't filtered
    for p in plays or []:
        try:
            money = bool(PE.play_is_money(sport, p))
        except Exception:                                       # noqa: BLE001
            money = False
        try:
            lock = bool(PE.play_is_lock(p))
            if lock:
                import shutoff as SO
                lock = not SO.is_off(sport, p.get("Market"), "lock")
        except Exception:                                       # noqa: BLE001
            lock = False
        use = p.get("Use")
        if tagged and use not in TB.PLAYABLE and not lock and not money:
            continue
        if tagged and use == PE.USE_PASS and not money:
            continue
        try:
            earned = PM.play_earned(sport, p)
        except Exception:                                       # noqa: BLE001
            earned = None
        pickem = bool(p.get("Pickem")) or p.get("RealPrice") is None
        need = PM.needed(p.get("RealPrice"), pickem)
        q = dict(p, RawProb=p.get("ModelProb"), Earned=earned, Money=money, Lock=lock,
                 EarnedEdge=(earned - need) if earned is not None and need is not None else None)
        if earned is not None:
            q["ModelProb"] = earned                             # the chance the show quotes is the honest one
        out.append(q)
    return out


def tag(p: Dict) -> str:
    """"💰 " / "🔒 " / "" for a show line."""
    return "💰 " if p.get("Money") else "🔒 " if p.get("Lock") else ""


def _sport_rows(day: str, sport: str, get=None) -> List[Dict]:
    """The sport's shown picks of `day`, once each (a pick on two lists counts once)."""
    import pick_ledger as PL
    seen, out = set(), []
    for kind, sp in (("strong", "ALL"), ("money", sport), ("games", sport)):
        for k, r in (PL.load(kind, sp, day, get)["rows"] or {}).items():
            if (r.get("sport") or r.get("league") or sp) != sport or k in seen:
                continue
            seen.add(k)
            out.append(r)
    return out


def _sum(rows: Sequence[Dict]) -> Dict:
    import props_engine as PE
    w = [r for r in rows if r.get("result") == "win"]
    l_ = [r for r in rows if r.get("result") == "loss"]
    units = 0.0
    for r in w + l_:
        d = PE.decimal(r.get("price")) if r.get("price") is not None else None
        if d:
            units += (d - 1) if r in w else -1.0
    return {"hits": len(w), "misses": len(l_), "units": units,
            "beat": sum(r.get("clv_mark") == "beat" for r in rows),
            "lost": sum(r.get("clv_mark") == "lost" for r in rows),
            "wins": w, "losses": l_, "open": sum(r.get("result") not in ("win", "loss", "push", "void") for r in rows)}


def ledger_review(sport: str, day: str, get=None) -> Optional[Dict]:
    """Yesterday's shown picks for one sport, graded; None when nothing was shown or graded."""
    rows = _sport_rows(day, sport, get)
    if not rows:
        return None
    s = _sum(rows)
    return s if s["hits"] + s["misses"] else None


def running_record(sport: str, end: str, get=None) -> Optional[Dict]:
    """The sport's shown picks since the current record began (investor.ERA), through `end`."""
    import investor as I
    d0, d1 = date.fromisoformat(I.ERA), date.fromisoformat(end)
    rows = []
    while d0 <= d1:
        rows += _sport_rows(d0.isoformat(), sport, get)
        d0 += timedelta(days=1)
    s = _sum(rows)
    return dict(s, since=I.ERA) if s["hits"] + s["misses"] else None


def record_line(r: Optional[Dict], label: str) -> str:
    """"Yesterday: 7–5, +1.40u at the prices shown; beat the close on 6 of 9 that moved." """
    if not r:
        return ""
    moved = r["beat"] + r["lost"]
    return (f"{label}: {r['hits']}–{r['misses']}, {r['units']:+.2f}u at the prices shown"
            + (f"; beat the closing line on {r['beat']} of {moved} that moved" if moved else "") + ".")


def pick_name(r: Dict) -> str:
    return str(r.get("pick") or f"{r.get('player')} {r.get('market')} {r.get('side')} {r.get('line')}")
