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


def pct(x) -> str:
    """One way to write a chance everywhere (the Why text and the table use the same one)."""
    return "—" if x is None else f"{x * 100:.1f}%"


def pts(x) -> str:
    return "—" if x is None else f"{x * 100:+.1f} pts"


NEW_MARKET_N = 50          # a market needs this many graded picks before its picks can be Good bets


def judge(c: Dict, hist: Dict, tag_rec: Optional[tuple] = None, market_n: Optional[int] = None) -> Dict:
    """c: {"sport", "market", "chance", "price", "use", "tested"}. Returns {"verdict", "signal", "why", "edge", "need",
    "model_chance", "real_chance"}. Every number in the Why text is the same number the table shows."""
    stop, warn, good = [], [], []
    model, price = _num(c.get("chance")), _num(c.get("price"))
    chance = model
    tag = _short(c.get("use"))
    if model is not None and tag_rec and tag_rec[1] >= 50 and tag_rec[0] / tag_rec[1] < model:
        chance = tag_rec[0] / tag_rec[1]                        # be realistic: the model runs high, use what's hit
        good.append(f"model says {pct(model)}, but {tag} picks have really hit {pct(chance)} — so the realistic "
                    f"chance is {pct(chance)}")
    word = "realistic chance" if chance != model else "model"
    need = breakeven(price)
    edge = None if chance is None or need is None else chance - need
    if chance is None:
        warn.append("no tested chance — the model's lean only")
    elif chance < 0.50:
        stop.append(f"{word} only {pct(chance)}")
    elif chance >= GOOD_CHANCE and word == "model" and price is None:     # with a price, the price line says it
        good.append(f"model {pct(chance)}")
    if price is None:
        warn.append("no live price to check")
    elif edge is not None:
        if edge < 0:
            stop.append(f"price too expensive: {price:+.0f} needs {pct(need)}, {word} {pct(chance)} → edge {pts(edge)}")
        elif edge < GOOD_EDGE:
            warn.append(f"thin edge: {price:+.0f} needs {pct(need)}, {word} {pct(chance)} → edge {pts(edge)}")
        else:
            good.append(f"{price:+.0f} needs {pct(need)}, {word} {pct(chance)} → edge {pts(edge)}")
    if c.get("use") and "Pass" in str(c["use"]):
        stop.append("the model's tested rules say pass")
    if tag_rec and tag_rec[1] >= 20:
        w, n = tag_rec
        if w / n < 0.5:
            stop.append(f"this kind of pick ({tag}) is {w}–{n - w} the last 30 days")
        else:
            good.append(f"{tag} is {w}–{n - w} lately")
    other = 0                                                   # cautions other than a thin edge
    pr = _price_row(hist, price)
    if pr and pr["Bets"] >= MIN_N and str(pr["Verdict"]).startswith("🔴"):
        warn.append(f"you're {pr['Record']} ({usd(pr['Money'])}) at {pr['What']} prices")
        other += 1
    lane = hist["lanes"].get(f"{c.get('sport')} · {c.get('market')}")
    if lane and lane["Bets"] >= MIN_N:
        if (lane["Money"] or 0) > 0:
            good.append(f"your {c.get('sport')} {c.get('market')}: {lane['Record']} ({usd(lane['Money'])})")
        else:
            warn.append(f"your {c.get('sport')} {c.get('market')}: {lane['Record']} ({usd(lane['Money'])})")
            other += 1
    if c.get("tested") is False:
        warn.append("untested lean")
        other += 1
    if c.get("kind") == "Prop" and market_n is not None and market_n < NEW_MARKET_N and str(c.get("use") or "").strip():
        # Nov 9: a market the props model only just started reading (NBA combos) -- its tag is real but its own
        # graded record isn't there yet, so it can be a Maybe, not a Good bet, until it has one
        warn.append(f"new market for the model — {market_n} graded so far (needs {NEW_MARKET_N})")
        other += 1
    unchecked = c.get("kind") == "Prop" and not str(c.get("use") or "").strip()
    if unchecked:
        # Nov 8-9: no Use tag = a market with no graded record (combos, blocks, steals); the model's chance can't be
        # checked against reality ("83%, +30 pt edge" on Nov 9). Its own group, never a Good bet or a Maybe.
        warn.append("no track record for this kind of pick — the model's chance is unchecked")
        other += 1
    if stop:
        v = "🔴 Skip"
    elif unchecked:
        v = "⚪ Unchecked"
    elif not warn and edge is not None and edge >= GOOD_EDGE and (chance or 0) >= GOOD_CHANCE:
        v = "🟢 Good bet"
    elif edge is not None and edge >= 0 and len(warn) <= 1:
        v = "🟡 Maybe"
    else:
        v = "🔴 Skip" if (edge is None and c.get("tested") is False) else "🟡 Maybe"
    return {"verdict": v, "signal": signal(v, edge, other), "why": "; ".join(stop + warn + good), "edge": edge,
            "need": need, "real_chance": chance, "model_chance": model}


