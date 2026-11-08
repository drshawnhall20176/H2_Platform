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
    best, worst = best_and_worst(bets, k=1, min_bets=MIN_N)      # a lane needs 10+ bets before it becomes a rule
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


# --------------------------------------------------------------------------- bet finder (Nov 8)
# Pick a sport, game and time; every bet on offer gets a plain verdict -- 🟢 Good bet / 🟡 Maybe / 🔴 Skip -- and the
# reasons in one line each. The checks, in order of how often they've cost money:
#   1. does the model think it wins at all (under 50% = skip; betting against the model went 21–47)
#   2. is the price cheap enough for the model's chance (chance minus what the price needs = the edge)
#   3. has this kind of pick (its Use tag) been winning lately (the 30-day record from pick_records)
#   4. how have YOU done at this price and in this sport/market (your own report card)
GOOD_EDGE = 0.03               # the model's chance must beat the price's break-even by 3 points to be a good bet
GOOD_CHANCE = 0.55


def _history(bets) -> Dict:
    lanes = {r["What"]: r for r in by_group(bets)}
    prices = list(price_check(bets))
    return {"lanes": lanes, "prices": prices}


def _price_row(hist: Dict, odds) -> Optional[Dict]:
    o = _num(odds)
    if o is None:
        return None
    for (name, lo, hi), r in ((p, next((x for x in hist["prices"] if x["What"] == p[0]), None)) for p in PRICES):
        if lo <= o <= hi:
            return r
    return None


def judge(c: Dict, hist: Dict, tag_rec: Optional[tuple] = None) -> Dict:
    """c: {"sport", "market", "chance", "price", "use", "tested"}. Returns {"verdict", "why", "edge", "need"}."""
    stop, warn, good = [], [], []
    chance, price = _num(c.get("chance")), _num(c.get("price"))
    model = chance
    if chance is not None and tag_rec and tag_rec[1] >= 50 and tag_rec[0] / tag_rec[1] < chance:
        chance = tag_rec[0] / tag_rec[1]                        # be realistic: the model runs high, use what's hit
        warn_real = f"model says {model:.0%}, but {_short(c.get('use'))} picks have really hit {chance:.0%} — using {chance:.0%}"
    else:
        warn_real = None
    need = breakeven(price)
    edge = None if chance is None or need is None else chance - need
    if chance is None:
        warn.append("no tested chance — the model's lean only")
    elif chance < 0.50:
        stop.append(f"the model gives it only {chance:.0%}")
    elif chance >= GOOD_CHANCE:
        good.append(f"model {chance:.0%}")
    if warn_real:
        good.insert(0, warn_real)
    if price is None:
        warn.append("no live price to check")
    elif edge is not None:
        if edge < 0:
            stop.append(f"price too expensive: {price:+.0f} needs {need:.0%}, model has {chance:.0%}")
        elif edge < GOOD_EDGE:
            warn.append(f"thin edge: {price:+.0f} needs {need:.0%}, model {chance:.0%}")
        else:
            good.append(f"{price:+.0f} needs {need:.0%} → edge {edge * 100:+.0f} pts")
    if c.get("use") and "Pass" in str(c["use"]):
        stop.append("the model's tested rules say pass")
    if tag_rec and tag_rec[1] >= 20:
        w, n = tag_rec
        if w / n < 0.5:
            stop.append(f"this kind of pick ({_short(c.get('use'))}) is {w}–{n - w} the last 30 days")
        else:
            good.append(f"{_short(c.get('use'))} is {w}–{n - w} lately")
    pr = _price_row(hist, price)
    if pr and pr["Bets"] >= MIN_N and str(pr["Verdict"]).startswith("🔴"):
        warn.append(f"you're {pr['Record']} ({usd(pr['Money'])}) at {pr['What']} prices")
    lane = hist["lanes"].get(f"{c.get('sport')} · {c.get('market')}")
    if lane and lane["Bets"] >= MIN_N:
        (good if (lane["Money"] or 0) > 0 else warn).append(
            f"your {c.get('sport')} {c.get('market')}: {lane['Record']} ({usd(lane['Money'])})")
    if c.get("tested") is False:
        warn.append("untested lean")
    if stop:
        v = "🔴 Skip"
    elif not warn and edge is not None and edge >= GOOD_EDGE and (chance or 0) >= GOOD_CHANCE:
        v = "🟢 Good bet"
    elif edge is not None and edge >= 0 and len(warn) <= 1:
        v = "🟡 Maybe"
    else:
        v = "🔴 Skip" if (edge is None and c.get("tested") is False) else "🟡 Maybe"
    return {"verdict": v, "why": "; ".join(stop + warn + good), "edge": edge, "need": need, "real_chance": chance,
            "model_chance": model}


def _short(use) -> str:
    return str(use or "").replace("🔒", "").replace("🎟️", "").replace("🎯", "").replace("⛔", "").strip() or "this tag"


def prop_candidates(sport: str, plays, meta=None) -> List[Dict]:
    """Every prop on the board that has a live price and a model chance."""
    import sports
    when = {}
    for m in meta or []:
        dt = sports.game_dt(m.get("game_date"))
        when[m.get("label")] = dt
    out = []
    for p in plays or []:
        price, chance = _num(p.get("RealPrice")), _num(p.get("ModelProb"))
        if price is None or chance is None:
            continue
        dt = when.get(p.get("Game"))
        line = _num(p.get("Line"))
        out.append({"sport": sport, "kind": "Prop", "game": p.get("Game") or "",
                    "time": p.get("Time") or (dt.strftime("%I:%M %p").lstrip("0") if dt else ""), "dt": dt,
                    "pick": f"{p.get('Player')} {p.get('Market')} {p.get('Side')}" + ("" if line is None else f" {line:g}"),
                    "market": p.get("Market"), "chance": chance, "price": price, "book": p.get("RealPriceBook") or "",
                    "use": p.get("Use") or "", "tested": True})
    return out


def lean_candidates(rows) -> List[Dict]:
    """Game lines from Today's best (winner rows): tested picks with their chance, untested leans without one."""
    out = []
    for r in rows or []:
        if not r.get("best"):
            continue
        tested = bool(r.get("best_tested"))
        out.append({"sport": r.get("sport"), "kind": "Game line", "game": r.get("game") or "", "time": r.get("time") or "",
                    "pick": r["best"], "market": r.get("bet_market") or "Game line",
                    "chance": r.get("best_chance") if tested else None,
                    "price": r.get("best_price") if tested else None, "book": "",
                    "use": r.get("use") or "", "tested": tested, "lean_verdict": r.get("lean_verdict")})
    return out


def finder(cands, bets, tag_records: Optional[Dict] = None) -> List[Dict]:
    """Each candidate judged; good bets first, then by edge."""
    hist = _history(bets)
    out = []
    for c in cands:
        tr = (tag_records or {}).get(_strip_use(c.get("use")))
        j = judge(c, hist, tr)
        if c.get("lean_verdict") in ("losing", "fade"):
            j["verdict"] = "🔴 Skip"
            j["why"] = "the model's leans in this market have been losing lately; " + j["why"]
        out.append({**c, **j})
    rank = {"🟢 Good bet": 0, "🟡 Maybe": 1, "🔴 Skip": 2}
    return sorted(out, key=lambda r: (rank.get(r["verdict"], 3), -(r["edge"] if r["edge"] is not None else -1)))


def _strip_use(use) -> str:
    return str(use or "").replace("🔒", "").strip()
