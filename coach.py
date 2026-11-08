"""
coach.py — My Coach (Nov 8): plain tables from your own settled real-money bets that steer the next choice.

The owner asked for something elementary while he learns: what makes money, what costs money, how betting against the
model has gone, and whether the price is eating the wins. Every table here is built from the Bet Log, so it updates
each morning as bets settle -- the personal half of the daily feedback loop.

Money is counted the way the Reports page counts it (singles and parlay tickets once each). Pick accuracy (the model
bands) counts singles and parlay legs, because each leg is a choice you made.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence

import betlog as B

MIN_N = 10                     # under this many bets a row says "too early to tell"
BANDS = ("Model liked it a lot (60%+)", "Model liked it (55–60%)", "Model barely liked it (50–55%)",
         "Against the model (under 50%)", "No model number")
PRICES = (("Plus money (+100 or more)", 100, 10_000), ("−100 to −125", -125, -100), ("−126 to −150", -150, -126),
          ("−151 to −200", -200, -151), ("Worse than −200", -100_000, -201))


def _num(v) -> Optional[float]:
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _real(b: Dict) -> bool:
    return b.get("is_real_bet") not in (False, 0, "0", "false", "False", None)


def _day(b: Dict) -> str:
    return str(b.get("slate_date") or b.get("created_at") or "")[:10]


def in_period(bets: Sequence[Dict], days: Optional[int], today: Optional[date] = None) -> List[Dict]:
    if not days:
        return list(bets)
    cut = ((today or date.today()) - timedelta(days=days)).isoformat()
    return [b for b in bets if _day(b) >= cut]


def money_rows(bets: Sequence[Dict]) -> List[Dict]:
    """Settled real-money bets, each counted once (singles and parlay tickets)."""
    real = [b for b in bets if _real(b)]
    return [b for b in B.money_bets(real) if B._result(b) in ("win", "loss", "push") and B.bet_pnl(b) is not None]


def pick_rows(bets: Sequence[Dict]) -> List[Dict]:
    """Settled real picks: singles and parlay legs (not the parlay ticket itself)."""
    return [b for b in bets if _real(b) and not B.is_parlay_header(b) and B._result(b) in ("win", "loss")]


def is_parlay(b: Dict) -> bool:
    return B.is_parlay_header(b) or bool(B._ticket(b))


def band_of(b: Dict) -> str:
    mp = _num(b.get("model_prob"))
    if mp is None:
        return BANDS[4]
    return BANDS[0] if mp >= 0.60 else BANDS[1] if mp >= 0.55 else BANDS[2] if mp >= 0.50 else BANDS[3]


def breakeven(odds) -> Optional[float]:
    """The win rate a price needs just to break even (-110 -> 52.4%)."""
    o = _num(odds)
    if o is None or -100 < o < 100:
        return None
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def grade(n: int, money: Optional[float], win: Optional[float] = None, need: Optional[float] = None) -> str:
    if n < MIN_N:
        return "⚪ Too early to tell"
    if money is not None:
        if money > 0:
            return "🟢 Keep doing this"
        if win is not None and need is not None and win >= need - 0.02:
            return "🟡 Close — watch the price"
        return "🔴 Stop or shrink this"
    if win is not None and need is not None:
        return "🟢 Keep doing this" if win >= need else "🔴 Stop or shrink this"
    return "🟡 Not sure yet"


def _wl(rows) -> tuple:
    w = sum(B._result(b) == "win" for b in rows)
    l = sum(B._result(b) == "loss" for b in rows)
    return w, l


def _money(rows) -> float:
    return round(sum(B.bet_pnl(b) or 0.0 for b in rows), 2)


def _avg_need(rows) -> Optional[float]:
    xs = [x for x in (breakeven(b.get("entry_odds")) for b in rows) if x is not None]
    return sum(xs) / len(xs) if xs else None


def _row(what: str, picks: Sequence[Dict], money: Optional[Sequence[Dict]]) -> Dict:
    w, l = _wl(picks)
    n = w + l
    win = w / n if n else None
    need = _avg_need(money if money is not None else picks)
    m = _money(money) if money is not None else None
    return {"What": what, "Bets": n, "Record": f"{w}–{l}", "Win %": win,
            "Need to win": need, "Money": m, "Verdict": grade(n, m if money else None, win, need)}


def report_card(bets: Sequence[Dict]) -> List[Dict]:
    """One line per kind of choice: all bets, singles, parlays, then your singles by how much the model liked them."""
    money = money_rows(bets)
    singles = [b for b in money if not is_parlay(b)]
    parlays = [b for b in money if is_parlay(b)]
    out = [_row("Everything", money, money), _row("Single bets", singles, singles),
           _row("Parlays (each ticket once)", parlays, parlays)]
    picks = pick_rows(bets)
    for band in BANDS:
        p = [b for b in picks if band_of(b) == band]
        if not p:
            continue
        s = [b for b in singles if band_of(b) == band]
        r = _row(band, p, s if s else None)
        r["Money"] = _money(s) if s else None
        r["Verdict"] = grade(r["Bets"], r["Money"] if s else None, r["Win %"], r["Need to win"])
        out.append(r)
    return out


def by_group(bets: Sequence[Dict]) -> List[Dict]:
    """Singles by sport and market, plus parlays by sport, with their money -- sorted best to worst."""
    g = defaultdict(list)
    for b in money_rows(bets):
        key = f"{b.get('sport') or '?'} · parlays" if is_parlay(b) else f"{b.get('sport') or '?'} · {b.get('market') or '?'}"
        g[key].append(b)
    rows = [_row(k, v, v) for k, v in g.items()]
    return sorted(rows, key=lambda r: -(r["Money"] or 0))


def best_and_worst(bets: Sequence[Dict], k: int = 5, min_bets: int = 3):
    rows = [r for r in by_group(bets) if r["Bets"] >= min_bets]
    best = [r for r in rows if (r["Money"] or 0) > 0][:k]
    worst = [r for r in reversed(rows) if (r["Money"] or 0) < 0][:k]
    return best, worst


def against_model(bets: Sequence[Dict]) -> Dict:
    """Your picks where the model gave under 50%: by sport, and the most recent ones."""
    picks = [b for b in pick_rows(bets) if band_of(b) == BANDS[3]]
    money = {b.get("id") for b in money_rows(bets) if not is_parlay(b)}
    g = defaultdict(list)
    for b in picks:
        g[b.get("sport") or "?"].append(b)
    by_sport = []
    for sp, rows in sorted(g.items(), key=lambda kv: -len(kv[1])):
        singles = [b for b in rows if b.get("id") in money]
        r = _row(sp, rows, singles if singles else None)
        r["Money"] = _money(singles) if singles else None
        by_sport.append(r)
    recent = sorted(picks, key=lambda b: (_day(b), b.get("id") or 0), reverse=True)[:10]
    return {"by_sport": by_sport,
            "recent": [{"Date": _day(b), "Sport": b.get("sport"), "Pick": describe(b),
                        "Model said": _num(b.get("model_prob")), "Result": "✅ won" if B._result(b) == "win" else "❌ lost"}
                       for b in recent]}


def describe(b: Dict) -> str:
    who = b.get("player") or ""
    line = _num(b.get("line"))
    bits = [who, b.get("market") or "", b.get("side") or "", "" if line is None else f"{line:g}"]
    return " ".join(x for x in bits if x).strip() or (b.get("game") or "")


def price_check(bets: Sequence[Dict]) -> List[Dict]:
    """Single bets by price: how often you win at each price, and how often that price needs you to win."""
    singles = [b for b in money_rows(bets) if not is_parlay(b)]
    out = []
    for name, lo, hi in PRICES:
        rows = [b for b in singles if _num(b.get("entry_odds")) is not None and lo <= _num(b["entry_odds"]) <= hi]
        if rows:
            out.append(_row(name, rows, rows))
    return out


def usd(x) -> str:
    return f"+${x:,.2f}" if x >= 0 else f"−${-x:,.2f}"


def rules(bets: Sequence[Dict]) -> List[str]:
    """Plain-English rules from the tables above. Only rules the data backs (10+ bets) are written."""
    out = []
    card = {r["What"]: r for r in report_card(bets)}
    strong, against = card.get(BANDS[0]), card.get(BANDS[3])
    if against and against["Bets"] >= MIN_N and (against["Win %"] or 0) < 0.45:
        out.append(f"**Don't bet against the model.** When you did, you went {against['Record']} "
                   f"({against['Win %']:.0%}). If the model is under 50% on a pick, skip it.")
    mid = card.get(BANDS[1])
    if mid and mid["Bets"] >= MIN_N and (mid["Money"] or 0) > 0:
        out.append(f"**The 55–60% picks have paid you** ({mid['Record']}, {usd(mid['Money'])}). They are often "
                   "cheaper than the 60%+ picks, so the price leaves room to profit.")
    if strong and strong["Bets"] >= MIN_N and strong["Need to win"] and (strong["Money"] or 0) < 0:
        out.append(f"**Strong picks win, but the price eats it.** Your 60%+ singles won {strong['Win %']:.0%}, yet the "
                   f"prices needed {strong['Need to win']:.0%}. Only bet them at about −125 or better.")
    for r in price_check(bets):
        if r["Bets"] >= MIN_N and (r["Money"] or 0) < 0 and r["What"] in ("−151 to −200", "Worse than −200"):
            out.append(f"**Avoid {r['What']} prices.** You need to win {r['Need to win']:.0%} there and won "
                       f"{r['Win %']:.0%} ({usd(r['Money'])}).")
    best, worst = best_and_worst(bets, k=1, min_bets=5)
    if best:
        out.append(f"**Your best lane: {best[0]['What']}** ({best[0]['Record']}, {usd(best[0]['Money'])}). Look there first.")
    if worst:
        out.append(f"**Your biggest leak: {worst[0]['What']}** ({worst[0]['Record']}, {usd(worst[0]['Money'])}). "
                   "Bet it smaller or skip it until it turns around.")
    par = card.get("Parlays (each ticket once)")
    if par and par["Bets"] >= MIN_N and (par["Money"] or 0) > 0:
        out.append(f"**Small parlays have worked for you** ({par['Record']}, {usd(par['Money'])}). Keep them small: "
                   "most parlays lose, and one hit pays for many misses.")
    if not out:
        out.append("Not enough settled bets in this period to write rules yet. Try a longer period.")
    return out
