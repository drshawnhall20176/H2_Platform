"""
community_post.py — the H2 Discord bot (Nov 20).

Owner: "how do I set up the discord bot" (the weekend audit's top engagement idea: post each day's 🔒 and 💰 picks to
the community, then how they did). Two posts a day to the PUBLIC community channel, through H2_COMMUNITY_WEBHOOK:

  picks:    the day's 💰 Money picks (all, up to MAX_MONEY) and its strongest 🔒 Most probable picks (up to MAX_LOCKS),
            games not started yet, earliest first, each with its price, book and chance -- plus the 💰 live test's
            running record. Weekdays after 3:30 PM New York; Saturday / Sunday after 11:30 AM (early football).
  results:  the next morning, the same picks marked ✅ / ❌, with the 💰 and 🔒 records for the day.

Only model picks go out -- never the owner's bets, stakes or bankroll (those stay in the private brief). Each post goes
once a day (model_store setting "community:<date>:<kind>"). Without the webhook nothing is sent or marked, so the
first run after the secret is added posts. `--dry-run` prints the post and sends nothing.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

import pytz

ET = pytz.timezone("US/Eastern")
KEY = "community:{date}:{kind}"
PROPS_SPORTS = ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB")
MAX_MONEY = 12
MAX_LOCKS = 8
ICON = {"NBA": "🏀", "NHL": "🏒", "NFL": "🏈", "NCAAF": "🏈", "NCAAMB": "🏀"}
FOOTER = "_Model picks for analysis and entertainment — not financial advice. Bet responsibly._"


def now_et() -> datetime:
    return datetime.now(ET)


def picks_due(now: datetime) -> bool:
    """Weekdays from 3:30 PM, weekends from 10:30 AM (New York): Sunday NFL starts at 1 PM."""
    start = (10, 30) if now.weekday() >= 5 else (15, 30)
    return (now.hour, now.minute) >= start


def _start(day: str, time_text: str) -> Optional[datetime]:
    try:
        return ET.localize(datetime.strptime(f"{day} {time_text.strip()}", "%Y-%m-%d %I:%M %p"))
    except (ValueError, AttributeError):
        return None


def _price(p) -> str:
    try:
        return f"{int(float(p)):+d}"
    except (TypeError, ValueError):
        return ""


def choose(rows: Sequence[Dict], day: str, now: Optional[datetime] = None) -> List[Dict]:
    """The picks to post: every 💰 (biggest edge first, cap MAX_MONEY), then the likeliest 🔒 not already in, cap
    MAX_LOCKS -- sportsbook lines only, games not started, one pick per player; earliest game first."""
    now = now or now_et()
    live = []
    for r in rows or []:
        if r.get("kind") != "Prop" or r.get("pickem_only") or r.get("price") is None:
            continue
        st = _start(day, r.get("time") or "")
        if st is not None and st <= now:
            continue
        live.append(r)
    seen, out = set(), []

    def take(r, why):
        who = (r.get("sport"), r.get("player") or r.get("pick"))
        if who in seen:
            return False
        seen.add(who)
        out.append({"sport": r.get("sport"), "pick": r.get("pick"), "time": r.get("time") or "", "price": r.get("price"),
                    "book": r.get("book") or "", "chance": r.get("chance"), "money": why == "money",
                    "lock": bool(r.get("lock")), "game": r.get("game") or ""})
        return True
    n = 0
    for r in sorted((r for r in live if r.get("money")), key=lambda r: -(r.get("edge") or 0)):
        if n < MAX_MONEY and take(r, "money"):
            n += 1
    n = 0
    for r in sorted((r for r in live if r.get("lock")), key=lambda r: -(r.get("chance") or 0)):
        if n < MAX_LOCKS and take(r, "lock"):
            n += 1
    out.sort(key=lambda x: (_start(day, x["time"]) is None, _start(day, x["time"]) or now))
    return out


def _line(p: Dict, mark: str = "") -> str:
    bits = [f"`{p['time'] or 'TBD':>8}`", f"{ICON.get(p['sport'], '')} {p['pick']}"]
    pr = _price(p.get("price"))
    if pr:
        bits.append(f"{pr}" + (f" {p['book']}" if p.get("book") else ""))
    if p.get("chance") is not None:
        bits.append(f"{p['chance']:.0%}")
    return (mark + " " if mark else "") + " · ".join(bits)


def scoreboard_line() -> Optional[str]:
    try:
        import money_scoreboard as MSB
        import props_engine as PE
        t = MSB.scoreboard()["total"]
        if not t["n"]:
            return None
        f = datetime.fromisoformat(PE.MONEY_TEST["from"])
        return (f"💰 Live test since {f:%a %b %-d}: **{t['hits']}–{t['misses']}** ({t['hit_rate']:.0%}, needed "
                f"{t['needed']:.0%}) · **{t['units']:+.2f} units** at 1 unit a pick")
    except Exception:                                           # noqa: BLE001
        return None


def picks_text(day: str, chosen: Sequence[Dict], board: Optional[str] = None) -> str:
    d = datetime.strptime(day, "%Y-%m-%d")
    money = [p for p in chosen if p["money"]]
    locks = [p for p in chosen if not p["money"]]
    lines = [f"📋 **H2 Sports — today's model picks · {d:%a %b %-d}**", ""]
    if money:
        lines += ["💰 **Money picks** — the model's edge at a fair price (live test this weekend)",
                  *[_line(p) for p in money], ""]
    if locks:
        lines += ["🔒 **Most probable** — the model's likeliest picks with a sportsbook line",
                  *[_line(p) for p in locks], ""]
    if board:
        lines += [board, ""]
    lines += [FOOTER]
    return "\n".join(lines)


def results_text(day: str, posted: Sequence[Dict], results: Dict) -> Optional[str]:
    """None until most posted picks are graded."""
    if not posted:
        return None
    marks = []
    for p in posted:
        r = results.get((p["sport"], p["pick"]))
        marks.append({"hit": "✅", "win": "✅", "miss": "❌", "loss": "❌", "push": "➖", "void": "➖"}.get(r or "", "⏳"))
    done = sum(m in ("✅", "❌") for m in marks)
    if done < max(1, int(0.8 * len(posted))):
        return None
    d = datetime.strptime(day, "%Y-%m-%d")
    lines = [f"🧾 **H2 Sports — how yesterday's picks did · {d:%a %b %-d}**", ""]
    for kind, title in (("money", "💰 Money picks"), ("lock", "🔒 Most probable")):
        grp = [(p, m) for p, m in zip(posted, marks) if (p["money"] if kind == "money" else not p["money"])]
        if not grp:
            continue
        w, l = sum(m == "✅" for _, m in grp), sum(m == "❌" for _, m in grp)
        units = 0.0
        for p, m in grp:
            dec = None
            try:
                a = float(p["price"])
                dec = 1 + (a / 100 if a > 0 else 100 / -a)
            except (TypeError, ValueError, ZeroDivisionError):
                pass
            if m == "✅" and dec:
                units += dec - 1
            elif m == "❌":
                units -= 1
        lines += [f"{title}: **{w}–{l}**" + (f" · {units:+.2f} units" if kind == "money" else ""),
                  *[_line(p, m) for p, m in grp], ""]
    board = scoreboard_line()
    if board:
        lines += [board, ""]
    lines += [FOOTER]
    return "\n".join(lines)


def deliver(text: str, webhook: Optional[str], post=None) -> bool:
    import morning_brief as MB
    return MB.deliver(text, webhook, post)


def run(kind: str, now: Optional[datetime] = None, dry_run: bool = False, force: bool = False, get=None, save=None,
        collect=None, webhook: Optional[str] = None, post=None) -> int:
    import model_store as MS
    get = get or MS.get_setting
    save = save or MS.save_setting
    now = now or now_et()
    webhook = webhook if webhook is not None else os.environ.get("H2_COMMUNITY_WEBHOOK")
    if collect is None:
        import todays_best as TB
        collect = TB.collect
    if kind == "test":                                          # Nov 20: check the webhook without waiting for picks
        text = "✅ **H2 Sports bot connected.** Today's 💰 and 🔒 model picks will post here this afternoon."
        print(text)
        if dry_run:
            return 0
        ok = deliver(text, webhook, post)
        print("posted the test message" if ok else "H2_COMMUNITY_WEBHOOK not set — nothing posted")
        return 0 if ok else 1
    if kind == "auto":
        return max(run(k, now, dry_run, force, get, save, collect, webhook, post) for k in ("results", "picks"))
    if kind == "picks":
        day = now.strftime("%Y-%m-%d")
        key = KEY.format(date=day, kind="picks")
        if get(key) and not force:
            print(f"picks for {day} already posted")
            return 0
        if not picks_due(now) and not force:
            print("picks post: not time yet")
            return 0
        chosen = choose(collect(day, PROPS_SPORTS)["rows"], day, now)
        if not chosen:
            print(f"no 🔒 / 💰 picks saved for {day} yet")
            return 0
        text = picks_text(day, chosen, scoreboard_line())
        print(text)
        if dry_run:
            return 0
        if not deliver(text, webhook, post):
            print("H2_COMMUNITY_WEBHOOK not set — nothing posted")
            return 0
        save(key, {"at": datetime.now(timezone.utc).isoformat(), "picks": chosen})
        print("posted picks to Discord")
        return 0
    if kind == "results":
        yday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        posted = (get(KEY.format(date=yday, kind="picks")) or {}).get("picks")
        key = KEY.format(date=yday, kind="results")
        if not posted:
            print(f"no picks were posted for {yday}")
            return 0
        if get(key) and not force:
            print(f"results for {yday} already posted")
            return 0
        rows = collect(yday, PROPS_SPORTS, past=True)["rows"]
        res = {(r.get("sport"), r.get("pick")): r.get("result") for r in rows if r.get("kind") == "Prop"}
        text = results_text(yday, posted, res)
        if not text:
            print(f"results for {yday}: not graded yet")
            return 0
        print(text)
        if dry_run:
            return 0
        if not deliver(text, webhook, post):
            print("H2_COMMUNITY_WEBHOOK not set — nothing posted")
            return 0
        save(key, {"at": datetime.now(timezone.utc).isoformat()})
        print("posted results to Discord")
        return 0
    print(f"unknown kind {kind}")
    return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    dry = "--dry-run" in argv
    force = "--force" in argv
    argv = [a for a in argv if not a.startswith("--")]
    return run(argv[0] if argv else "auto", dry_run=dry, force=force)


if __name__ == "__main__":
    sys.exit(main())
