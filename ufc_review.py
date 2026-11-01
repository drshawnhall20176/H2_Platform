"""
ufc_review.py — UFC in the morning review (Nov 1).

The platform has no UFC model yet (the Fight Card page shows the market's prices), so this grades THE MARKET and your
own bets, card by card:

  1. capture(): the books' moneyline and rounds over/under for every upcoming bout, with the vig removed (the median of
     every US book's no-vig price), saved before each bout starts (model_store.ufc_odds). Run by the capture-ufc-odds
     workflow through fight day, and whenever the Fight Card page loads a bout.
  2. card_results(): every bout of a card from ESPN -- winner, method (KO/TKO, submission, decision, draw, no
     contest), round and time.
  3. grade_card() / summarize(): each bout against its saved prices -- did the favorite win, did it end early, did the
     over/under land -- and the card's record: favorites, big favorites, upsets, finishes, overs, and how close the
     market's probabilities came (Brier score).
  4. settle(): open UFC bets in the Bet Log -- moneyline, fight duration, method of victory -- by fighter name.
  5. recap(): a short, Discord-ready summary of the card.

review() puts it together for daily_review.py; the report shows on Postgame Review (sport: UFC).
"""
from __future__ import annotations

import re
import statistics
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
ODDS_URL = "https://api.the-odds-api.com/v4/sports/mma_mixed_martial_arts/odds"
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard"
BIG_FAVORITE = 0.70
TREND_DAYS = 120
FAV_BANDS = ((0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 1.01))


def _http(url: str, params: Optional[Dict] = None):
    import requests
    try:
        r = requests.get(url, params=params or {}, timeout=20, headers={"User-Agent": "H2Sports/1.0"})
        return r.json() if r.ok else None
    except Exception:                                           # noqa: BLE001
        return None


def norm(name) -> str:
    t = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z ]", " ", t.replace("'", "")).split())