SIGNALS = ("🟢 Go", "🟢 Small stake OK", "🟡 Tiny stake only", "🟠 Lean pass", "🔴 No")


def signal(verdict: str, edge: Optional[float], cautions: int = 0) -> str:
    """The row's stoplight. Good bets are 🟢, skips 🔴; a Maybe is graded by its edge, less a point per caution
    (your losing record at that price or in that market, an untested lean)."""
    if verdict.startswith("🟢"):
        return SIGNALS[0]
    if verdict.startswith("🔴"):
        return SIGNALS[4]
    if verdict.startswith("⚪"):
        return "⚪ Unchecked"
    if edge is None:
        return SIGNALS[3]
    score = edge * 100 - cautions
    return SIGNALS[1] if score >= 2 else SIGNALS[2] if score >= 1 else SIGNALS[3]


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
                    "use": p.get("Use") or "", "tested": True,
                    "player": p.get("Player"), "pid": p.get("PlayerId"), "side": p.get("Side"), "line": line})
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
                    "use": r.get("use") or "", "tested": tested, "lean_verdict": r.get("lean_verdict"),
                    # what the Bet Log needs to write a game-line bet (todays_best.bet_rows)
                    "_rec": r.get("_rec"), "bet_market": r.get("bet_market"), "bet_side": r.get("bet_side"),
                    "bet_line": r.get("bet_line"), "best_tested": tested, "best_chance": r.get("best_chance"),
                    "bet_price": r.get("bet_price")})
    return out


def finder(cands, bets, tag_records: Optional[Dict] = None, market_counts: Optional[Dict] = None) -> List[Dict]:
    """Each candidate judged; good bets first, then by edge."""
    hist = _history(bets)
    out = []
    for c in cands:
        tr = (tag_records or {}).get(_strip_use(c.get("use")))
        mn = None if market_counts is None else int((market_counts or {}).get(c.get("market"), 0))
        j = judge(c, hist, tr, mn)
        if c.get("lean_verdict") in ("losing", "fade"):
            j["verdict"] = "🔴 Skip"
            j["why"] = "the model's leans in this market have been losing lately; " + j["why"]
        out.append({**c, **j})
    rank = {"🟢 Good bet": 0, "🟡 Maybe": 1, "⚪ Unchecked": 2, "🔴 Skip": 3}
    sig = {k: i for i, k in enumerate(SIGNALS)}
    return sorted(out, key=lambda r: (rank.get(r["verdict"], 3), sig.get(r.get("signal"), 9),
                                      -(r["edge"] if r["edge"] is not None else -1)))


def _strip_use(use) -> str:
    return str(use or "").replace("🔒", "").strip()


# --------------------------------------------------------------------------- coaching guardrails (Nov 9)
# Nov 8 post-mortem: $47 of a $57 loss came from three 5-leg parlays; one was a same-game stack of untested combo
# props; most of the 1 PM slip had no model support; heavy-priced Unders the model overrated lost. So before a ticket is
# logged (or placed), it's graded: every leg through judge(), then the ticket itself -- legs, same-game stacking, the
# chance it hits, and the owner's own daily limits.
DEFAULT_LIMITS = {"daily_budget": 40.0, "stop_loss": 25.0, "max_legs": 3, "max_parlays": 2, "max_parlay_stake": 10.0}
LIMITS_KEY = "coach_limits"


