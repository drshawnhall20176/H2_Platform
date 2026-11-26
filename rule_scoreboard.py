"""
rule_scoreboard.py -- every rule's forward record, trend and distance to its next gate (Nov 26).

Owner, Nov 26 (approving the H2 Rulebook): "I need some kind of trend metrics to go along with this so I can track as
I go." The Rulebook's lifecycle: Candidate -> Paper -> Live test -> Proven, with Gate 1 (Paper -> Live test: 100+ picks
over 10+ slate days -- 4+ game weeks in the weekly sports -- at +2% per $1, both halves at or above break-even, the
close moving toward the pick 50%+ of the time) and Gate 2 (Live test -> Proven: 300+ picks over 10+ slate days -- 6+
weeks -- at +2%, the low end of the 90% range above zero, both halves making money, the close 50%+). Close gap keeps
the gate it was given on Nov 23 (200 games at 55%+).

Scored from what the platform already grades, at the prices the picks carried:
  * 💰 Money props, every props sport, live or paper -- graded pre-game reads in the 💰 band
    (props_engine.snapshot_in_band: the rule itself, whether or not 💰 is switched on);
  * 🔒 Most probable, every props sport -- graded reads props_engine.is_lock flags;
  * the prop Under rules (candidate_rules.PROP_RULES), from their start dates;
  * 💰 Money Score game lines -- past winner_rows in the band (money_score.row_in_band), paused or not;
  * 🧪 Close gap -- its own ledger (pick_ledger kind "cand").
The last WINDOW days (the shut-off's window), saved compactly under KEY for the Rule scoreboard page. Prints counts only
(the job logs are public).
"""
from __future__ import annotations

import math
import random
import sys
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence

KEY = "rules:scoreboard"
WINDOW = 60
SPORTS = ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB")
WEEKLY = ("NFL", "NCAAF")
GATE1 = {"n": 100, "days": 10, "weeks": 4, "roi": 0.02}
GATE2 = {"n": 300, "days": 10, "weeks": 6, "roi": 0.02}
CLOSE_GAP_GATE = {"n": 200, "hit": 0.55}
MIN_BEAT = 0.50
LABELS = {"money_props": "💰 Money props", "lock": "🔒 Most probable", "money_games": "💰 Money Score game lines",
          "close_gap": "🧪 Close gap", "nfl_under_vs_fav": "🧪 NFL Under vs the favorite",
          "ncaaf_under": "🧪 College football Under", "ncaaf_under_same": "🧪 College football Under, model & market agree"}


def _dec(price) -> Optional[float]:
    try:
        a = float(price)
    except (TypeError, ValueError):
        return None
    if -100 < a < 100:
        return None
    return 1 + (a / 100 if a > 0 else 100 / -a)


def _p(day: str, hit: bool, price, clv: Optional[str] = None) -> List:
    """One graded pick, compact: [day, 1/0, decimal price, close mark b/l/s/None]."""
    d = _dec(price) or _dec(-110)
    return [str(day)[:10], 1 if hit else 0, round(d, 4), {"beat": "b", "lost": "l", "same": "s"}.get(clv or "")]


# --------------------------------------------------------------------------- collecting
def from_graded(sport: str, graded: Sequence[Dict]) -> Dict[str, List]:
    """{rule key: [picks]} from one sport's graded prop reads: 💰 band, 🔒, and its prop Under rules."""
    import props_engine as PE
    out: Dict[str, List] = {}
    try:
        import candidate_rules as CR
        prop_rules = {k: v for k, v in CR.PROP_RULES.items() if v["sport"] == sport}
    except Exception:                                           # noqa: BLE001
        CR, prop_rules = None, {}
    for r in graded:
        day = str(r.get("slate_date") or "")[:10]
        if r.get("result") in ("hit", "miss") and r.get("price") is not None:
            hit = r["result"] == "hit"
            try:
                import clv as CLV
                mark = CLV.pick_clv(r)
            except Exception:                                   # noqa: BLE001
                mark = None
            try:
                if PE.snapshot_in_band(sport, r):
                    out.setdefault(f"money_props|{sport}", []).append(_p(day, hit, r["price"], mark))
                if PE.is_lock(r.get("chance"), r.get("cushion"), r.get("gap"), r.get("book"), ev=r.get("ev")):
                    out.setdefault(f"lock|{sport}", []).append(_p(day, hit, r["price"], mark))
            except Exception:                                   # noqa: BLE001
                pass
        for rule, cfg in prop_rules.items():
            if day < cfg["from"] or r.get("actual") is None or r.get("line") is None:
                continue
            try:
                if not CR.prop_qualifies(rule, r):
                    continue
                thr = PE.threshold(float(r["line"]))
                if r["actual"] == thr:
                    continue
                out.setdefault(f"{rule}|{sport}", []).append(_p(day, r["actual"] < thr, r.get("under_price")))
            except Exception:                                   # noqa: BLE001
                continue
    return out


