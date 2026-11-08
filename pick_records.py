"""
pick_records.py — every kind of pick the platform shows, with its live record (Nov 8).

The owner's point: a number on the screen invites a bet whether or not it's labelled "tracking", so every pick type has
to carry its own record, and a type that's been losing shouldn't be presented as a pick until it earns its way back.
Records refresh as games are graded (the morning review), so this is the visible half of the daily feedback loop:

  tag_records(sport)        the Use tags (🔒 / 🎟️ / 🎯) over the last 30 days, from that sport's latest morning review
  lean_records(league)      the model's game leans by market -- spread, total, moneyline -- graded from the Game Lab
                            records (final scores vs the line the record carries), last 30 days
  verdict(w, n)             "losing" once there's enough of a record and it's under 50% (props: before the price even
                            counts) / under 47.6% for -110 game lines; "fade" when the other side has won 60%+
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Optional, Tuple

MIN_N = 20
DAYS = 30


def verdict(w: int, n: int, line_market: bool = False) -> str:
    if n < MIN_N:
        return "new"
    r = w / n
    if r <= 0.40:
        return "fade"
    if r < (0.476 if line_market else 0.50):
        return "losing"
    return "ok"


def label(w: int, n: int, line_market: bool = False) -> str:
    if not n:
        return "no record yet"
    v = verdict(w, n, line_market)
    tail = {"fade": f" · the other side won {n - w}–{w}", "losing": " · losing", "new": " · small sample"}.get(v, "")
    return f"{w}–{n - w} ({w / n:.0%}){tail}"


def tag_records(sport: str) -> Dict[str, Tuple[int, int]]:
    """{use tag: (hits, graded)} over the last 30 days, from the sport's latest morning review."""
    try:
        import model_store as MS
        for m in MS.daily_review_mornings(sport)[:3]:
            rep = MS.load_daily_review(sport, m) or {}
            use = (rep.get("trend") or {}).get("use")
            if use:
                return {u["Use"]: (int(u["Hits"]), int(u["Graded"])) for u in use}
    except Exception:                                           # noqa: BLE001
        pass
    return {}


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def grade_lean(rec: Dict) -> Dict[str, Optional[str]]:
    """{"Spread", "Total", "Moneyline": "win" / "loss" / "push" / None} for the model's lean on one graded game record."""
    fh, fa = _num(rec.get("final_home")), _num(rec.get("final_away"))
    out = {"Spread": None, "Total": None, "Moneyline": None}
    if fh is None or fa is None:
        return out
    mm = _num(rec.get("model_margin"))                          # model's home margin
    hs = _num(rec.get("home_spread") if rec.get("home_spread") is not None else rec.get("line"))
    if mm is not None and hs is not None and mm + hs != 0:
        home = mm + hs > 0                                      # the model's home side covers its own line
        v = (fh - fa) + hs
        out["Spread"] = "push" if v == 0 else ("win" if (v > 0) == home else "loss")
    mt = _num(rec.get("model_total"))
    lt = _num(rec.get("line_total") if rec.get("line_total") is not None else rec.get("close_total"))
    if mt is not None and lt is not None and mt != lt:
        v = (fh + fa) - lt
        out["Total"] = "push" if v == 0 else ("win" if (v > 0) == (mt > lt) else "loss")
    mp = _num(rec.get("model_p"))
    home_ml = (mp > 0.5) if mp is not None else ((mm > 0) if mm is not None else None)
    if home_ml is not None and fh != fa:
        out["Moneyline"] = "win" if (fh > fa) == home_ml else "loss"
    return out


def lean_records(league: str, days: int = DAYS, recs=None) -> Dict[str, Tuple[int, int]]:
    """{"Spread" / "Total" / "Moneyline": (wins, decided)} for the model's leans over the last `days` days."""
    if recs is None:
        try:
            import model_store as MS
            recs = MS.load_game_picks(league)
        except Exception:                                       # noqa: BLE001
            recs = []
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    out = {"Spread": [0, 0], "Total": [0, 0], "Moneyline": [0, 0]}
    for r in recs or []:
        if str(r.get("kickoff") or "")[:10] < cutoff:
            continue
        for mk, res in grade_lean(r).items():
            if res in ("win", "loss"):
                out[mk][0] += res == "win"
                out[mk][1] += 1
    return {k: (w, n) for k, (w, n) in out.items()}
