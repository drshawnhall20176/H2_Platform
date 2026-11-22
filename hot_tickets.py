"""
hot_tickets.py — 🔥 H2 Sports Hot Tickets: the day's most probable picks, posted to the Analyst Desk Discord (Nov 22).

Owner, Nov 22: "top picks of the day ... H2 Sports Hot Tickets or games of the week ... the most probable picks to
win, as these will be used to drive interaction and draw attention to the Discord and my page." Format: both singles
and a parlay ("would you disagree that both would scratch the itch of multiple types of bettors?" -- agreed). Price:
his call to me. Timing: posted no later than 11 AM ET (early weekend, tournament and bowl starts).

THE RULE (rules.py "hot"):
  * the pool is the platform's own picks -- today's saved props boards (the Command Center's) and the game-line 💰
    picks -- never a pick'em-only line (no price to grade), never a game that has started, never a market the
    automatic shut-off has pulled;
  * MOST PROBABLE, BUT IT MUST PAY: ranked by the EARNED chance (what the model's record has earned, not its raw
    opinion), keeping only picks whose earned chance clears what the price needs, at no worse than MAX_FAV (-300).
    A -400 favorite wins a lot and still loses money; Hot Tickets that lose money would burn the trust they're built
    to earn;
  * SINGLES singles, one per game and one per player; the top one is the 🎟️ Ticket of the Day;
  * the 🎰 Hot Ticket parlay is the top LEGS singles (different games, so the legs don't lean on each other); its
    chance is the legs' chances multiplied, its price the legs' prices multiplied;
  * Saturday's top college football pick and Sunday's top NFL pick are the 🏈 Pick of the Week.

THE RECORD: every posted ticket is saved to the shown-picks ledger (kind "hot") the moment it's posted and graded the
next morning with everything else; the parlay is graded from its legs. The next post opens with yesterday's results
and the running record -- wins and losses. Nothing is posted twice (analyst_ledger.claim_post).

    python hot_tickets.py            # dry run: print today's post and yesterday's recap
    python hot_tickets.py post       # post (DISCORD_WEBHOOK_URL), once a day each
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

MAX_FAV = -300          # no worse than -300 (Nov 22 dry run: at -200 the top ticket was a 57% shot)
SINGLES = 3
LEGS = 2
START = "2026-11-22"    # the first Hot Tickets slate
KEY = "HOT:{day}"       # the posted parlay: {"legs": [ledger keys], "price", "chance", "posted_at"}
EARLIEST = (8, 30)      # Nov 22: never before 8:30 AM ET (the morning review runs overnight too)
POTW = {5: "NCAAF", 6: "NFL"}     # Saturday / Sunday -> the Pick of the Week's sport
POTW_NAME = {"NCAAF": "College Football", "NFL": "NFL"}


# --------------------------------------------------------------------------- choosing
def candidates(day: str, now: Optional[datetime] = None, keys: Optional[Sequence[str]] = None, load_props=None,
               games=None, off=None) -> List[Dict]:
    import pick_ledger as PL
    import props_money as PM
    if load_props is None:
        import todays_best as TB
        load_props = TB.load_props
    if off is None:
        import shutoff as SO

        def off(sport, market, kind):
            return SO.is_off(sport, market, kind, day)
    picks: List[Dict] = []
    for k in keys if keys is not None else PL.strong_keys():
        picks += [dict(r, sport=r.get("sport") or k) for r in (load_props(k, day) or {}).get("rows") or []]
    try:
        picks += PL.game_candidates(day) if games is None else list(games)
    except Exception:                                           # noqa: BLE001 -- props still count
        pass
    out = []
    for r in picks:
        if r.get("pickem_only") or r.get("price") is None or r.get("earned") is None:
            continue
        if PL.started(day, r, now):
            continue
        try:
            price = float(r["price"])
        except (TypeError, ValueError):
            continue
        if price < MAX_FAV:
            continue
        need = PM.needed(price)
        if need is None or float(r["earned"]) < need:
            continue
        kind = "games" if r.get("money_market") else "lock"
        try:
            if off(r.get("sport"), r.get("money_market") or r.get("market"), kind):
                continue
        except Exception:                                       # noqa: BLE001
            pass
        out.append(dict(r, need=need))
    out.sort(key=lambda r: (-float(r["earned"]), -float(r["earned"]) + r["need"]))
    return out


def _who(r: Dict) -> str:
    return str(r.get("player") or r.get("pick") or "").lower()


def choose(cands: Sequence[Dict], day: str) -> Dict:
    """{"singles": [...], "parlay": {"legs", "price", "chance"} or None, "potw": row or None}."""
    import props_engine as PE
    singles, games, people = [], set(), set()
    for r in cands:
        g = r.get("game_id") or r.get("game")
        if g in games or (not r.get("money_market") and _who(r) in people):
            continue
        singles.append(r)
        games.add(g)
        people.add(_who(r))
        if len(singles) >= SINGLES:
            break
    parlay = None
    if len(singles) >= LEGS:
        legs = singles[:LEGS]
        dec, ch = 1.0, 1.0
        for r in legs:
            dec *= PE.decimal(r["price"]) or 1.0
            ch *= float(r["earned"])
        parlay = {"legs": legs, "price": PE.american(1 / dec) if dec > 1 else None, "decimal": dec, "chance": ch}
    potw = None
    sp = POTW.get(date.fromisoformat(day).weekday())
    if sp:
        potw = next((r for r in cands if r.get("sport") == sp), None)
    return {"singles": singles, "parlay": parlay, "potw": potw}


# --------------------------------------------------------------------------- words
def _price(p) -> str:
    try:
        return f"{int(float(p)):+d}"
    except (TypeError, ValueError):
        return "—"


def _time(r: Dict) -> str:
    t = str(r.get("time") or "").strip()
    return f" · {t} ET" if t else ""


def _book(r: Dict) -> str:
    try:
        import odds_api as O
        b = r.get("book")
        return O.book_label(b) if isinstance(b, str) and b else ""
    except Exception:                                           # noqa: BLE001
        return str(r.get("book") or "")


def pick_line(r: Dict) -> str:
    bk = _book(r)
    return (f"{r.get('sport')} · **{r.get('pick')}** ({_price(r.get('price'))}{', ' + bk if bk else ''}){_time(r)}\n"
            f"   about {float(r['earned']):.0%} to cash by the model's earned chance (the price needs {r['need']:.0%})")


def _nice_day(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{d:%a} {d:%b} {d.day}"


def post_text(day: str, ch: Dict, record_line: str = "") -> str:
    import analyst_tools as AT
    s = ch["singles"]
    if not s:
        return ""
    lines = [f"🔥 **H2 SPORTS HOT TICKETS** · {_nice_day(day)}",
             "The picks most likely to cash today — at prices that still pay.", "",
             "🎟️ **TICKET OF THE DAY**", pick_line(s[0]), ""]
    if len(s) > 1:
        lines.append("🔥 **ALSO HOT**")
        for i, r in enumerate(s[1:], 2):
            lines.append(f"{i}) " + pick_line(r))
        lines.append("")
    p = ch.get("parlay")
    if p and p.get("price") is not None:
        lines += [f"🎰 **HOT TICKET PARLAY** · {len(p['legs'])} legs · {_price(p['price'])} · about {p['chance']:.0%} "
                  "to hit",
                  "   " + " + ".join(str(r.get("pick")) for r in p["legs"]),
                  "   Bigger payout, misses more often — size it smaller than a single.", ""]
    w = ch.get("potw")
    if w:
        sp = w.get("sport")
        if any(w is r or w.get("pick") == r.get("pick") for r in s):
            lines += [f"🏈 **{POTW_NAME.get(sp, sp).upper()} PICK OF THE WEEK:** {w.get('pick')} — on the card above.", ""]
        else:
            lines += [f"🏈 **{POTW_NAME.get(sp, sp).upper()} PICK OF THE WEEK**", pick_line(w), ""]
    if record_line:
        lines += [record_line, ""]
    lines += ["Every ticket is saved before its game and graded the next morning — wins and losses, in this channel.",
              f"_{AT.DISCLAIMER}_"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- the record
def _leg_results(day: str, get=None) -> Dict[str, Optional[str]]:
    import pick_ledger as PL
    return {k: r.get("result") for k, r in (PL.load("hot", "ALL", day, get)["rows"] or {}).items()}


def parlay_result(day: str, get=None) -> Optional[str]:
    """win / loss / push / None (not graded yet, or no parlay). A void leg drops out; all legs void = push."""
    import pick_ledger as PL
    p = PL._get(KEY.format(day=day), get)
    legs = p.get("legs") or []
    if not legs:
        return None
    res = _leg_results(day, get)
    got = [res.get(k) for k in legs]
    if any(g == "loss" for g in got):
        return "loss"
    if any(g not in ("win", "push", "void") for g in got):
        return None
    return "win" if any(g == "win" for g in got) else "push"


def _parlay_units(day: str, get=None) -> float:
    """Units at the posted price, voided legs taken out (1u stake)."""
    import pick_ledger as PL
    import props_engine as PE
    p = PL._get(KEY.format(day=day), get)
    rows = PL.load("hot", "ALL", day, get)["rows"] or {}
    dec = 1.0
    for k in p.get("legs") or []:
        r = rows.get(k) or {}
        if r.get("result") == "win":
            dec *= PE.decimal(r.get("price")) or 1.0
    return dec - 1


def record(end: str, get=None) -> Dict:
    """Singles and parlays from START through `end`: {"w", "l", "units", "pw", "pl", "punits"}."""
    import pick_ledger as PL
    out = {"w": 0, "l": 0, "units": 0.0, "pw": 0, "pl": 0, "punits": 0.0}
    d0, d1 = date.fromisoformat(START), date.fromisoformat(end)
    while d0 <= d1:
        d = d0.isoformat()
        r = PL.record("hot", "ALL", d, get)
        if r:
            out["w"] += r["hits"]
            out["l"] += r["misses"]
            out["units"] += r["units"]
        pr = parlay_result(d, get)
        if pr == "win":
            out["pw"] += 1
            out["punits"] += _parlay_units(d, get)
        elif pr == "loss":
            out["pl"] += 1
            out["punits"] -= 1.0
        d0 += timedelta(days=1)
    return out


def record_line(rec: Dict) -> str:
    if not (rec["w"] + rec["l"] + rec["pw"] + rec["pl"]):
        return ""
    return (f"📒 **Hot Tickets record:** singles {rec['w']}–{rec['l']} ({rec['units']:+.2f}u) · "
            f"parlays {rec['pw']}–{rec['pl']} ({rec['punits']:+.2f}u) · 1u a ticket, at the posted prices")


def recap_text(day: str, get=None) -> str:
    """Yesterday's tickets, graded; "" until every single is graded."""
    import pick_ledger as PL
    rows = PL.rows("hot", "ALL", day, get)
    if not rows or any(r.get("result") not in ("win", "loss", "push", "void") for r in rows):
        return ""
    mark = {"win": "✅", "loss": "❌", "push": "➖", "void": "➖"}
    lines = [f"🧾 **HOT TICKETS RECAP** · {_nice_day(day)}"]
    for r in rows:
        lines.append(f"{mark.get(r.get('result'), '•')} {r.get('sport')} · {r.get('pick')} ({_price(r.get('price'))})")
    pr = parlay_result(day, get)
    if pr:
        lines.append(f"{mark.get(pr, '•')} 🎰 Hot Ticket parlay")
    rl = record_line(record(day, get))
    if rl:
        lines += ["", rl]
    lines += ["", "Wins and losses, every one — that's the deal."]
    return "\n".join(lines)


