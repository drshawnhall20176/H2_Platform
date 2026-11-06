"""
investor.py — the numbers behind the Investor Relations section (Nov 6).

The question an investor asks of a betting-analytics product is "does the model have an edge, and how sure are you?"
So every figure here comes with its sample size and a 95% range, and each section says what it does and doesn't
show. Sources -- all already recorded by the platform, nothing re-graded here:

  locked calls      analyst_ledger (every Analyst Desk call, locked before the game and never edited)
  model reads       the latest morning review per sport (daily_review: results by Use tag, calibration)
  closing line      the Bet Log's entry vs closing prices (beating the close is the earliest, least noisy sign of edge)
  real money        the Bet Log, real-money bets only (shown, but labeled: a short record is mostly variance)
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

SPORTS = ("NFL", "NBA", "NHL", "NCAAF", "NCAAMB")


def wilson(hits: int, n: int, z: float = 1.96) -> Tuple[Optional[float], Optional[float]]:
    """95% range for a hit rate (Wilson score interval)."""
    if n <= 0:
        return None, None
    p = hits / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def verdict(n: int, hit: Optional[float], need: Optional[float], lo: Optional[float]) -> str:
    """Plain-English reading of a hit rate against what it needs (break-even or the model's own stated chance)."""
    if hit is None or n == 0:
        return "No graded results yet"
    if n < 100:
        return "Too early to tell"
    if need is not None and lo is not None and lo > need:
        return "Above what it needs, beyond chance"
    if need is not None and hit >= need:
        return "Above what it needs, not yet beyond chance"
    return "Below what it needs"


def locked_calls(rows: Sequence[Dict]) -> Dict:
    graded = [r for r in rows if r.get("hit") is not None]
    hits = sum(1 for r in graded if r["hit"])
    probs = [float(r["model_prob"]) for r in graded if r.get("model_prob") is not None]
    lo, hi = wilson(hits, len(graded))
    by = {}
    for r in graded:
        by.setdefault(r.get("sport") or "—", []).append(r)
    per = []
    for sp, g in sorted(by.items()):
        h = sum(1 for r in g if r["hit"])
        pr = [float(r["model_prob"]) for r in g if r.get("model_prob") is not None]
        l2, h2 = wilson(h, len(g))
        per.append({"sport": sp, "n": len(g), "hit": h / len(g), "said": (sum(pr) / len(pr)) if pr else None,
                    "lo": l2, "hi": h2})
    dates = sorted(str(r.get("call_date") or r.get("date") or "") for r in rows if r.get("call_date") or r.get("date"))
    return {"locked": len(rows), "n": len(graded), "hits": hits, "hit": (hits / len(graded)) if graded else None,
            "said": (sum(probs) / len(probs)) if probs else None, "lo": lo, "hi": hi, "by_sport": per,
            "first": dates[0] if dates else None, "last": dates[-1] if dates else None,
            "published": sum(1 for r in rows if r.get("published_at"))}


def use_tags(reports: Dict[str, Dict]) -> List[Dict]:
    """Per sport and Use tag, from each sport's latest morning review (its 30-day trend)."""
    out = []
    for sport, rep in reports.items():
        tr = (rep or {}).get("trend") or {}
        for row in tr.get("use") or []:
            n, hits = int(row.get("Graded") or 0), int(row.get("Hits") or 0)
            lo, hi = wilson(hits, n)
            out.append({"sport": sport, "use": row.get("Use"), "n": n, "hit": (hits / n) if n else None,
                        "said": row.get("Model said"), "lo": lo, "hi": hi, "morning": rep.get("morning"),
                        "days": tr.get("days"), "slates": tr.get("slates")})
    return out


def calibration(reports: Dict[str, Dict]) -> List[Dict]:
    out = []
    for sport, rep in reports.items():
        cal = (rep or {}).get("calibration") or {}
        for b in cal.get("buckets") or []:
            out.append({"sport": sport, "range": b.get("range"), "n": b.get("n"), "said": b.get("shown"),
                        "hit": b.get("hit")})
    return out


def closing_line(bets: Sequence[Dict]) -> Dict:
    import betlog as B
    money = B.money_bets(list(bets))
    clvs = [B.clv_pct(b.get("entry_odds"), b.get("close_odds")) for b in money if not B.is_parlay_header(b)]
    clvs = [c for c in clvs if c is not None]
    beat = sum(1 for c in clvs if c > 0)
    lo, hi = wilson(beat, len(clvs))
    return {"n": len(clvs), "beat": (beat / len(clvs)) if clvs else None, "avg": (sum(clvs) / len(clvs)) if clvs else None,
            "lo": lo, "hi": hi}


def real_money(bets: Sequence[Dict]) -> Dict:
    import betlog as B
    real = [b for b in bets if b.get("is_real_bet") not in (False, 0, "0", "false")]
    s = B.summary(real)
    singles = [b for b in B.money_bets(real) if not B.is_parlay_header(b) and not B._ticket(b)
               and B._result(b) in ("win", "loss")]
    w = sum(1 for b in singles if B._result(b) == "win")
    lo, hi = wilson(w, len(singles))
    dates = sorted(str(b.get("slate_date") or "") for b in real if b.get("slate_date"))
    return dict(s, singles=len(singles), singles_hit=(w / len(singles)) if singles else None, lo=lo, hi=hi,
                first=dates[0] if dates else None, last=dates[-1] if dates else None)


def bets_for_edge(edge: float = 0.03, price: int = -110) -> int:
    """Roughly how many bets at this price it takes before a true edge of `edge` (ROI) stands out from luck at 95%."""
    dec = 1 + (100 / -price if price < 0 else price / 100)
    p_be = 1 / dec
    p = p_be * (1 + edge)
    sd = math.sqrt(p * (1 - p))
    return int(math.ceil((1.96 * sd / (p - p_be)) ** 2))