def limits() -> Dict:
    try:
        import model_store as MS
        got = MS.get_setting(LIMITS_KEY) or {}
        if isinstance(got, str):
            import json
            got = json.loads(got)
        return {**DEFAULT_LIMITS, **{k: v for k, v in got.items() if k in DEFAULT_LIMITS}}
    except Exception:                                           # noqa: BLE001
        return dict(DEFAULT_LIMITS)


def save_limits(new: Dict) -> bool:
    try:
        import model_store as MS
        return bool(MS.save_setting(LIMITS_KEY, {k: new[k] for k in DEFAULT_LIMITS if k in new}))
    except Exception:                                           # noqa: BLE001
        return False


def today_so_far(bets: Sequence[Dict], day: str) -> Dict:
    """Real money staked today, settled P/L today, parlays placed today."""
    mine = [b for b in bets if _real(b) and _day(b) == day and (not B._ticket(b) or B.is_parlay_header(b))]
    staked = sum(_num(b.get("stake")) or 0.0 for b in mine)
    pl = sum(B.bet_pnl(b) or 0.0 for b in mine if B._result(b) in ("win", "loss", "push"))
    return {"staked": round(staked, 2), "pl": round(pl, 2), "parlays": sum(1 for b in mine if B.is_parlay_header(b)),
            "bets": len(mine), "open": sum(1 for b in mine if B._result(b) not in ("win", "loss", "push"))}


def _dec(odds) -> Optional[float]:
    o = _num(odds)
    if o is None or -100 < o < 100:
        return None
    return 1 + (o / 100 if o > 0 else 100 / -o)


