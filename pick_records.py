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
    hs = _num(rec.get("home_spread"))                          # the home team's spread (-7.5 = home favored)
    if hs is None and _num(rec.get("line")) is not None:        # Game Lab records keep the home's expected margin
        hs = -_num(rec.get("line"))
    if mm is not None and hs is not None and mm + hs != 0:
        home = mm + hs > 0                                      # the model's home side covers its own line
        v = (fh - fa) + hs
        out["Spread"] = "push" if v == 0 else ("win" if (v > 0) == home else "loss")
    if str(rec.get("result") or "").lower() in ("win", "loss", "push") and rec.get("pick"):
        out["Spread"] = str(rec["result"]).lower()              # the record's own grading of its posted pick wins
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


HIDE = ("losing", "fade")


def _strip(use: str) -> str:
    return str(use or "").replace("🔒", "").strip()


def annotate_props(rows, records_for=tag_records) -> None:
    """Adds "record" (label) and "verdict" to each Today's best pick row from its sport's Use-tag record."""
    cache: Dict[str, Dict] = {}
    for r in rows or []:
        sp = r.get("sport")
        if sp not in cache:
            cache[sp] = records_for(sp) or {}
        w, n = cache[sp].get(_strip(r.get("use")), (0, 0))
        line_mk = r.get("kind") not in (None, "Prop")
        r["record"] = label(w, n, line_mk) if n else ""
        r["verdict"] = verdict(w, n, line_mk) if n else "new"


def annotate_leans(rows, records_for=lean_records) -> None:
    """Adds "lean_record" / "lean_verdict" to each game-line row from its league's record in that row's market."""
    cache: Dict[str, Dict] = {}
    for r in rows or []:
        lg = (r.get("_rec") or {}).get("sport") or r.get("sport")
        mk = r.get("bet_market")
        if not mk:
            r["lean_record"], r["lean_verdict"] = "", "new"
            continue
        if lg not in cache:
            cache[lg] = records_for(lg) or {}
        w, n = cache[lg].get(mk, (0, 0))
        r["lean_record"] = f"{mk}: " + label(w, n, mk != "Moneyline") if n else ""
        r["lean_verdict"] = verdict(w, n, mk != "Moneyline") if n else "new"


BANDS = ("Model 60%+", "Model 55–60%", "Model 50–55%", "Against the model (<50%)", "No model read")


def band_of(mp) -> str:
    mp = _num(mp)
    if mp is None:
        return BANDS[4]
    return BANDS[0] if mp >= 0.60 else BANDS[1] if mp >= 0.55 else BANDS[2] if mp >= 0.50 else BANDS[3]


def your_picks(bets) -> list:
    """Your real, graded bets by how strongly the model agreed: [{"Bets", "Band", "Record", "Win %", "Staked", "P/L"}].
    Singles and parlay legs are graded on their own; parlays get one row (the band is the weakest leg's)."""
    cell: Dict[Tuple[str, str], list] = {}
    for b in bets or []:
        if not b.get("is_real_bet") or b.get("result") not in ("win", "loss"):
            continue
        kind = "Parlay" if b.get("market") == "Parlay" else ("Parlay leg" if b.get("ticket") else "Single")
        c = cell.setdefault((kind, "All" if kind == "Parlay" else band_of(b.get("model_prob"))), [0, 0, 0.0, 0.0])
        c[0] += b["result"] == "win"
        c[1] += 1
        if kind == "Parlay leg":
            continue                                            # a leg's money is the parlay's
        stake = _num(b.get("stake")) or 0.0
        o = _num(b.get("entry_odds"))
        dec = 1.909 if o is None or o == 0 else 1 + (o / 100 if o > 0 else 100 / -o)
        c[2] += stake
        c[3] += stake * (dec - 1) if b["result"] == "win" else -stake
    order = {k: i for i, k in enumerate(BANDS + ("All",))}
    kinds = {"Single": 0, "Parlay leg": 1, "Parlay": 2}
    out = []
    for (kind, band), (w, n, st, pl) in sorted(cell.items(), key=lambda kv: (kinds[kv[0][0]], order[kv[0][1]])):
        out.append({"Bets": kind, "Band": band, "Record": f"{w}–{n - w}", "Win %": w / n,
                    "Staked": None if kind == "Parlay leg" else round(st, 2),
                    "P/L": None if kind == "Parlay leg" else round(pl, 2)})
    return out
