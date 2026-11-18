"""
watch.py -- 👀 Watch: No-edge groups that made money, tracked before they're trusted (Nov 17).

Owner: "with all of these pass ratings ... I would have expected the model pass hit rate to be extremely high ... there
are playable items being missed." research/pass_hunt.py split 30 days of graded No-edge reads (63 for football) by
sport x market x side and kept groups that made money at their real prices in BOTH halves of the window. Dozens of
groups were tested, so some of these will be luck: they are tagged 👀 Watch (shown on the boards, graded like
everything else, never a parlay leg) and judged on the games AFTER they were found:
  * 14+ days and 30+ graded reads since `since`, profit per $1 > 0 -> promoted: tagged 🎯 Single only from then on
  * profit per $1 below -5% once 30+ are graded -> dropped: back to No edge
The morning review writes each group's verdict (STATUS_KEY); the boards read it.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Sequence

STATUS_KEY = "watch:status"
MIN_DAYS, MIN_READS, DROP_BELOW = 14, 30, -0.05
# Nov 18: dozens of groups were searched to find these six, so some made money by luck. Promotion now needs the profit
# to clear zero by a margin: average profit per $1 minus PROMOTE_Z standard errors still above 0 (one-sided ~90%).
PROMOTE_Z = 1.28
FAR = 0.15                     # |projection - line| / line at or above this = "far" from the number

RULES: List[Dict] = [
    {"id": "nba_pts_under_far", "sport": "NBA", "market": "Points", "side": "Under", "gap": "far", "since": "2026-11-17",
     "found": "276 reads, 55.8%, +5.5% per $1 (+9.1% then +4.0%)"},
    {"id": "nba_3pm_over", "sport": "NBA", "market": "Threes Made", "side": "Over", "gap": None, "since": "2026-11-17",
     "found": "325 reads, 48.3% at plus prices, +5.1% per $1 (+5.3% then +5.0%)"},
    {"id": "nfl_rush_att_under", "sport": "NFL", "market": "Rush Attempts", "side": "Under", "gap": None,
     "since": "2026-11-17", "found": "60 reads, 60.0%, +14.4% per $1"},
    {"id": "nfl_rush_yds_under", "sport": "NFL", "market": "Rush Yards", "side": "Under", "gap": None,
     "since": "2026-11-17", "found": "60 reads, 58.3%, +10.4% per $1"},
    {"id": "nfl_sacks_over", "sport": "NFL", "market": "Sacks", "side": "Over", "gap": None, "since": "2026-11-17",
     "found": "192 reads, 32.8% at long prices, +12.8% per $1 (+28.7% then +3.3%: fading)"},
    {"id": "ncaaf_rec_under_near", "sport": "NCAAF", "market": "Receptions", "side": "Under", "gap": "near",
     "since": "2026-11-17", "found": "69 reads, 59.4%, +9.5% per $1"},
]


def _market(m) -> str:
    try:
        import model_view as MV
        return MV.market_of(m) or str(m)
    except Exception:                                           # noqa: BLE001
        return str(m)


def gap_bucket(projection, line) -> Optional[str]:
    try:
        g = abs(float(projection) - float(line)) / max(float(line), 0.5)
    except (TypeError, ValueError):
        return None
    return "far" if g >= FAR else "near"


def rule_for(sport: Optional[str], market, side, projection=None, line=None) -> Optional[Dict]:
    if not sport:
        return None
    mk = _market(market)
    for r in RULES:
        if r["sport"] == sport and r["market"] == mk and r["side"] == side:
            if r["gap"] is None or r["gap"] == gap_bucket(projection, line):
                return r
    return None


_STATUS_CACHE: Dict = {"at": 0.0, "v": {}}


def statuses() -> Dict[str, Dict]:
    import time
    if time.time() - _STATUS_CACHE["at"] < 600:
        return _STATUS_CACHE["v"]
    try:
        import model_store as MS
        v = MS.get_setting(STATUS_KEY, {}) or {}
    except Exception:                                           # noqa: BLE001
        v = {}
    _STATUS_CACHE.update(at=time.time(), v=v if isinstance(v, dict) else {})
    return _STATUS_CACHE["v"]


def apply(tag: str, sport: Optional[str], market, side, projection=None, line=None,
          status: Optional[Dict[str, Dict]] = None) -> str:
    """A No-edge tag becomes 👀 Watch (or 🎯 Single only once its group is promoted) when the read falls in a
    watched group; any other tag is returned unchanged."""
    import props_engine as PE
    if not PE.is_pass(tag):
        return tag
    r = rule_for(sport, market, side, projection, line)
    if not r:
        return tag
    st = (status if status is not None else statuses()).get(r["id"], {}).get("status", "watch")
    if st == "promoted":
        return PE.USE_SINGLE
    if st == "dropped":
        return tag
    return PE.USE_WATCH


def _dec(price) -> Optional[float]:
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    return 1 + (p / 100 if p > 0 else 100 / -p)


def judge(sport: str, graded_by_date: Dict[str, Sequence[Dict]], today: str,
          old: Optional[Dict[str, Dict]] = None) -> Dict[str, Dict]:
    """Each of `sport`'s groups judged on reads graded since it was found (its "since" date)."""
    out = dict(old or {})
    for r in (x for x in RULES if x["sport"] == sport):
        n = h = 0
        units = 0.0
        rets = []
        for d, rows in graded_by_date.items():
            if d < r["since"]:
                continue
            for g in rows:
                if g.get("result") not in ("hit", "miss") or _market(g.get("market")) != r["market"] \
                        or g.get("side") != r["side"]:
                    continue
                if r["gap"] and gap_bucket(g.get("projection"), g.get("line")) != r["gap"]:
                    continue
                dec = _dec(g.get("over_price") if g.get("side") == "Over" else g.get("under_price"))
                if dec is None:
                    continue
                y = g["result"] == "hit"
                n += 1
                h += y
                units += (dec - 1) if y else -1.0
                rets.append((dec - 1) if y else -1.0)
        prev = (out.get(r["id"]) or {}).get("status", "watch")
        days = (date.fromisoformat(today) - date.fromisoformat(r["since"])).days
        status = prev
        floor = None
        if n >= 2:
            m = units / n
            sd = (sum((x - m) ** 2 for x in rets) / (n - 1)) ** 0.5
            floor = m - PROMOTE_Z * sd / n ** 0.5
        if prev == "watch" and n >= MIN_READS:
            if units / n < DROP_BELOW:
                status = "dropped"
            elif days >= MIN_DAYS and floor is not None and floor > 0:
                status = "promoted"
        out[r["id"]] = {"status": status, "n": n, "hits": h, "profit_per_1": round(units / n, 4) if n else None,
                        "profit_floor": None if floor is None else round(floor, 4), "days": days, "updated": today}
    return out


