"""
shutoff.py — markets that keep losing leave 💰, 🔒 and the strongest list on their own (Nov 21).

Owner, Nov 21: get the proven edge to A+. Item 6 of the plan: a market that has lost over a real sample is pulled
automatically, instead of waiting for someone to notice (NHL 🔒 lost -6.2% per $1 over 1,523 picks for weeks before
the audit caught it). Every morning (daily-review workflow) this scores each sport x market x kind over the last
WINDOW days of graded pre-game reads, under TODAY's rules:

  kind "money" -- reads the 💰 rule flags (props_engine.snapshot_is_money), at the price each carried;
  kind "lock"  -- reads 🔒 flags (props_engine.is_lock);
  kind "games" -- game lines the Money Score flags 💰 (todays_best.winner_rows), at the price each carried.

OFF   -- MIN_N+ picks and the return per $1 is below zero even at the top of its 90% range (it isn't bad luck), or
         MIN_CLV_N+ picks that moved and the market moved against them more than (1 - MIN_BEAT) of the time.
WATCH -- WATCH_N+ picks and the return is below WATCH_ROI: shown on the record page, not pulled.

An OFF market stays listed on its pages (the board, Best Bets) but loses its 💰 / 🔒 flag and its place on the
strongest list from the morning it was switched off -- earlier slates keep the flags they were shown with. It comes back
by itself when its record recovers. `python shutoff.py` refits and saves KEY.
"""
from __future__ import annotations

import math
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

KEY = "shutoff:status"
WINDOW = 60
MIN_N = 150
MIN_CLV_N = 100
MIN_BEAT = 0.45
WATCH_N = 75
WATCH_ROI = -0.05
SPORTS = ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB")
_CACHE: Dict[str, tuple] = {}


def verdict(units: Sequence[float], clv: Sequence[str]) -> Dict:
    """{"n", "roi", "hi" (top of the 90% range), "clv_n", "beat", "state": "off" / "watch" / "ok"} from per-$1 results
    and beat / lost / same closing-line marks."""
    n = len(units)
    roi = sum(units) / n if n else None
    sd = (sum((u - roi) ** 2 for u in units) / (n - 1)) ** 0.5 if n > 1 else None
    hi = roi + 1.645 * sd / math.sqrt(n) if sd is not None else None
    moved = [c for c in clv if c in ("beat", "lost")]
    beat = (moved.count("beat") / len(moved)) if moved else None
    state = "ok"
    if n >= MIN_N and hi is not None and hi < 0:
        state = "off"
    elif len(moved) >= MIN_CLV_N and beat is not None and beat < MIN_BEAT:
        state = "off"
    elif n >= WATCH_N and roi is not None and roi < WATCH_ROI:
        state = "watch"
    return {"n": n, "roi": roi, "hi": hi, "clv_n": len(moved), "beat": beat, "state": state}


def _unit(price, hit: bool) -> Optional[float]:
    import props_engine as PE
    d = PE.decimal(price) if price is not None else None
    return None if not d else ((d - 1) if hit else -1.0)


def score_props(sport: str, graded: Sequence[Dict]) -> Dict[str, Dict]:
    """{"<sport>|<market>|money" / "|lock": verdict} from graded prop reads."""
    import clv as CLV
    import props_engine as PE
    groups: Dict[str, tuple] = {}
    for r in graded:
        if r.get("result") not in ("hit", "miss"):
            continue
        hit = r["result"] == "hit"
        u = _unit(r.get("price"), hit)
        if u is None:
            continue
        kinds = []
        try:
            if PE.snapshot_is_money(sport, r):
                kinds.append("money")
            if PE.is_lock(r.get("chance"), r.get("cushion"), r.get("gap"), r.get("book"), ev=r.get("ev")):
                kinds.append("lock")
        except Exception:                                       # noqa: BLE001
            continue
        for k in kinds:
            g = groups.setdefault(f"{sport}|{r.get('market')}|{k}", ([], []))
            g[0].append(u)
            try:
                g[1].append(CLV.pick_clv(r))
            except Exception:                                   # noqa: BLE001
                pass
    return {k: verdict(u, c) for k, (u, c) in groups.items()}


def score_games(rows: Sequence[Dict]) -> Dict[str, Dict]:
    """{"<league>|<market>|games": verdict} from past winner_rows (money flag, money_result, money_price)."""
    groups: Dict[str, List[float]] = {}
    for r in rows:
        if not r.get("money") or r.get("money_result") not in ("win", "loss"):
            continue
        u = _unit(r.get("money_price"), r["money_result"] == "win")
        if u is not None:
            groups.setdefault(f"{r.get('sport')}|{r.get('money_market')}|games", []).append(u)
    return {k: verdict(u, []) for k, u in groups.items()}


