"""
report_card.py — the public report card (Nov 20): 30 days of 💰 Money picks and 🔒 Most probable picks, graded AT THE
PRICE they showed, by sport -- won-lost, hit rate against what the prices needed, return per $1, and how often the
market moved toward the pick before the game (closing-line value).

Owner: build the "public report card" from the weekend audit -- the record no competitor publishes. Reads the stored
morning reviews only (daily_review.py's per-slate "money" and "most_probable" records): no Odds API credits, no box
scores. Each slate counts once, from the latest morning that graded it. Picks are as they were flagged at the time:
when a rule changed (💰 on Nov 20, 🔒's price check on Nov 20), earlier slates keep the rule they were shown under.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Dict, List, Optional, Sequence

DAYS = 30


def slates(sport: str, load: Callable, today: str, days: int = DAYS) -> Dict[str, Dict]:
    """{slate date: its summary} over the last `days` slates, each from the latest morning review that has it."""
    t = date.fromisoformat(today)
    out: Dict[str, Dict] = {}
    for k in range(days + 4, 0, -1):                          # oldest morning first: later mornings overwrite
        morning = (t - timedelta(days=k - 1)).isoformat()
        try:
            rev = load(sport, morning) or {}
        except Exception:                                       # noqa: BLE001
            continue
        for d, s in (rev.get("slates") or {}).items():
            if (t - date.fromisoformat(d)).days <= days:
                out[d] = s
    return out


def _add(acc: Dict, rec: Dict, kind: str) -> None:
    h, m = rec.get("hits") or 0, rec.get("misses") or 0
    n = h + m
    if not n:
        return
    acc["hits"] += h
    acc["misses"] += m
    if rec.get("profit") is not None:
        acc["units"] += rec["profit"] * (rec.get("priced") or n if kind == "lock" else n)
        acc["priced"] += (rec.get("priced") or n) if kind == "lock" else n
    if rec.get("needed") is not None:
        acc["need_sum"] += rec["needed"] * n
        acc["need_n"] += n
    acc["clv_beat"] += rec.get("clv_beat") or 0
    acc["clv_lost"] += rec.get("clv_lost") or 0


def card(sports_: Sequence[str], load: Optional[Callable] = None, today: Optional[str] = None,
         days: int = DAYS, ledger: Optional[Callable] = None) -> List[Dict]:
    """[{sport, kind ("money" / "lock"), hits, misses, hit_rate, needed, units, roi, clv, clv_n}] for every sport and
    kind with at least one graded pick."""
    import props_engine as PE
    if load is None:
        import model_store as MS
        import pick_ledger as PL
        load = MS.load_daily_review
        if ledger is None:
            ledger = lambda sp, d: PL.record("money", sp, d)      # noqa: E731
    today = today or PE._et_today()
    out = []
    for sp in sports_:
        ss = slates(sp, load, today, days)
        for kind, field in (("money", "money"), ("lock", "most_probable")):
            acc = {"hits": 0, "misses": 0, "units": 0.0, "priced": 0, "need_sum": 0.0, "need_n": 0, "clv_beat": 0,
                   "clv_lost": 0}
            for d, s in ss.items():
                rec = s.get(field) or {}
                if kind == "money" and ledger is not None:      # Nov 21: the 💰 picks as shown (pick_ledger.py)
                    led = ledger(sp, d)
                    if led:
                        rec = {"hits": led["hits"], "misses": led["misses"], "needed": led["needed"],
                               "profit": led["units"] / led["n"] if led["priced"] == led["n"] else None}
                _add(acc, rec, kind)
            n = acc["hits"] + acc["misses"]
            if not n:
                continue
            c = acc["clv_beat"] + acc["clv_lost"]
            out.append({"sport": sp, "kind": kind, "hits": acc["hits"], "misses": acc["misses"],
                        "hit_rate": acc["hits"] / n,
                        "needed": acc["need_sum"] / acc["need_n"] if acc["need_n"] else None,
                        "units": acc["units"] if acc["priced"] else None,
                        "roi": acc["units"] / acc["priced"] if acc["priced"] else None,
                        "clv": acc["clv_beat"] / c if c else None, "clv_n": c})
    return out


def table(rows: Sequence[Dict]) -> List[Dict]:
    import sports as S
    name = {"money": "💰 Money picks", "lock": "🔒 Most probable"}
    out = []
    for r in sorted(rows, key=lambda r: (r["kind"] != "money", r["sport"])):
        try:
            sp = f"{S.get(r['sport']).icon} {S.get(r['sport']).label.split(' — ')[0]}"
        except Exception:                                       # noqa: BLE001
            sp = r["sport"]
        out.append({"Picks": name[r["kind"]], "Sport": sp, "Record": f"{r['hits']}–{r['misses']}",
                    "Hit rate": f"{r['hit_rate']:.0%}",
                    "Needed": f"{r['needed']:.0%}" if r.get("needed") is not None else "—",
                    "Return per $1": f"{r['roi']:+.1%}" if r.get("roi") is not None else "—",
                    "Units ($1 a pick)": f"{r['units']:+.2f}" if r.get("units") is not None else "—",
                    "Beat the close": f"{r['clv']:.0%} of {r['clv_n']}" if r.get("clv") is not None else "—"})
    return out