# --------------------------------------------------------------------------- Overs gate (Nov 17)
# Owner-approved after the Over/Under record: bet-tagged Overs hit 37-45% vs Unders 51-61% (30 days; 63 for football),
# and raising the chance floor didn't help -- NBA, NCAAF and NHL Overs lost money at every floor up to 62-65%
# (research/over_bar.py). NFL Overs made +16% per $1 (21 priced, mostly plus-money), so the gate is per sport and
# decided by each sport's own record every morning: Over bets are tagged ⚪ No edge while the sport's would-be Over
# bets (Over reads at 55%+) lose -- profit per $1 < 0 when 20+ are priced, else a hit rate 5+ points under what the
# model said -- and come back on their own once they don't.
OVERS_KEY = "overs:gate"
OVER_FLOOR = 0.55


def judge_overs(sport: str, graded_by_date: Dict[str, Sequence[Dict]], old: Optional[Dict] = None) -> Dict:
    out = dict(old or {})
    rows = [g for rs in graded_by_date.values() for g in rs
            if g.get("result") in ("hit", "miss") and g.get("side") == "Over"
            and float(g.get("chance") or 0) >= OVER_FLOOR]
    n = len(rows)
    hits = sum(g["result"] == "hit" for g in rows)
    said = sum(float(g["chance"]) for g in rows) / n if n else None
    priced = [g for g in rows if _dec(g.get("over_price")) is not None]
    units = sum((_dec(g["over_price"]) - 1) if g["result"] == "hit" else -1.0 for g in priced)
    if n < 20:
        off = bool((out.get(sport) or {}).get("off"))          # too few to change anything
    elif len(priced) >= 20:
        off = units < 0
    else:
        off = (hits / n) < (said or 0) - 0.05
    out[sport] = {"off": off, "n": n, "hit": round(hits / n, 4) if n else None,
                  "said": round(said, 4) if said is not None else None, "priced": len(priced),
                  "profit_per_1": round(units / len(priced), 4) if priced else None}
    return out


_OVERS_CACHE: Dict = {"at": 0.0, "v": {}}


def overs_off(sport: Optional[str], gate: Optional[Dict] = None) -> bool:
    if not sport:
        return False
    if gate is None:
        import time
        if time.time() - _OVERS_CACHE["at"] > 600:
            try:
                import model_store as MS
                _OVERS_CACHE.update(at=time.time(), v=MS.get_setting(OVERS_KEY, {}) or {})
            except Exception:                                   # noqa: BLE001
                _OVERS_CACHE.update(at=time.time(), v={})
        gate = _OVERS_CACHE["v"]
    return bool((gate.get(sport) or {}).get("off"))


def gate_over(tag: str, sport: Optional[str], side, gate: Optional[Dict] = None) -> str:
    """A bet tag on an Over becomes ⚪ No edge while the sport's Overs gate is off."""
    import props_engine as PE
    if side != "Over" or PE.norm_use(tag) not in (PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE):
        return tag
    return PE.USE_PASS if overs_off(sport, gate) else tag