def ticket_check(items: Sequence[Dict], mode: str, stake: float, parlay_stake: float, parlay_odds,
                 bets: Sequence[Dict], day: str, tag_records_for=None, lim: Optional[Dict] = None) -> Dict:
    """Grade a ticket before it's placed. Returns {"grade", "headline", "flags": [(level, text)], "legs": [...],
    "hit_chance", "ev"}; level is "red" (don't), "amber" (be careful) or "ok"."""
    lim = lim or limits()
    hist = _history(bets)
    flags, legs = [], []
    cache: Dict[str, Dict] = {}
    for it in items:
        sp = it.get("sport")
        if tag_records_for and sp not in cache:
            try:
                cache[sp] = tag_records_for(sp) or {}
            except Exception:                                   # noqa: BLE001
                cache[sp] = {}
        c = {"sport": sp, "market": it.get("market") or it.get("bet_market"), "kind": "Game line" if it.get("_rec") else "Prop",
             "chance": it.get("chance") if not it.get("_rec") else (it.get("best_chance") if it.get("best_tested") else None),
             "price": it.get("price"), "use": it.get("use") if it.get("use") is not None else "",
             "tested": bool(it.get("best_tested")) if it.get("_rec") else True}
        if not it.get("_rec") and it.get("use") is None:
            c["use"] = "?"                                      # came from a page that doesn't carry the tag: unknown
        j = judge(c, hist, cache.get(sp, {}).get(_strip_use(c["use"])))
        legs.append({**it, **j})
    singles_mode, parlay_mode = mode in ("Singles", "Both"), mode in ("Parlay", "Both")
    for l in legs:
        if l["verdict"].startswith("🔴"):
            flags.append(("red", f"{l.get('pick')}: Skip — {l['why'].split(';')[0]}"))
        elif l["verdict"].startswith("⚪"):
            flags.append(("amber", f"{l.get('pick')}: ⚪ no track record — the model's chance is unchecked"))
        elif l.get("signal") in ("🟠 Lean pass", "🟡 Tiny stake only"):
            flags.append(("amber", f"{l.get('pick')}: {l['signal']} — {l['why'].split(';')[0]}"))
    hit = None
    if parlay_mode and len(legs) >= 2:
        n = len(legs)
        if n > int(lim["max_legs"]):
            flags.append(("red", f"{n} legs — your limit is {int(lim['max_legs'])}. Every extra leg is another way to lose "
                                 "the whole ticket; Nov 8's three 5-leg parlays cost $47 of the $57 lost."))
        games = [l.get("game") for l in legs if l.get("game")]
        dup = {g for g in games if games.count(g) > 1}
        if dup:
            flags.append(("amber", f"{sum(games.count(g) for g in dup)} legs from the same game ({', '.join(sorted(dup))}) "
                                   "— they win or lose together (a shootout sinks every Under at once)."))
        # an unchecked chance (no track record for the pick type) can't be multiplied into a hit rate
        ch = [None if "no track record" in str(l.get("why")) else l.get("real_chance") for l in legs]
        if all(x is not None for x in ch):
            hit = 1.0
            for x in ch:
                hit *= x
        d = _dec(parlay_odds)
        if hit is not None and d:
            ev = hit * d - 1
            fair = (1 / hit - 1) * 100 if hit < 0.5 else -hit / (1 - hit) * 100
            same = " Same-game legs move together, so the real chance is less certain than this." if dup else ""
            msg = (f"Hits about {hit:.0%} of the time (1 in {1 / hit:.0f}); it pays {float(parlay_odds):+.0f}, fair is "
                   f"{fair:+.0f} → {'an edge' if ev > 0 else 'a losing price'} ({ev:+.0%} per $1).{same}")
            flags.append(("ok" if ev > 0 else "red", msg))
        elif hit is None:
            flags.append(("amber", "Some legs have no checked chance (no track record), so nobody can say how often "
                                   "this hits — or whether the price is fair."))
        if _num(parlay_stake) and _num(parlay_stake) > float(lim["max_parlay_stake"]):
            flags.append(("red", f"${float(parlay_stake):.0f} on a parlay — your limit is ${float(lim['max_parlay_stake']):.0f}."))
    t = today_so_far(bets, day)
    new_stake = (len(legs) * float(stake or 0) if singles_mode else 0) + (float(parlay_stake or 0) if parlay_mode else 0)
    if t["pl"] <= -float(lim["stop_loss"]):
        flags.append(("red", f"You're {usd(t['pl'])} today — past your stop-loss of ${float(lim['stop_loss']):.0f}. "
                             "Chasing is how Nov 8's $20 night parlay happened. Done for today."))
    if t["staked"] + new_stake > float(lim["daily_budget"]):
        flags.append(("red", f"This brings today to ${t['staked'] + new_stake:.0f} staked — your budget is "
                             f"${float(lim['daily_budget']):.0f}."))
    if parlay_mode and t["parlays"] >= int(lim["max_parlays"]):
        flags.append(("red", f"You've placed {t['parlays']} parlay(s) today — your limit is {int(lim['max_parlays'])}."))
    reds = sum(1 for lv, _ in flags if lv == "red")
    ambers = sum(1 for lv, _ in flags if lv == "amber")
    grade = "A" if not reds and not ambers else "B" if not reds and ambers <= 1 else "C" if not reds else \
        "D" if reds == 1 else "F"
    headline = {"A": "✅ Good ticket — place it at your normal stake.",
                "B": "🟢 Fine — one thing to watch below.",
                "C": "🟡 Shaky — trim the flagged legs or halve the stake.",
                "D": "🟠 Fix the red item before you place this.",
                "F": "🔴 Don't place this ticket as it is."}[grade]
    ev = None
    if hit is not None and _dec(parlay_odds):
        ev = hit * _dec(parlay_odds) - 1
    return {"grade": grade, "headline": headline, "flags": flags, "legs": legs, "hit_chance": hit, "ev": ev,
            "today": t}


