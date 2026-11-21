"""
bankroll_sim.py — what the 💰 staking plan risks (Nov 21).

Owner, Nov 21: yes to a bankroll simulation. The stakes are a quarter of the Kelly stake, at most 2u a pick, and the
day's 💰 picks scaled to 10u at most (1u = 1% of the bankroll). This replays the last WINDOW days of graded 💰 picks
(props and game lines, today's rules, at the price each carried) with those stakes, then draws DAYS-day seasons by
resampling whole days (a day's picks stay together, as they're bet together), PATHS times, from a 100u bankroll:

  * at the record   -- each day's picks win or lose as they did;
  * with no edge    -- the same picks, each winning only as often as its price needs (break-even): what the plan risks
                       if the edge isn't real. That's the honest floor while the edge is still being proven.

For each: the middle and the bad-case (5th percentile) bankroll after DAYS days, the chance of finishing up, the
typical and bad-case worst drop from a high (drawdown), and the chance of a 25u drop at some point. Saved (KEY) once a
morning by the daily review; shown on Model Record.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

KEY = "bankroll:sim"
WINDOW = 60
DAYS = 90
PATHS = 5000
BANK = 100.0
DAILY_CAP = 10.0
DROP = 25.0


def day_picks(graded_by: Dict[str, Sequence[Dict]], games: Sequence[Dict] = ()) -> Dict[str, List[tuple]]:
    """{slate: [(stake units, decimal price, hit)]} -- every graded 💰 pick, stakes as the platform sizes them."""
    import props_engine as PE
    days: Dict[str, List[tuple]] = {}
    for sp, g in graded_by.items():
        for r in g:
            if r.get("result") not in ("hit", "miss") or r.get("price") is None:
                continue
            try:
                if not PE.snapshot_is_money(sp, r):
                    continue
            except Exception:                                   # noqa: BLE001
                continue
            u = PE.stake_units(r.get("chance"), r.get("price"), capped=False)
            d = PE.decimal(r["price"])
            if u and d:
                days.setdefault(str(r.get("slate_date")), []).append((u, d, r["result"] == "hit"))
    for r in games:
        if not r.get("money") or r.get("money_result") not in ("win", "loss") or r.get("money_price") is None:
            continue
        u = PE.stake_units(r.get("money_chance"), r.get("money_price"), capped=False)
        d = PE.decimal(r["money_price"])
        if u and d:
            days.setdefault(str(r.get("date") or r.get("slate") or r.get("_day") or ""), []).append(
                (u, d, r["money_result"] == "win"))
    for k, ps in days.items():                                  # the 10u daily cap
        tot = sum(u for u, _, _ in ps)
        if tot > DAILY_CAP:
            days[k] = [(u * DAILY_CAP / tot, d, h) for u, d, h in ps]
    return {k: v for k, v in days.items() if k}


def _day_pnl(ps: Sequence[tuple], no_edge: bool, rnd: random.Random) -> float:
    out = 0.0
    for u, d, h in ps:
        win = (rnd.random() < 1 / d) if no_edge else h
        out += u * (d - 1) if win else -u
    return out


def simulate(days: Dict[str, List[tuple]], no_edge: bool = False, n_days: int = DAYS, paths: int = PATHS,
             seed: int = 7) -> Optional[Dict]:
    pool = list(days.values())
    if len(pool) < 5:
        return None
    rnd = random.Random(seed)
    ends, dds, hit25 = [], [], 0
    for _ in range(paths):
        bank, peak, worst = BANK, BANK, 0.0
        for _ in range(n_days):
            bank += _day_pnl(rnd.choice(pool), no_edge, rnd)
            peak = max(peak, bank)
            worst = max(worst, peak - bank)
        ends.append(bank)
        dds.append(worst)
        hit25 += worst >= DROP
    ends.sort()
    dds.sort()
    q = lambda xs, p: xs[min(len(xs) - 1, int(p * len(xs)))]   # noqa: E731
    return {"median_end": q(ends, 0.5), "bad_end": q(ends, 0.05), "good_end": q(ends, 0.95),
            "p_up": sum(e > BANK for e in ends) / paths, "median_dd": q(dds, 0.5), "bad_dd": q(dds, 0.95),
            "p_drop25": hit25 / paths}


def run(graded_by: Dict[str, Sequence[Dict]], games: Sequence[Dict] = (), save=None) -> Optional[Dict]:
    days = day_picks(graded_by, games)
    if len(days) < 5:
        return None
    picks = [p for v in days.values() for p in v]
    rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "days": len(days), "picks": len(picks),
           "avg_day_units": sum(u for u, _, _ in picks) / len(days),
           "record": simulate(days), "no_edge": simulate(days, no_edge=True),
           "hit_rate": sum(h for _, _, h in picks) / len(picks),
           "needed": sum(1 / d for _, d, _ in picks) / len(picks)}
    if save is None:
        import model_store as MS
        save = MS.save_setting
    try:
        save(KEY, rec)
    except Exception:                                           # noqa: BLE001
        pass
    return rec


def load() -> Optional[Dict]:
    try:
        import model_store as MS
        return MS.get_setting(KEY, None)
    except Exception:                                           # noqa: BLE001
        return None


def rows(rec: Dict) -> List[Dict]:
    out = []
    for key, name in (("record", "At the record"), ("no_edge", "With no edge (break-even)")):
        s = rec.get(key)
        if not s:
            continue
        out.append({"Scenario": name, f"Bankroll after {DAYS} days (middle)": f"{s['median_end']:.0f}u",
                    "Bad case (1 in 20)": f"{s['bad_end']:.0f}u", "Chance of finishing up": f"{s['p_up']:.0%}",
                    "Typical worst drop": f"{s['median_dd']:.0f}u", "Bad-case worst drop": f"{s['bad_dd']:.0f}u",
                    f"Chance of a {DROP:.0f}u drop": f"{s['p_drop25']:.0%}"})
    return out