def from_games(rows: Sequence[Dict]) -> Dict[str, List]:
    """{"money_games|<sport>": [picks]} -- the Money Score rule on past game lines, paused or not."""
    import money_score as MSC
    out: Dict[str, List] = {}
    for r in rows:
        if not (r.get("money") or MSC.row_in_band(r)) or r.get("money_result") not in ("win", "loss"):
            continue
        out.setdefault(f"money_games|{r.get('sport')}", []).append(
            _p(r.get("_day") or "", r["money_result"] == "win", r.get("money_price")))
    return out


def from_close_gap(start: str, end: str, get=None) -> List:
    import picks_performance as PP
    out = []
    for p in PP.ledger_picks("cand", ("NCAAMB",), start, end, get):
        if p["result"] in ("win", "loss"):
            out.append([p["day"], 1 if p["result"] == "win" else 0, round(p.get("dec") or _dec(-110), 4), None])
    return out


# --------------------------------------------------------------------------- metrics
def _roi(ps: Sequence[List]) -> Optional[float]:
    return (sum((p[2] - 1) if p[1] else -1.0 for p in ps) / len(ps)) if ps else None


def metrics(picks: Sequence[List], weekly: bool = False, today: Optional[str] = None, seed: int = 1) -> Dict:
    """The record and its trend: n, hit rate, the rate the prices needed, units, return per $1, its 90% range (whole
    slate days resampled), the two halves, the last 7 and 30 days, and the close."""
    ps = sorted(picks, key=lambda p: p[0])
    n = len(ps)
    if not n:
        return {"n": 0}
    days = sorted({p[0] for p in ps})
    units = sum((p[2] - 1) if p[1] else -1.0 for p in ps)
    half = n // 2
    byd = {d: [p for p in ps if p[0] == d] for d in days}
    rng = random.Random(seed)
    boots = sorted(_roi([p for d in rng.choices(days, k=len(days)) for p in byd[d]]) for _ in range(500))
    lo, hi = boots[25], boots[474]
    today = today or days[-1]
    t = date.fromisoformat(today)
    last = lambda k: [p for p in ps if p[0] > (t - timedelta(days=k)).isoformat()]      # noqa: E731
    moved = [p[3] for p in ps if p[3] in ("b", "l")]
    weeks = len({date.fromisoformat(d).isocalendar()[:2] for d in days})
    return {"n": n, "wins": sum(p[1] for p in ps), "hit": sum(p[1] for p in ps) / n,
            "needed": sum(1 / p[2] for p in ps) / n, "units": units, "roi": units / n, "lo": lo, "hi": hi,
            "h1": _roi(ps[:half]), "h2": _roi(ps[half:]), "days": len(days), "weeks": weeks, "weekly": weekly,
            "roi7": _roi(last(7)), "n7": len(last(7)), "roi30": _roi(last(30)), "n30": len(last(30)),
            "beat": (moved.count("b") / len(moved)) if moved else None, "moved": len(moved),
            "first": days[0], "last": days[-1]}


def gate(m: Dict, which: Dict) -> Dict:
    """Each check of a gate: {name: (passed, shown)}. The close counts as passed while too few picks have moved."""
    if not m.get("n"):
        return {"Sample": (False, "no graded picks yet")}
    span_ok = m["weeks"] >= which["weeks"] if m.get("weekly") else m["days"] >= which["days"]
    span = f"{m['weeks']} of {which['weeks']} weeks" if m.get("weekly") else f"{m['days']} of {which['days']} days"
    checks = {"Sample": (m["n"] >= which["n"] and span_ok, f"{m['n']} of {which['n']} picks · {span}"),
              "Return": (m["roi"] >= which["roi"], f"{m['roi']:+.1%} per $1 (needs {which['roi']:+.0%})")}
    if which is GATE2:
        checks["Not luck"] = (m["lo"] > 0 and (m["h1"] or 0) > 0 and (m["h2"] or 0) > 0,
                              f"90% low {m['lo']:+.1%} · halves {m['h1']:+.1%} / {m['h2']:+.1%}")
    else:
        need = m["needed"]
        checks["Not luck"] = ((m["h1"] or 0) >= 0 and (m["h2"] or 0) >= 0,
                              f"halves {m['h1']:+.1%} / {m['h2']:+.1%} (break-even {need:.1%})")
    if m.get("moved", 0) >= 30:
        checks["Market agrees"] = (m["beat"] >= MIN_BEAT, f"close moved toward the pick {m['beat']:.0%} of {m['moved']}")
    else:
        checks["Market agrees"] = (True, f"only {m.get('moved', 0)} closes moved yet")
    return checks


