"""
progression.py — the numbers behind the Progression Plan page (Nov 3): the slow-build framework for running the
platform as a business, measured from the Bet Log (real-money bets only; the Bet Log stays the single ledger).

The framework: flat stakes at a fixed share of the bankroll, quality singles over volume, judged monthly, and three
stages with gates that have to be EARNED before stakes go up:
  1. Prove  -- small flat stakes until 1,000 settled singles show an edge (ROI and the closing line)
  2. Scale  -- stakes follow the bankroll (unit = UNIT % of it); income goal math becomes meaningful
  3. Go     -- a year-long record at the scaled size supports the monthly income goal

    plan(settings, bets, today) -> everything the page shows (no Streamlit here; tested directly)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional, Sequence

DEFAULTS = {"start_bankroll": 1000.0, "start_date": "2026-11-01", "unit_pct": 0.01, "target_roi": 0.03,
            "monthly_goal": 4000.0, "bets_per_month": 300}
SETTINGS_KEY = "progression_plan"

# Gates to move from Prove to Scale (and Scale to Go). Each is (label, key, needed, how it's compared).
PROVE_GATES = (
    ("Settled singles", "singles", 1000, ">="),
    ("Singles ROI", "singles_roi", 0.02, ">="),
    ("Bets with a closing price", "clv_n", 200, ">="),
    ("Beat the closing line", "beat_close", 0.52, ">="),
    ("Largest drawdown (share of peak bankroll)", "max_dd", 0.30, "<="),
)
SCALE_GATES = (
    ("Months at the scaled size", "months_scaled", 12, ">="),
    ("Profitable months", "profitable_share", 0.60, ">="),
    ("Average month vs the income goal", "goal_share", 1.0, ">="),
)
PARLAY_MONEY_CAP = 0.10       # parlays kept to 10% or less of money staked
OVERSIZE_UNITS = 2.0          # a single over 2 units is off-plan
TAX_NONDEDUCTIBLE = 0.10      # 2026: gambling losses are 90% deductible (rough estimate only)


def _res(b) -> str:
    r = b.get("result")
    return "" if r is None or (isinstance(r, float) and r != r) else str(r).strip().lower()


def _month(b) -> str:
    return str(b.get("slate_date") or b.get("ts_placed") or "")[:7]


def _day(b) -> str:
    return str(b.get("slate_date") or b.get("ts_placed") or "")[:10]


def _ok(v, need, how) -> bool:
    if v is None:
        return False
    return v >= need if how == ">=" else v <= need


def plan(settings: Dict, bets: Sequence[Dict], today: Optional[date] = None) -> Dict:
    import betlog as B
    s = dict(DEFAULTS, **{k: v for k, v in (settings or {}).items() if v is not None})
    today = today or date.today()
    start = str(s["start_date"])
    real = [b for b in bets if b.get("is_real_bet") not in (False, 0, "0", "false") and _day(b) >= start]
    money = B.money_bets(real)
    # a $0 row (a pick'em leg or a pick logged without a stake) carries no money: it isn't a bet for the plan
    settled = [b for b in money if _res(b) in ("win", "loss", "push") and float(b.get("stake") or 0) > 0]
    singles = [b for b in settled if not B.is_parlay_header(b) and not B._ticket(b)]
    parlays = [b for b in settled if B.is_parlay_header(b)]

    def roi(rows):
        st = sum(float(b.get("stake") or 0) for b in rows)
        return (sum(B.bet_pnl(b) or 0 for b in rows) / st) if st > 0 else None

    # bankroll path by day, drawdown
    by_day = defaultdict(float)
    for b in settled:
        by_day[_day(b)] += B.bet_pnl(b) or 0
    bank, peak, max_dd, path = float(s["start_bankroll"]), float(s["start_bankroll"]), 0.0, []
    for d in sorted(by_day):
        bank += by_day[d]
        peak = max(peak, bank)
        if peak > 0:
            max_dd = max(max_dd, (peak - bank) / peak)
        path.append({"date": d, "bankroll": round(bank, 2)})
    unit = max(0.0, bank * float(s["unit_pct"]))

    # closing line
    clvs = [B.clv_pct(b.get("entry_odds"), b.get("close_odds")) for b in money if not B.is_parlay_header(b)]
    clvs = [c for c in clvs if c is not None]

    # months
    months = []
    by_m = defaultdict(list)
    for b in settled:
        by_m[_month(b)].append(b)
    for m in sorted(by_m):
        rows = by_m[m]
        sg = [b for b in rows if not B.is_parlay_header(b) and not B._ticket(b)]
        staked = sum(float(b.get("stake") or 0) for b in rows)
        profit = sum(B.bet_pnl(b) or 0 for b in rows)
        cm = [B.clv_pct(b.get("entry_odds"), b.get("close_odds")) for b in sg]
        cm = [c for c in cm if c is not None]
        months.append({"month": m, "bets": len(rows), "singles": len(sg), "staked": round(staked, 2),
                       "profit": round(profit, 2), "roi": (profit / staked) if staked > 0 else None,
                       "singles_roi": roi(sg), "beat_close": (sum(1 for c in cm if c > 0) / len(cm)) if cm else None,
                       "parlay_money": (sum(float(b.get("stake") or 0) for b in rows if B.is_parlay_header(b)) / staked)
                       if staked > 0 else None})

    # discipline
    staked_all = sum(float(b.get("stake") or 0) for b in settled)
    parlay_share = (sum(float(b.get("stake") or 0) for b in parlays) / staked_all) if staked_all > 0 else None
    oversize = [b for b in singles if unit > 0 and float(b.get("stake") or 0) > OVERSIZE_UNITS * unit]

    # gates
    metrics = {"singles": len(singles), "singles_roi": roi(singles), "clv_n": len(clvs),
               "beat_close": (sum(1 for c in clvs if c > 0) / len(clvs)) if clvs else None,
               "max_dd": max_dd if path else None}
    prove = [{"label": lbl, "value": metrics[k], "need": need, "how": how, "ok": _ok(metrics[k], need, how)}
             for lbl, k, need, how in PROVE_GATES]
    goal = float(s["monthly_goal"])
    full = [m for m in months if m["month"] < today.isoformat()[:7]]
    scaled_from = s.get("scaled_from")
    scaled = [m for m in full if scaled_from and m["month"] >= str(scaled_from)[:7]]
    smetrics = {"months_scaled": len(scaled),
                "profitable_share": (sum(1 for m in scaled if m["profit"] > 0) / len(scaled)) if scaled else None,
                "goal_share": (sum(m["profit"] for m in scaled) / len(scaled) / goal) if scaled and goal > 0 else None}
    scale = [{"label": lbl, "value": smetrics[k], "need": need, "how": how, "ok": _ok(smetrics[k], need, how)}
             for lbl, k, need, how in SCALE_GATES]
    stage = 1 if not all(g["ok"] for g in prove) else (2 if not all(g["ok"] for g in scale) else 3)

    # goal math: what the monthly goal takes at the target ROI, and what the record says now
    tr = float(s["target_roi"])
    turnover = goal / tr if tr > 0 else None
    per_bet = (turnover / float(s["bets_per_month"])) if turnover and s["bets_per_month"] else None
    bank_needed = (per_bet / float(s["unit_pct"])) if per_bet and s["unit_pct"] else None
    recent = full[-3:]
    pace = (sum(m["profit"] for m in recent) / len(recent)) if recent else None

    losing_stakes_ytd = sum(float(b.get("stake") or 0) for b in settled
                            if _res(b) == "loss" and _day(b)[:4] == str(today.year))
    return {"settings": s, "stage": stage, "bankroll": round(bank, 2), "unit": round(unit, 2), "path": path,
            "profit": round(bank - float(s["start_bankroll"]), 2), "settled": len(settled),
            "singles": len(singles), "parlays": len(parlays), "singles_roi": roi(singles), "parlay_roi": roi(parlays),
            "max_dd": max_dd, "months": months, "prove": prove, "scale": scale,
            "discipline": {"parlay_share": parlay_share, "parlay_ok": parlay_share is None or parlay_share <= PARLAY_MONEY_CAP,
                           "oversize": len(oversize)},
            "goal": {"monthly": goal, "turnover": turnover, "per_bet": per_bet, "bankroll_needed": bank_needed,
                     "pace": pace, "bets_per_month": s["bets_per_month"], "target_roi": tr},
            "tax": {"nondeductible": round(losing_stakes_ytd * TAX_NONDEDUCTIBLE, 2), "losing_stakes": round(losing_stakes_ytd, 2)}}


# --------------------------------------------------------------------------- strategies (Nov 4)
# A "strategy" is the tag a bet was logged under (live-tennis, live-intl-hoops, discord-over...). For each: the real money
# result, and -- for parlays whose legs carry their own prices -- how the LEGS did against what those prices implied, and
# what the same legs would have made as $1 singles. That answers the question a parlay result alone can't: is there an
# edge in the picks, or did the parlay just get lucky?
AUTO_TAGS = ("use:", "leg_price=", "market-gap", "star-out", "tracking", "honest-chances")


def strategy_of(b: Dict) -> str:
    for part in str(b.get("notes") or "").split(","):
        t = part.strip()
        if not t or t.startswith(AUTO_TAGS):
            continue
        return "game-lab" if t.startswith("gl:") else t
    return "untagged"


def _implied(a) -> Optional[float]:
    try:
        a = float(a)
    except (TypeError, ValueError):
        return None
    if -100 < a < 100:
        return None
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def strategies(bets: Sequence[Dict], start: Optional[str] = None) -> List[Dict]:
    import betlog as B
    real = [b for b in bets if b.get("is_real_bet") not in (False, 0, "0", "false")
            and (not start or _day(b) >= start)]
    headed = B.headed_tickets(real)
    groups: Dict[str, Dict] = {}
    for b in B.money_bets(real):
        if float(b.get("stake") or 0) <= 0:
            continue
        g = groups.setdefault(strategy_of(b), {"strategy": strategy_of(b), "bets": 0, "parlays": 0, "singles": 0,
                                               "open": 0, "staked": 0.0, "profit": 0.0, "legs": []})
        g["bets"] += 1
        g["parlays" if B.is_parlay_header(b) else "singles"] += 1
        if not _res(b):
            g["open"] += 1
            continue
        g["staked"] += float(b.get("stake") or 0)
        g["profit"] += B.bet_pnl(b) or 0
        if not B.is_parlay_header(b):                            # a single is its own "leg"
            g["legs"].append((b.get("entry_odds"), _res(b)))
    for b in real:
        if B.is_parlay_leg(b, headed) and B.leg_price(b) is not None:
            hdr = next((h for h in real if B.is_parlay_header(h) and B._ticket(h) == B._ticket(b)), None)
            if hdr is None or float(hdr.get("stake") or 0) <= 0:
                continue
            g = groups.get(strategy_of(hdr))
            if g is not None:
                g["legs"].append((B.leg_price(b), _res(b)))
    out = []
    for g in groups.values():
        legs = [(pr, r) for pr, r in g.pop("legs") if r in ("win", "loss") and _implied(pr) is not None]
        n = len(legs)
        won = sum(1 for _, r in legs if r == "win")
        implied = sum(_implied(pr) / 1.045 for pr, _ in legs) / n if n else None    # vig taken off (~4.5%)
        as_singles = sum((100 / -float(pr) if float(pr) < 0 else float(pr) / 100) if r == "win" else -1.0
                         for pr, r in legs) if n else None
        g.update(roi=(g["profit"] / g["staked"]) if g["staked"] > 0 else None, legs=n, legs_won=won,
                 leg_hit=(won / n) if n else None, leg_implied=implied,
                 singles_per_leg=(as_singles / n) if n else None)
        out.append(g)
    return sorted(out, key=lambda x: -x["staked"])