def lessons(bets: Sequence[Dict], day: str) -> List[str]:
    """Plain-English lessons from one day's settled real bets (the morning-after review)."""
    mine = [b for b in bets if _real(b) and _day(b) == day]
    money = [b for b in mine if (not B._ticket(b) or B.is_parlay_header(b)) and B._result(b) in ("win", "loss", "push")]
    if not money:
        return []
    out = []
    total = _money(money)
    par = [b for b in money if B.is_parlay_header(b)]
    sing = [b for b in money if not B.is_parlay_header(b)]
    pl_par, pl_sing = _money(par), _money(sing)
    w, l = _wl(sing)
    out.append(f"**The day: {usd(total)}.** Singles {w}–{l} ({usd(pl_sing)}); parlays {sum(B._result(b) == 'win' for b in par)}"
               f"–{sum(B._result(b) == 'loss' for b in par)} ({usd(pl_par)}).")
    if par and pl_par < 0 and total < 0 and pl_par <= 0.6 * total:
        big = [b for b in par if (_num(b.get("entry_odds")) or 0) >= 1000]
        out.append(f"**Parlays were the leak:** {usd(pl_par)} of the {usd(total)}."
                   + (f" {len(big)} paid +1000 or more — long shots that hit less than 1 time in 10." if big else ""))
    picks = [b for b in mine if not B.is_parlay_header(b) and B._result(b) in ("win", "loss")]
    unbacked = [b for b in picks if _num(b.get("model_prob")) is None or _num(b.get("model_prob")) < 0.5]
    if len(unbacked) >= 2:
        uw, ul = _wl(unbacked)
        out.append(f"**{len(unbacked)} of your {len(picks)} picks had no model support** (under 50% or no read): "
                   f"{uw}–{ul}. Check Find a bet first — if it isn't 🟢 or a 🟢 Small-stake Maybe, skip it.")
    heavy = [b for b in picks if (_num(b.get("entry_odds")) or 0) <= -150 and not B._ticket(b)]
    if heavy:
        hw, hl = _wl(heavy)
        out.append(f"**Heavy prices (−150 or worse): {hw}–{hl}.** At −150 you must win 60% just to break even.")
    tick = defaultdict(list)
    for b in mine:
        if B._ticket(b) and not B.is_parlay_header(b):
            tick[B._ticket(b)].append(b)
    for t, ls in tick.items():
        games = [x.get("game") for x in ls if x.get("game")]
        if games and max(games.count(g) for g in games) >= 3:
            g = max(set(games), key=games.count)
            out.append(f"**{t}: {games.count(g)} legs from one game ({g}).** They rise and fall together — one game "
                       "script sank the ticket.")
    good = [b for b in picks if (_num(b.get("model_prob")) or 0) >= 0.6]
    if good:
        gw, gl = _wl(good)
        out.append(f"Picks the model rated 60%+: {gw}–{gl}.")
    return out


def why_nothing(judged: Sequence[Dict], sport: str) -> Optional[str]:
    """When a sport has no Good bets or Maybes, the plain reason (Nov 9: 'is something broken?' -- usually not)."""
    if any(r["verdict"].startswith(("🟢", "🟡")) for r in judged):
        return None
    if not judged:
        return None
    n = len(judged)
    props = [r for r in judged if r.get("kind") == "Prop"]
    lines = [r for r in judged if r.get("kind") != "Prop"]
    passed = sum(1 for r in props if "Pass" in str(r.get("use")))
    unchecked = sum(1 for r in judged if r["verdict"].startswith("⚪"))
    bits = []
    if props and passed == len(props):
        bits.append(f"all {len(props)} player props are tagged ⛔ Pass by the model's tested rules — it sees no edge it "
                    "trusts")
    elif props:
        bits.append(f"{passed} of {len(props)} player props are tagged ⛔ Pass and the rest are priced too high for "
                    "their chance")
    if lines and all(not r.get("tested") for r in lines):
        bits.append(f"the {len(lines)} game leans are untested (tracking only)")
    if unchecked:
        bits.append(f"{unchecked} have no track record (⚪ Unchecked)")
    return (f"Nothing to bet in {sport} right now: " + "; ".join(bits) + ". That's the coach working — no bet is the "
            "right bet when nothing clears the bar.") if bits else None
