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
    try:                                                        # Nov 21: the picks as shown, when the slate has a ledger
        import pick_ledger as PL
        led = PL.record("money", sport, slate)
        if led:
            return {"hits": led["hits"], "misses": led["misses"], "units": led["units"], "needed": led["needed"],
                    "clv_beat": 0, "clv_lost": 0}
    except Exception:                                           # noqa: BLE001
        pass
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
                    "units": (mo.get("profit") or 0.0) * n, "needed": mo.get("needed"),
                    "clv_beat": mo.get("clv_beat") or 0, "clv_lost": mo.get("clv_lost") or 0}
    return best


def game_record(day: str, games: Callable) -> Dict[str, Dict]:
    """Nov 20: the day's game-line 💰 (money_score.py), graded: {"games:<sport>": {hits, misses, units, needed}}."""
    out: Dict[str, Dict] = {}
    try:                                                        # Nov 21: the game-line 💰 as shown, when there's a ledger
        import pick_ledger as PL
        for lg in ("NCAAMB", "NBA", "NHL", "NFL", "NCAAF"):
            led = PL.record("games", lg, day)
            if led:
                out[f"games:{lg}"] = {"hits": led["hits"], "misses": led["misses"], "units": led["units"],
                                      "need_sum": (led["needed"] or 0) * led["n"]}
        if out:
            return out
    except Exception:                                           # noqa: BLE001
        pass
    for r in games(day) or []:
        res = r.get("money_result")
        if not r.get("money") or res not in ("win", "loss"):
            continue
        d = PE.decimal(r.get("money_price")) if r.get("money_price") is not None else None
        if not d:
            continue
        x = out.setdefault(f"games:{r.get('sport')}", {"hits": 0, "misses": 0, "units": 0.0, "need_sum": 0.0})
        x["hits" if res == "win" else "misses"] += 1
        x["units"] += (d - 1) if res == "win" else -1.0
        x["need_sum"] += 1 / d
    return out


def scoreboard(load: Optional[Callable] = None, today: Optional[str] = None, test: Optional[Dict] = None,
               games: Optional[Callable] = None) -> Dict:
    """{"sports": [{sport, hits, misses, units, roi, hit_rate, needed, slates}], "total": {...}, "from", "to"}."""
    if load is None:
        import model_store as MS
        load = MS.load_daily_review
    test = test or PE.MONEY_TEST
    today = today or PE._et_today()
    last = min(test["to"], (date.fromisoformat(today) - timedelta(days=1)).isoformat())
    out, tot = [], {"hits": 0, "misses": 0, "units": 0.0, "need_sum": 0.0, "clv_beat": 0, "clv_lost": 0}
    for sp in test["sports"]:
        row = {"sport": sp, "hits": 0, "misses": 0, "units": 0.0, "need_sum": 0.0, "slates": 0, "clv_beat": 0,
               "clv_lost": 0}
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
                row["clv_beat"] += r.get("clv_beat") or 0
                row["clv_lost"] += r.get("clv_lost") or 0
        out.append(row)
        for k in ("hits", "misses", "units", "need_sum", "clv_beat", "clv_lost"):
            tot[k] += row[k]
    # Nov 20: the game-line 💰 (money_score.py), one row per league
    try:
        import money_score as MSC
        if games is None:
            import todays_best as TB
            games = lambda d: TB.winner_rows(d, leagues=list(MSC.MONEY_LEAGUES), past=True)   # noqa: E731
        grows = {f"games:{lg}": {"sport": f"games:{lg}", "hits": 0, "misses": 0, "units": 0.0, "need_sum": 0.0,
                                 "slates": 0} for lg in MSC.MONEY_LEAGUES if lg in test["sports"]}
        if grows and test["from"] <= last:
            for d in _days(test["from"], last):
                for k, v in game_record(d, games).items():
                    if k in grows:
                        for f in ("hits", "misses", "units", "need_sum"):
                            grows[k][f] += v[f]
                        grows[k]["slates"] += 1
        for row in grows.values():
            out.append(row)
            for k in ("hits", "misses", "units", "need_sum"):
                tot[k] += row[k]
    except Exception:                                           # noqa: BLE001 -- props rows still show
        pass
    for r in out + [tot]:
        c = r.get("clv_beat", 0) + r.get("clv_lost", 0)
        r["clv"] = r.get("clv_beat", 0) / c if c else None
        r["clv_n"] = c
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
            if r["sport"].startswith("games:"):
                g = S.get(r["sport"].split(":", 1)[1])
                name = f"{g.icon} {g.label.split(' — ')[0]} game lines"
            else:
                name = f"{S.get(r['sport']).icon} {S.get(r['sport']).label.split(' — ')[0]} props"
        except Exception:                                       # noqa: BLE001
            name = r["sport"]
        rows.append({"Sport": name,
                     "Record": f"{r['hits']}–{r['misses']}" if r["n"] else "—",
                     "Hit rate": r["hit_rate"], "Needed": r["needed"],
                     "Units ($1 a pick)": round(r["units"], 2) if r["n"] else None,
                     "Per $1": r["roi"],
                     "Beat the close": (f"{r['clv']:.0%} of {r['clv_n']}" if r.get("clv") is not None else "—"),
                     "Today": (live or {}).get(r["sport"], 0)})
    return rows


TESTED = {"NBA": "💰 tested: 50–57 (47%, needed 45%), +6.0% per $1"}     # research/weekend_audit2.py, the Nov 20 rule


def record_text(sport: str, board: Optional[Dict] = None) -> str:
    """Nov 20 (owner: "I thought the record column was cleaned up"): what a 💰 pick's Record column says -- the live
    test's record for that sport's 💰 props once there is one, else the rule's tested record, else that it's new."""
    try:
        b = board or scoreboard()
        r = next((x for x in b["sports"] if x["sport"] == sport), None)
        if r and r["n"]:
            return (f"💰 live: {r['hits']}–{r['misses']} ({r['hit_rate']:.0%}, needed {r['needed']:.0%}), "
                    f"{r['units']:+.2f}u")
    except Exception:                                           # noqa: BLE001
        pass
    return TESTED.get(sport, "💰 new rule — no record yet (live test)")