def refit(today: Optional[str] = None, save=None, grade=None, games=None, now: Optional[datetime] = None) -> Dict:
    import props_engine as PE
    today = today or PE._et_today()
    since = (date.fromisoformat(today) - timedelta(days=WINDOW)).isoformat()
    if grade is None:
        import daily_review as DR
        import model_store as MS

        def grade(sp):
            g = DR.grade_dates(sp, [d for d in MS.snapshot_dates(sp) if since <= d < today])
            return [r for rs in g.values() for r in rs]
    out: Dict[str, Dict] = {}
    graded_by: Dict[str, List[Dict]] = {}
    for sp in SPORTS:
        try:
            graded_by[sp] = grade(sp)
            out.update(score_props(sp, graded_by[sp]))
        except Exception as exc:                                # noqa: BLE001
            print(f"{sp}: shut-off scoring failed ({type(exc).__name__}: {exc})")
    try:
        if games is None:
            import money_score as MSC
            import todays_best as TB
            d0, d1 = date.fromisoformat(since), date.fromisoformat(today)
            games = []
            while d0 < d1:
                games += [dict(r, _day=d0.isoformat())
                          for r in TB.winner_rows(d0.isoformat(), leagues=list(MSC.MONEY_LEAGUES), past=True)]
                d0 += timedelta(days=1)
        out.update(score_games(games))
    except Exception as exc:                                    # noqa: BLE001
        print(f"game lines: shut-off scoring failed ({type(exc).__name__}: {exc})")
    if save is None:                                            # Nov 21: the bankroll simulation, same graded picks
        try:
            import bankroll_sim as BS
            BS.run(graded_by, games or [])
        except Exception as exc:                                # noqa: BLE001
            print(f"bankroll simulation failed ({type(exc).__name__}: {exc})")
    prev = (_load() or {}).get("since") or {}
    # a switch takes effect before the day's games: today when refit before 11 AM New York, else tomorrow
    import pytz
    et = (now or datetime.now(timezone.utc)).astimezone(pytz.timezone("US/Eastern"))
    start = today if et.hour < 11 else (date.fromisoformat(today) + timedelta(days=1)).isoformat()
    since_map = {k: (prev.get(k) or start) for k, v in out.items() if v["state"] == "off"}
    rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "day": today, "groups": out,
           "since": since_map}
    if save is None:
        import model_store as MS
        save = MS.save_setting
    save(KEY, rec)
    _CACHE.clear()
    for k, v in sorted(out.items()):
        if v["state"] != "ok":
            print(f"{v['state'].upper():5} {k}: {v['n']} picks, {v['roi']:+.1%} per $1 (90% top {v['hi']:+.1%})"
                  + (f", beat the close {v['beat']:.0%} of {v['clv_n']}" if v.get("beat") is not None else ""))
    print(f"shut-off: {sum(v['state'] == 'off' for v in out.values())} off, "
          f"{sum(v['state'] == 'watch' for v in out.values())} watch, of {len(out)} groups")
    return rec


def _load(get=None) -> Dict:
    injected = get is not None
    hit = _CACHE.get("v")
    if hit and time.time() - hit[0] < 600 and not injected:
        return hit[1]
    try:
        if get is None:
            import model_store as MS
            get = MS.get_setting
        v = get(KEY, None) or {}
    except Exception:                                           # noqa: BLE001
        v = {}
    if not injected:
        _CACHE["v"] = (time.time(), v)
    return v


def is_off(sport: str, market: Optional[str], kind: str, day: Optional[str] = None, status: Optional[Dict] = None) -> bool:
    """Is this sport x market x kind switched off for slate `day` (default today)? Slates before the switch keep their
    flags."""
    st_ = status if status is not None else _load()
    k = f"{sport}|{market}|{kind}"
    since = (st_.get("since") or {}).get(k)
    if not since:
        return False
    import props_engine as PE
    if day is None:
        day = PE._et_today()
    t = PE.MONEY_TEST                                           # the owner's 💰 live test runs untouched to its end
    if kind == "money" and t["from"] <= day <= t["to"] and sport in t["sports"]:
        return False
    return day >= since


def table(status: Optional[Dict] = None) -> List[Dict]:
    st_ = status if status is not None else _load()
    name = {"money": "💰 props", "lock": "🔒 Most probable", "games": "💰 game lines"}
    rows = []
    for k, v in sorted((st_.get("groups") or {}).items(), key=lambda kv: (kv[1]["state"] != "off", kv[0])):
        if v["state"] == "ok":
            continue
        sp, mk, kind = k.split("|")
        rows.append({"State": "⛔ Off" if v["state"] == "off" else "👀 Watch", "Picks": name.get(kind, kind),
                     "Sport": sp, "Market": mk, "Graded": v["n"],
                     "Return per $1": f"{v['roi']:+.1%}" if v.get("roi") is not None else "—",
                     "Beat the close": f"{v['beat']:.0%} of {v['clv_n']}" if v.get("beat") is not None else "—",
                     "Since": (st_.get("since") or {}).get(k, "")})
    return rows


def main(argv: Optional[Sequence[str]] = None) -> int:
    import props_engine as PE
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--force" not in argv and (_load().get("day") == PE._et_today()):
        print("shut-off: already refit this morning")             # the daily review runs hourly; once a day is enough
        return 0
    refit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