# --------------------------------------------------------------------------- posting
def save_posted(day: str, ch: Dict, now: Optional[datetime] = None, save=None) -> None:
    import pick_ledger as PL
    rows = list(ch["singles"])
    w = ch.get("potw")
    if w and not any(w.get("pick") == r.get("pick") for r in rows):
        rows.append(dict(w, potw=True))
    PL.add("hot", "ALL", day, rows, now=now, save=save)
    p = ch.get("parlay")
    if p:
        PL._save(KEY.format(day=day), {"legs": [PL.row_key(r) for r in p["legs"]], "price": p["price"],
                                       "chance": p["chance"],
                                       "posted_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")},
                 save)


def run(post: bool = False, now: Optional[datetime] = None, webhook: Optional[str] = None, send=None,
        out=print) -> int:
    import analyst_ledger as AL
    import analyst_tools as AT
    import props_engine as PE
    today = PE._et_today()
    yest = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    code = 0
    if post and not (webhook or "").strip():
        out("DISCORD_WEBHOOK_URL is not set: nothing posted")
        return 1
    import pytz                                         # Nov 22: the morning review is a backup poster -- not overnight
    et = (now or datetime.now(timezone.utc)).astimezone(pytz.timezone("US/Eastern"))
    if post and (et.hour, et.minute) < EARLIEST:
        out(f"too early to post ({et:%H:%M} ET); Hot Tickets go out from {EARLIEST[0]}:{EARLIEST[1]:02d} AM ET")
        return 0
    # yesterday's recap first, once every ticket is graded
    rt = recap_text(yest) if yest >= START else ""
    if rt:
        if not post:
            out(f"--- recap (dry run) ---\n{rt}\n")
        elif AL.claim_post("hot_recap", "ALL", yest):
            try:
                AT.post_to_discord(webhook, rt, post=send)
                out("recap posted")
            except RuntimeError as exc:
                AL.release_post("hot_recap", "ALL", yest)
                out(f"recap failed: {exc}")
                code = 1
    elif yest >= START:
        out("recap: yesterday's tickets aren't all graded yet")
    # today's tickets, once
    if post and AL.posted("hot", "ALL", today):
        out("today's Hot Tickets already posted")
        return code
    ch = choose(candidates(today, now), today)
    text = post_text(today, ch, record_line(record(yest)) if yest >= START else "")
    if not text:
        out("no pick cleared the Hot Tickets rule yet")
        return code
    if not post:
        out(f"--- Hot Tickets (dry run) ---\n{text}\n")
        return code
    if not AL.claim_post("hot", "ALL", today):
        out("today's Hot Tickets already posted")
        return code
    try:
        AT.post_to_discord(webhook, text, post=send)
    except RuntimeError as exc:
        AL.release_post("hot", "ALL", today)
        out(f"Hot Tickets failed: {exc}")
        return 1
    save_posted(today, ch, now)
    out(f"Hot Tickets posted: {len(ch['singles'])} singles" + (", a parlay" if ch.get("parlay") else ""))
    return code


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    return run(post=bool(argv) and argv[0] == "post", webhook=os.environ.get("DISCORD_WEBHOOK_URL"))


if __name__ == "__main__":
    sys.exit(main())
