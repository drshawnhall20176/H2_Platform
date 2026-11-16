"""
model_record.py — the customer proof page's numbers (Nov 16): the MODEL's own graded record, nothing from the Bet Log.

Two tables, both over the last 30 days and both read from records the platform already keeps (pick_records.py):
  props_table   each sport's prop picks by Use tag, from that sport's latest morning review
  lines_table   each league's game-line leans (spread / total / moneyline), graded from the Game Lab records

Every row carries its sample size and the 90% range around the hit rate; a small sample or a losing record says so.
A hit rate is before the price: above 50% is not by itself a profit (a -110 line needs 52.4%).
"""
from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional

import pick_records as PR

STATUS = {"new": "Small sample", "ok": "Holding up", "losing": "Losing", "fade": "Losing badly"}
LINE_MARKETS = ("Spread", "Total", "Moneyline")
LINE_LEAGUES = ("NFL", "NCAAF", "NBA", "NCAAMB", "NHL")      # the Game Labs; a league with no graded leans adds no rows
BREAK_EVEN_110 = 0.524


def row(sport: str, kind: str, w: int, n: int, line_market: bool = False) -> Dict:
    return {"Sport": sport, "Pick type": kind, "Record": f"{w}–{n - w}", "Graded": n,
            "Hit rate": round(w / n, 3) if n else None,
            "90% range (±)": round(PR.margin(w, n), 3) if n else None,
            "Status": STATUS[PR.verdict(w, n, line_market)]}


def props_table(sport_keys: Iterable[str], records_for: Optional[Callable] = None) -> List[Dict]:
    records_for = records_for or PR.tag_records
    out: List[Dict] = []
    for sp in sport_keys:
        try:
            recs = records_for(sp) or {}
        except Exception:                                       # noqa: BLE001
            recs = {}
        for tag, (w, n) in recs.items():
            if n:
                out.append(row(sp, str(tag), int(w), int(n)))
    return out


def lines_table(leagues: Iterable[str], records_for: Optional[Callable] = None) -> List[Dict]:
    records_for = records_for or PR.lean_records
    out: List[Dict] = []
    for lg in leagues:
        try:
            recs = records_for(lg) or {}
        except Exception:                                       # noqa: BLE001
            recs = {}
        for mk in LINE_MARKETS:
            w, n = recs.get(mk) or (0, 0)
            if n:
                out.append(row(lg, mk, int(w), int(n), line_market=True))
    return out