def close_gap_gate(m: Dict) -> Dict:
    if not m.get("n"):
        return {"Sample": (False, "no graded games yet")}
    g = CLOSE_GAP_GATE
    return {"Sample": (m["n"] >= g["n"], f"{m['n']} of {g['n']} games"),
            "Hit rate": (m["hit"] >= g["hit"], f"{m['hit']:.1%} (needs {g['hit']:.0%})")}


def health(m: Dict) -> str:
    """The Rulebook's watch / pause lines on the record (display only -- the shut-off acts on them)."""
    if not m.get("n"):
        return ""
    sd_hi = m.get("hi")
    if m["n"] >= 150 and sd_hi is not None and sd_hi < 0:
        return "⛔ Pause line: losing even at the top of its range"
    if m.get("moved", 0) >= 100 and m.get("beat") is not None and m["beat"] < 0.45:
        return "⛔ Pause line: the close keeps moving against it"
    if m["n"] >= 75 and m["roi"] < -0.05:
        return "⚠️ Watch: below −5% per $1"
    return ""


# --------------------------------------------------------------------------- stage
def stage(rule: str, sport: str, today: str) -> str:
    """Where the rule sits today, from the switches the platform runs on."""
    import props_engine as PE
    if rule == "money_props":
        return "Live test" if sport in PE.money_sports(day=today) else "Paper"
    if rule == "lock":
        return "Live test"
    if rule == "money_games":
        import money_score as MSC
        p = MSC.PAUSED.get(sport)
        return "Paused" if p and today >= p else "Live test"
    return "Paper"


def build(graded_by: Dict[str, Sequence[Dict]], games: Sequence[Dict], today: str, get=None,
          close_gap: Optional[List] = None) -> Dict:
    """Every rule's picks and metrics for the page."""
    picks: Dict[str, List] = {}
    for sp, graded in (graded_by or {}).items():
        for k, v in from_graded(sp, graded).items():
            picks.setdefault(k, []).extend(v)
    for k, v in from_games(games or []).items():
        picks.setdefault(k, []).extend(v)
    end = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    try:
        cg = close_gap if close_gap is not None else from_close_gap("2026-11-23", end, get)
    except Exception:                                           # noqa: BLE001
        cg = []
    picks["close_gap|NCAAMB"] = cg
    rules = []
    for key, ps in sorted(picks.items()):
        rule, sp = key.split("|", 1)
        m = metrics(ps, weekly=sp in WEEKLY, today=today)
        st_ = stage(rule, sp, today)
        nxt = ("Close gap's gate" if rule == "close_gap" else
               "Gate 2" if st_ == "Live test" else "Return (Gate 2)" if st_ == "Paused" else "Gate 1")
        checks = close_gap_gate(m) if rule == "close_gap" else gate(m, GATE2 if st_ in ("Live test", "Paused") else GATE1)
        rules.append({"key": key, "rule": rule, "sport": sp, "label": LABELS.get(rule, rule), "stage": st_,
                      "next": nxt, "checks": {k: list(v) for k, v in checks.items()},
                      "ready": all(v[0] for v in checks.values()), "health": health(m), "m": m,
                      "picks": sorted(ps, key=lambda p: p[0])})
    return {"day": today, "window": WINDOW, "rules": rules}


def save(rec: Dict, save_fn=None) -> None:
    from datetime import datetime, timezone
    import model_store as MS
    (save_fn or MS.save_setting)(KEY, dict(rec, at=datetime.now(timezone.utc).isoformat(timespec="seconds")))


def load(get=None) -> Optional[Dict]:
    import model_store as MS
    return (get or MS.get_setting)(KEY, None)