def _num(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def implied(american) -> Optional[float]:
    a = _num(american)
    if a is None or a == 0:
        return None
    return 100.0 / (a + 100.0) if a > 0 else -a / (-a + 100.0)


def no_vig(a, b) -> Optional[Tuple[float, float]]:
    pa, pb = implied(a), implied(b)
    if pa is None or pb is None or pa + pb <= 0:
        return None
    return pa / (pa + pb), pb / (pa + pb)


def card_date_of(iso_utc: Optional[str]) -> Optional[str]:
    """The card's calendar day in New York (a 10 PM ET main event is "tomorrow" in UTC)."""
    if not iso_utc:
        return None
    try:
        d = datetime.fromisoformat(str(iso_utc).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(ET).date().isoformat()


def _started(iso_utc: Optional[str], now: datetime) -> bool:
    try:
        return datetime.fromisoformat(str(iso_utc).replace("Z", "+00:00")) <= now
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------- 1. prices before the bout
def record_from_event(ev: Dict, ts: Optional[str] = None) -> Optional[Dict]:
    """One Odds API MMA event (a bout, every bookmaker) -> the saved price record, or None without a moneyline."""
    a, b = ev.get("home_team"), ev.get("away_team")
    if not a or not b:
        return None
    p_a, best_a, best_b, totals = [], None, None, []
    for bm in ev.get("bookmakers") or []:
        for mk in bm.get("markets") or []:
            outs = {o.get("name"): o for o in mk.get("outcomes") or []}
            if mk.get("key") == "h2h" and a in outs and b in outs:
                pa_, pb_ = outs[a].get("price"), outs[b].get("price")
                nv = no_vig(pa_, pb_)
                if nv:
                    p_a.append(nv[0])
                if pa_ is not None and (best_a is None or pa_ > best_a[1]):
                    best_a = (bm.get("key"), pa_)
                if pb_ is not None and (best_b is None or pb_ > best_b[1]):
                    best_b = (bm.get("key"), pb_)
            elif mk.get("key") == "totals" and "Over" in outs and "Under" in outs:
                pt = _num(outs["Over"].get("point"))
                if pt is not None:
                    totals.append((pt, outs["Over"].get("price"), outs["Under"].get("price"), bm.get("key")))
    if not p_a:
        return None
    rec = {"event_id": ev.get("id"), "commence": ev.get("commence_time"), "card_date": card_date_of(ev.get("commence_time")),
           "fighter_a": a, "fighter_b": b, "p_a": round(statistics.median(p_a), 4), "books": len(p_a),
           "best_a": list(best_a) if best_a else None, "best_b": list(best_b) if best_b else None,
           "total_point": None, "p_over": None, "best_over": None, "best_under": None,
           "ts": ts or datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if totals:
        point = statistics.mode([t[0] for t in totals])
        at = [t for t in totals if t[0] == point]
        po = [nv[0] for nv in (no_vig(t[1], t[2]) for t in at) if nv]
        rec.update(total_point=point, p_over=round(statistics.median(po), 4) if po else None,
                   best_over=list(max(((t[3], t[1]) for t in at if t[1] is not None), key=lambda x: x[1], default=(None, None))),
                   best_under=list(max(((t[3], t[2]) for t in at if t[2] is not None), key=lambda x: x[1], default=(None, None))))
    return rec


def capture(api_key: str, fetch: Callable = _http, now: Optional[datetime] = None, db_path: Optional[str] = None) -> int:
    """Save the current prices of every bout that hasn't started. One request (2 credits) covers every card."""
    import model_store as MS
    now = now or datetime.now(timezone.utc)
    data = fetch(ODDS_URL, {"apiKey": api_key, "regions": "us", "markets": "h2h,totals", "oddsFormat": "american"})
    recs = [record_from_event(ev) for ev in (data or []) if not _started(ev.get("commence_time"), now)]
    return MS.save_ufc_odds([r for r in recs if r], db_path=db_path)


# --------------------------------------------------------------------------- 2. results
_METHOD = (("no contest", "No Contest"), ("draw", "Draw"), ("kotko", "KO/TKO"), ("ko", "KO/TKO"),
           ("submission", "Submission"), ("decision", "Decision"))


def _clock_secs(text) -> Optional[float]:
    m = re.match(r"^(\d+):(\d{2})$", str(text or "").strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def card_results(card_date: str, fetch: Callable = _http) -> List[Dict]:
    """Every bout ESPN lists for the card that day: {"fighters", "winner", "method", "round", "clock", "rounds",
    "elapsed" (rounds fought, e.g. 2.28), "final", "event", "weight"}."""
    data = fetch(ESPN_URL, {"dates": card_date.replace("-", "")}) or {}
    out = []
    for ev in data.get("events") or []:
        for c in ev.get("competitions") or []:
            names = [(x.get("athlete") or {}).get("displayName") for x in c.get("competitors") or []]
            if len(names) != 2 or not all(names):
                continue
            winner = next(((x.get("athlete") or {}).get("displayName") for x in c["competitors"] if x.get("winner")), None)
            st = c.get("status") or {}
            rnd = int(st.get("period") or 0) or None
            secs = _clock_secs(st.get("displayClock"))
            rounds = int(((c.get("format") or {}).get("regulation") or {}).get("periods") or 3)
            text = next((d["type"]["text"] for d in c.get("details") or []
                         if re.search(r"winner|draw|no contest", (d.get("type") or {}).get("text", ""), re.I)), "")
            method = next((m for k, m in _METHOD if k in text.lower()), None)
            if method is None and rnd and secs is not None:
                method = "Decision" if (rnd == rounds and secs >= 300) else ("Finish" if winner else None)
            elapsed = rounds if method in ("Decision", "Draw") else (
                (rnd - 1) + (secs or 0) / 300.0 if rnd else None)
            out.append({"fighters": names, "winner": winner, "method": method, "round": rnd,
                        "clock": st.get("displayClock"), "rounds": rounds, "elapsed": elapsed,
                        "final": bool(((st.get("type") or {}).get("completed"))), "event": ev.get("name"),
                        "weight": (c.get("type") or {}).get("abbreviation")})
    return out


def _same(a, b) -> bool:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta, tb = na.split(), nb.split()
    return ta[-1] == tb[-1] and ta[0][0] == tb[0][0]          # "JeongYeong Lee" / "Jeong Yeong Lee"


def find_bout(bouts: Sequence[Dict], a, b) -> Optional[Dict]:
    for bt in bouts:
        f1, f2 = bt["fighters"]
        if (_same(a, f1) and _same(b, f2)) or (_same(a, f2) and _same(b, f1)):
            return bt
    return None


# --------------------------------------------------------------------------- 3. grading the card
def grade_card(bouts: Sequence[Dict], prices: Sequence[Dict]) -> List[Dict]:
    """Each bout with its saved prices: favorite, its chance, whether it won, how it ended, the over/under."""
    out = []
    for bt in bouts:
        f1, f2 = bt["fighters"]
        rec = next((p for p in prices if (_same(p["fighter_a"], f1) and _same(p["fighter_b"], f2))
                    or (_same(p["fighter_a"], f2) and _same(p["fighter_b"], f1))), None)
        row = dict(bt, fav=None, fav_p=None, dog=None, fav_won=None, total_point=None, p_over=None, over=None)
        if rec:
            pa = float(rec["p_a"])
            fav, dog, fp = (rec["fighter_a"], rec["fighter_b"], pa) if pa >= 0.5 else (rec["fighter_b"], rec["fighter_a"], 1 - pa)
            row.update(fav=fav, dog=dog, fav_p=fp)
            if bt["final"] and bt["winner"] and bt["method"] not in ("Draw", "No Contest"):
                row["fav_won"] = _same(bt["winner"], fav)
            tp = _num(rec.get("total_point"))
            if tp is not None:
                row.update(total_point=tp, p_over=rec.get("p_over"))
                if bt["final"] and bt["elapsed"] is not None and bt["method"] != "No Contest":
                    row["over"] = bt["elapsed"] > tp
        out.append(row)
    return out


def summarize(rows: Sequence[Dict]) -> Dict:
    final = [r for r in rows if r["final"]]
    priced = [r for r in final if r["fav_won"] is not None]
    fav_w = sum(1 for r in priced if r["fav_won"])
    big = [r for r in priced if r["fav_p"] >= BIG_FAVORITE]
    upsets = sorted(([r["dog"], r["fav"], round(1 - r["fav_p"], 3)] for r in priced if not r["fav_won"]),
                    key=lambda u: u[2])
    finishes = sum(1 for r in final if r["method"] in ("KO/TKO", "Submission", "Finish"))
    tot = [r for r in final if r["over"] is not None]
    brier = (sum((r["fav_p"] - (1.0 if r["fav_won"] else 0.0)) ** 2 for r in priced) / len(priced)) if priced else None
    return {"bouts": len(rows), "final": len(final), "priced": len(priced),
            "favorites": {"won": fav_w, "lost": len(priced) - fav_w,
                          "expected": round(sum(r["fav_p"] for r in priced), 2)},
            "big_favorites": {"won": sum(1 for r in big if r["fav_won"]), "graded": len(big)},
            "upsets": upsets, "finishes": finishes, "decisions": sum(1 for r in final if r["method"] == "Decision"),
            "ko": sum(1 for r in final if r["method"] == "KO/TKO"), "subs": sum(1 for r in final if r["method"] == "Submission"),
            "totals": {"over": sum(1 for r in tot if r["over"]), "under": sum(1 for r in tot if not r["over"]),
                       "expected_over": round(sum((r["p_over"] or 0.5) for r in tot), 2)},
            "brier": round(brier, 4) if brier is not None else None}


def bands(rows: Iterable[Dict]) -> List[Dict]:
    """Across cards: how often favorites in each price band won vs what the price said."""
    rows = [r for r in rows if r.get("fav_won") is not None]
    out = []
    for lo, hi in FAV_BANDS:
        g = [r for r in rows if lo <= r["fav_p"] < hi]
        if g:
            out.append({"band": f"{lo:.0%}–{min(hi, 1.0):.0%}", "bouts": len(g),
                        "won": sum(1 for r in g if r["fav_won"]) / len(g),
                        "priced_at": sum(r["fav_p"] for r in g) / len(g)})
    return out


# --------------------------------------------------------------------------- 4. your bets
_METHOD_MARKET = {"win by ko/tko": "KO/TKO", "win by sub": "Submission", "win by submission": "Submission",
                  "win by decision": "Decision"}


def bet_result(bet: Dict, bout: Dict) -> Optional[str]:
    """win / loss / push for one UFC bet against its final bout; None when it can't be decided from the result."""
    if not bout or not bout["final"]:
        return None
    market = str(bet.get("market") or "").strip().lower()
    side = bet.get("side")
    void = bout["method"] in ("Draw", "No Contest") or not bout["winner"]
    if market == "moneyline":
        if void:
            return "push"
        return "win" if _same(side, bout["winner"]) else "loss"
    if market == "fight duration":
        line, el = _num(bet.get("line")), bout["elapsed"]
        if line is None or el is None or bout["method"] == "No Contest":
            return None if line is None else "push"
        over = el > line
        return "win" if (over == (str(side).lower() == "over")) else "loss"
    if market in _METHOD_MARKET:
        if bout["method"] == "No Contest":
            return "push"
        return "win" if (bout["winner"] and _same(side, bout["winner"]) and bout["method"] == _METHOD_MARKET[market]) else "loss"
    return None


def _game_fighters(game) -> Tuple[Optional[str], Optional[str]]:
    parts = re.split(r"\s+vs\.?\s+", str(game or ""), flags=re.I)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (None, None)


def settle(open_bets: Sequence[Dict], bouts_by_date: Dict[str, List[Dict]], write: bool = True,
           bet_db: Optional[str] = None) -> Dict:
    import betlog as B
    kw = {"db_path": bet_db} if bet_db else {}
    settled, unresolved = [], []
    for bet in open_bets:
        if (bet.get("sport") or "") != "UFC" or bet.get("result"):
            continue
        a, b = _game_fighters(bet.get("game"))
        bouts = [bt for d, lst in bouts_by_date.items() for bt in lst]
        bout = find_bout(bouts, a, b) if a else None
        desc = f"{bet.get('game')} · {bet.get('market')} {bet.get('side')}" + (f" {bet.get('line')}" if bet.get("line") else "")
        if bout is None:
            if str(bet.get("slate_date") or "") in bouts_by_date:
                unresolved.append({"bet_id": bet.get("id"), "description": desc, "why": "bout not found on ESPN's card"})
            continue
        res = bet_result(bet, bout)
        if res is None:
            unresolved.append({"bet_id": bet.get("id"), "description": desc, "why": "couldn't decide it from the result"})
            continue
        try:
            if write:
                B.update_bet(bet["id"], result=res, **kw)
            settled.append({"bet_id": bet.get("id"), "description": desc,
                            "actual": f"{bout['winner'] or '—'} · {bout['method'] or ''} R{bout['round'] or '?'}",
                            "result": res})
        except Exception as exc:                                    # noqa: BLE001
            unresolved.append({"bet_id": bet.get("id"), "description": desc, "why": f"couldn't save ({type(exc).__name__})"})
    return {"settled": settled, "tickets": [], "unresolved": unresolved, "still_pending": []}


# --------------------------------------------------------------------------- 5. recap
def recap(event: str, card_date: str, s: Dict, rows: Sequence[Dict]) -> str:
    lines = [f"🥊 **{event or 'UFC'} — card recap ({card_date})**", ""]
    if s["priced"]:
        f = s["favorites"]
        lines.append(f"• Favorites went **{f['won']}-{f['lost']}** (the prices said about {f['expected']:.1f} wins).")
        if s["big_favorites"]["graded"]:
            bf = s["big_favorites"]
            lines.append(f"• Big favorites (70%+): {bf['won']} of {bf['graded']}.")
        if s["upsets"]:
            lines.append("• Upsets: " + "; ".join(f"{d} over {fv} ({p:.0%})" for d, fv, p in s["upsets"][:4]) + ".")
    lines.append(f"• {s['finishes']} finishes ({s['ko']} KO/TKO, {s['subs']} submissions) and {s['decisions']} decisions "
                 f"across {s['final']} bouts.")
    if s["totals"]["over"] + s["totals"]["under"]:
        t = s["totals"]
        lines.append(f"• Rounds totals: {t['over']} overs, {t['under']} unders.")
    main = next((r for r in rows if r.get("rounds") == 5), rows[-1] if rows else None)
    if main and main.get("winner"):
        lines.append(f"• Main event: **{main['winner']}** by {main['method'] or 'result'}"
                     + (f" (R{main['round']} {main['clock']})" if main["method"] not in ("Decision", None) else "") + ".")
    lines += ["", "Graded against the closing market every morning, win or lose. 📊"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- the morning
def review(morning: str, open_bets: Sequence[Dict], fetch: Callable = _http, db_path: Optional[str] = None,
           write: bool = True, bet_db: Optional[str] = None) -> Optional[Dict]:
    """Yesterday's card (if there was one) graded against its saved prices, the trend across cards, and open UFC bets
    settled. None when there was no card and no open UFC bet."""
    import model_store as MS
    yday = (date.fromisoformat(morning) - timedelta(days=1)).isoformat()
    open_ufc = [b for b in open_bets if (b.get("sport") or "") == "UFC" and not b.get("result")]
    bout_dates = sorted({str(b.get("slate_date") or "")[:10] for b in open_ufc} | {yday})
    results = {d: card_results(d, fetch) for d in bout_dates if d}
    results = {d: r for d, r in results.items() if r}
    if yday not in results and not open_ufc:
        return None
    card = {}
    if yday in results:
        rows = grade_card(results[yday], MS.load_ufc_odds(yday, db_path=db_path))
        s = summarize(rows)
        event = next((r["event"] for r in rows if r.get("event")), "UFC")
        card = {"date": yday, "event": event, "summary": s, "bouts": rows, "recap": recap(event, yday, s, rows),
                "priced_note": None if s["priced"] else "No saved prices for this card (it ran before price capture "
                                                         "started) — results only."}
    # the market across every card on file
    cutoff = (date.fromisoformat(morning) - timedelta(days=TREND_DAYS)).isoformat()
    trend_rows = []
    for d in MS.ufc_card_dates(db_path=db_path):
        if cutoff <= d < morning:
            rs = card["bouts"] if card and d == yday else grade_card(card_results(d, fetch), MS.load_ufc_odds(d, db_path=db_path))
            trend_rows += rs
    settlement = settle(open_ufc, results, write=write, bet_db=bet_db) if open_ufc else \
        {"settled": [], "tickets": [], "unresolved": [], "still_pending": []}
    notes = []
    if card:
        s = card["summary"]
        if s["priced"]:
            notes.append(f"{yday}: favorites {s['favorites']['won']}-{s['favorites']['lost']} "
                         f"(priced for {s['favorites']['expected']:.1f} wins); {len(s['upsets'])} upset(s).")
        notes.append(f"{yday}: {s['finishes']} finishes, {s['decisions']} decisions.")
    return {"sport": "UFC", "morning": morning, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "card": card, "notes": notes, "trend": {"days": TREND_DAYS, "bouts": len([r for r in trend_rows if r.get("fav_won") is not None]),
                                                     "bands": bands(trend_rows), "summary": summarize(trend_rows) if trend_rows else None},
            "slates": {}, "suggestions": [], "settlement": settlement}
