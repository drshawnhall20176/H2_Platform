"""
money_scoreboard.py — the 💰 live test's running record, sport by sport (Nov 20).

Owner: "I really want to capture money picks ... run that concept live this weekend to see how it does across sports."
Every morning the daily review grades the night's 💰 picks (postgame.money_record over every saved read that met the
rule, at the price it carried) and stores the slate's record. This adds those records up over the test's slates
(props_engine.MONEY_TEST), per sport and in total: won–lost, hit rate against what the prices needed, and profit in
units of $1 per pick. No Odds API credits: it reads the saved reviews only.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Dict, List, Optional

import props_engine as PE

CATCH_UP = 4          # a slate's record can be finished on a later morning (late games, stat corrections)


def _days(a: str, b: str) -> List[str]:
    d0, d1 = date.fromisoformat(a), date.fromisoformat(b)
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def slate_record(sport: str, slate: str, load: Callable, today: Optional[str] = None) -> Optional[Dict]:
    """The latest stored 💰 record of one slate: {"hits", "misses", "units", "needed"} or None (not graded yet)."""
    best = None
    d = date.fromisoformat(slate)
    for k in range(1, CATCH_UP + 1):
        morning = (d + timedelta(days=k)).isoformat()
        if today and morning > today:
            break
        try:
            rev = load(sport, morning) or {}
        except Exception:                                       # noqa: BLE001
            continue
        mo = ((rev.get("slates") or {}).get(slate) or {}).get("money") or {}
        n = (mo.get("hits") or 0) + (mo.get("misses") or 0)
        if n:
            best = {"hits": mo["hits"], "misses": mo["misses"],
                    "units": (mo.get("profit") or 0.0) * n, "needed": mo.get("needed")}
    return best


def scoreboard(load: Optional[Callable] = None, today: Optional[str] = None, test: Optional[Dict] = None) -> Dict:
    """{"sports": [{sport, hits, misses, units, roi, hit_rate, needed, slates}], "total": {...}, "from", "to"}."""
    if load is None:
        import model_store as MS
        load = MS.load_daily_review
    test = test or PE.MONEY_TEST
    today = today or PE._et_today()
    last = min(test["to"], (date.fromisoformat(today) - timedelta(days=1)).isoformat())
    out, tot = [], {"hits": 0, "misses": 0, "units": 0.0, "need_sum": 0.0}
    for sp in test["sports"]:
        row = {"sport": sp, "hits": 0, "misses": 0, "units": 0.0, "need_sum": 0.0, "slates": 0}
        if test["from"] <= last:
            for d in _days(test["from"], last):
                r = slate_record(sp, d, load, today)
                if not r:
                    continue
                n = r["hits"] + r["misses"]
                row["hits"] += r["hits"]
                row["misses"] += r["misses"]
                row["units"] += r["units"]
                row["need_sum"] += (r["needed"] or 0) * n
                row["slates"] += 1
        out.append(row)
        for k in ("hits", "misses", "units", "need_sum"):
            tot[k] += row[k]
    for r in out + [tot]:
        n = r["hits"] + r["misses"]
        r["n"] = n
        r["hit_rate"] = r["hits"] / n if n else None
        r["needed"] = r["need_sum"] / n if n else None
        r["roi"] = r["units"] / n if n else None
    return {"sports": out, "total": tot, "from": test["from"], "to": test["to"]}


def table(board: Dict, live: Optional[Dict[str, int]] = None) -> List[Dict]:
    """Rows for the page: sport, record, hit rate vs needed, units, today's live 💰 picks."""
    import sports as S
    rows = []
    for r in board["sports"]:
        try:
            name = f"{S.get(r['sport']).icon} {S.get(r['sport']).label.split(' — ')[0]}"
        except Exception:                                       # noqa: BLE001
            name = r["sport"]
        rows.append({"Sport": name,
                     "Record": f"{r['hits']}–{r['misses']}" if r["n"] else "—",
                     "Hit rate": r["hit_rate"], "Needed": r["needed"],
                     "Units ($1 a pick)": round(r["units"], 2) if r["n"] else None,
                     "Per $1": r["roi"],
                     "Today": (live or {}).get(r["sport"], 0)})
    return rows