def run(today: Optional[str] = None) -> Dict:
    """Grade the window and save -- the standalone job (rule-scoreboard workflow)."""
    import daily_review as DR
    import model_store as MS
    import money_score as MSC
    import props_engine as PE
    import todays_best as TB
    today = today or PE._et_today()
    since = (date.fromisoformat(today) - timedelta(days=WINDOW)).isoformat()
    graded_by: Dict[str, List[Dict]] = {}
    for sp in SPORTS:
        try:
            g = DR.grade_dates(sp, [d for d in MS.snapshot_dates(sp) if since <= d < today])
            graded_by[sp] = [r for rs in g.values() for r in rs]
        except Exception as exc:                                # noqa: BLE001
            print(f"{sp}: grading failed ({type(exc).__name__})")
    games: List[Dict] = []
    d0, d1 = date.fromisoformat(since), date.fromisoformat(today)
    while d0 < d1:
        try:
            games += [dict(r, _day=d0.isoformat())
                      for r in TB.winner_rows(d0.isoformat(), leagues=list(MSC.MONEY_LEAGUES), past=True)]
        except Exception:                                       # noqa: BLE001
            pass
        d0 += timedelta(days=1)
    rec = build(graded_by, games, today)
    save(rec)
    print(f"rule scoreboard: {len(rec['rules'])} rules scored through {today}; "
          f"{sum(r['ready'] for r in rec['rules'])} clear their next gate")
    return rec


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    run(argv[0] if argv else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())


# --------------------------------------------------------------------------- when could each rule clear? (Nov 26)
# Owner, Nov 26: "the fear would be that a season will be over before proven rules produce picks." For each rule: at
# its current return and pace, how many graded picks the next gate needs and roughly when it gets there. Gate 2's
# "90% low end above zero" needs n >= (1.645 x sd / edge)^2 picks -- a small edge takes thousands, a big one a few
# hundred. A forecast, not a promise: the return will move as the sample grows.
Z90 = 1.645
SEASON_END = {"NBA": "04-12", "NHL": "04-16", "NFL": "01-10", "NCAAF": "01-19", "NCAAMB": "04-06"}


def season_end(sport: str, today: str) -> Optional[date]:
    md = SEASON_END.get(sport)
    if not md:
        return None
    t = date.fromisoformat(today)
    y = t.year + (1 if int(md[:2]) < t.month or (int(md[:2]) == t.month and int(md[3:]) < t.day) else 0)
    return date.fromisoformat(f"{y}-{md}")


def sd_per_pick(picks: Sequence[List], roi: float) -> float:
    """The standard deviation of one $1 bet's result at these prices, if the true return were `roi`."""
    vs = []
    for p in picks:
        d = float(p[2])
        q = min(0.99, max(0.01, (1 + roi) / d))
        vs.append(q * (d - 1) ** 2 + (1 - q) - roi ** 2)
    return (sum(vs) / len(vs)) ** 0.5 if vs else 1.0


def picks_needed(picks: Sequence[List], roi: float, floor: int) -> int:
    if roi <= 0:
        return 10 ** 9
    return max(floor, int(math.ceil((Z90 * sd_per_pick(picks, roi) / roi) ** 2)))


def forecast(r: Dict, today: str) -> Dict:
    """{"text", "date", "state"} -- state: on_track / not_this_season / below_bar / losing / proven / no_data."""
    m, picks, sport = r.get("m") or {}, r.get("picks") or [], r.get("sport")
    n = m.get("n") or 0
    if not n:
        return {"state": "no_data", "text": "No graded picks yet", "date": None}
    first = date.fromisoformat(m["first"])
    span = max(1, (date.fromisoformat(today) - first).days)
    pace = n / span                                             # picks a calendar day
    end = season_end(sport, today)
    if r.get("ready"):
        return {"state": "proven", "text": "Clears its next gate now", "date": today}
    if r.get("rule") == "close_gap":
        g = CLOSE_GAP_GATE
        if m["hit"] < g["hit"]:
            return {"state": "below_bar", "text": f"Hitting {m['hit']:.0%}; the gate needs {g['hit']:.0%}", "date": None}
        need = max(0, g["n"] - n)
    else:
        roi = m.get("roi") or 0.0
        if roi <= 0:
            return {"state": "losing", "text": f"Losing ({roi:+.1%} per $1) — can't clear at this edge", "date": None}
        gate_ = GATE2 if r.get("stage") in ("Live test", "Paused") else GATE1
        if roi < gate_["roi"]:
            return {"state": "below_bar", "text": f"Edge {roi:+.1%} is below the {gate_['roi']:+.0%} the gate needs",
                    "date": None}
        total = picks_needed(picks, roi, gate_["n"]) if gate_ is GATE2 else gate_["n"]
        need = max(0, total - n)
    days = int(math.ceil(need / pace)) if pace > 0 else 10 ** 6
    eta = date.fromisoformat(today) + timedelta(days=days)
    if end and eta > end:
        return {"state": "not_this_season", "date": None,
                "text": f"Not this season at this pace — needs ~{need:,} more picks (~{pace:.1f} a day)"}
    return {"state": "on_track", "date": eta.isoformat(),
            "text": f"On track for ~{eta:%b} {eta.day} if the edge holds ({need:,} more picks at ~{pace:.1f} a day)"}
