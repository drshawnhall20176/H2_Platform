"""
morning_brief.py — the platform's own daily check-in (Nov 11, agent step 1).

Every morning the owner asked: did everything run, did the model learn, how did my bets do? This writes that note
itself, in plain words, and delivers it:

    python morning_brief.py morning [YYYY-MM-DD]     # health, what the model learned, yesterday's bets and scorecard
    python morning_brief.py picks   [YYYY-MM-DD]     # this afternoon's Good bets, sized to the owner's limits

Each note is saved (model_store setting "brief:<date>:<kind>", shown on Home) and, when OWNER_BRIEF_WEBHOOK is set
(a PRIVATE Discord channel's webhook -- never the public H2 channel: the note has the owner's bets and money), posted
there. A note is sent once per day per kind; --force sends it again.
The morning note waits until the morning review has run (it reads it); the workflow runs the review first if needed.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

import pytz

ET = pytz.timezone("US/Eastern")
SPORTS = ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB", "UFC")
PROPS_SPORTS = ("NBA", "NFL", "NHL", "NCAAF")
KEY = "brief:{date}:{kind}"
# overnight jobs worth checking: workflow file -> plain name
JOBS = {"settle-results.yml": "Settling bets", "capture-closing-lines.yml": "Closing lines",
        "script-learn.yml": "Game-script learning", "daily-review.yml": "Morning review"}
DISCORD_LIMIT = 1900


def today_et() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d")


def usd(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}${abs(x):,.2f}"


# --------------------------------------------------------------------------- pieces of the morning note
def job_health(since_utc: datetime, fetch=None) -> List[str]:
    """One line per overnight job: ran fine / failed / didn't run. Needs GITHUB_TOKEN + GITHUB_REPOSITORY (Actions)."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if fetch is None:
        if not (token and repo):
            return []
        import requests

        def fetch(wf):
            r = requests.get(f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs",
                             params={"per_page": 20, "created": f">={since_utc:%Y-%m-%dT%H:%M:%SZ}"},
                             headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                             timeout=20)
            r.raise_for_status()
            return r.json().get("workflow_runs") or []
    out = []
    for wf, name in JOBS.items():
        try:
            runs = [r for r in fetch(wf) if r.get("status") == "completed"]
        except Exception as exc:                                    # noqa: BLE001
            out.append(f"⚪ {name}: couldn't check ({type(exc).__name__})")
            continue
        ok = [r for r in runs if r.get("conclusion") == "success"]
        bad = [r for r in runs if r.get("conclusion") == "failure"]
        if ok and not bad:
            out.append(f"✅ {name}")
        elif ok:
            out.append(f"🟠 {name}: ran, but {len(bad)} of {len(runs)} runs failed")
        elif bad:
            out.append(f"🔴 {name}: failed")
        else:
            out.append(f"🔴 {name}: didn't run")
    return out


def learned(reports: Dict[str, Dict]) -> List[str]:
    """What changed overnight, and a one-line 'held' summary -- the automatic steps' own words."""
    changed, held = [], 0
    for sp, rep in reports.items():
        for d in (rep.get("calibration") or {}).get("auto") or []:
            if d.get("applied"):
                side = "overall" if d.get("side") == "overall" else f"{d['side']}s"
                changed.append(f"{sp} {side}: {d['active']:.2f} → {d['new']:.2f} ({d.get('why', '')})")
            else:
                held += 1
        for t in rep.get("auto_tuning") or []:
            if t.get("applied"):
                changed.append(f"{sp} {t.get('market')}{' · ' + t['slot'] if t.get('slot') else ''} projections "
                               f"×{t.get('factor', 1):.3f} ({t.get('why', '')})")
            else:
                held += 1
    out = [f"🔧 {c}" for c in changed] or ["No changes overnight."]
    if held:
        out.append(f"{held} other check(s) waited for more data — nothing for you to do.")
    return out


def scorecard(reports: Dict[str, Dict], yday: str) -> List[str]:
    """Per sport: the model's side record and its 'most probable' picks, from the morning review's own notes."""
    out = []
    for sp, rep in reports.items():
        bits = []
        for n in rep.get("notes") or []:
            if not n.startswith(yday):
                continue
            if "model's side was right" in n:
                bits.append(n.split(": ", 1)[1].replace("the model's side was right on ", "right on ").rstrip("."))
            elif "Most probable" in n or "most probable" in n:
                bits.append(n.split(": ", 1)[1].rstrip("."))
        if bits:
            out.append(f"**{sp}**: " + "; ".join(bits[:2]))
    return out


def bets_yesterday(bets: Sequence[Dict], yday: str) -> List[str]:
    import betlog as B
    mine = [b for b in B.money_bets(list(bets)) if str(b.get("slate_date")) == yday]
    if not mine:
        return ["No bets logged."]
    singles = [b for b in mine if not B.is_parlay_header(b)]
    tickets = [b for b in mine if B.is_parlay_header(b)]
    out = []
    for name, group in (("Singles", singles), ("Parlays", tickets)):
        if not group:
            continue
        done = [b for b in group if B.bet_pnl(b) is not None]
        w = sum(B._result(b) == "win" for b in done)
        lo = sum(B._result(b) == "loss" for b in done)
        pl = sum(B.bet_pnl(b) for b in done)
        line = f"{name}: {w}–{lo}, {usd(pl)}"
        misses = [str(b.get("player") or b.get("notes") or "")[:30] for b in group if B._result(b) == "loss"]
        if name == "Singles" and misses:
            line += f" (missed: {', '.join(m for m in misses if m)[:120]})"
        if len(done) < len(group):
            line += f" · {len(group) - len(done)} not settled yet"
        out.append(line)
    total = sum(B.bet_pnl(b) or 0 for b in mine)
    out.append(f"**Total: {usd(total)}**")
    still = [b for b in B.money_bets(list(bets)) if B._result(b) in ("", "pending") and str(b.get("slate_date")) < yday]
    if still:
        out.append(f"⚠️ {len(still)} older bet(s) still open — check the Bet Log.")
    return out


def morning(day: str, reports: Dict[str, Dict], bets: Sequence[Dict], health: Sequence[str]) -> str:
    yday = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    lines = [f"☀️ **H2 morning brief — {datetime.strptime(day, '%Y-%m-%d'):%a %b %-d}**", ""]
    if health:
        bad = [h for h in health if not h.startswith("✅")]
        lines += ["**Overnight jobs**: " + ("all ran ✅" if not bad else ""), *bad, ""]
    lines += ["**What the model learned**", *learned(reports), ""]
    lines += [f"**Your bets ({datetime.strptime(yday, '%Y-%m-%d'):%a})**", *bets_yesterday(bets, yday), ""]
    sc = scorecard(reports, yday)
    if sc:
        lines += ["**How the model did**", *sc, ""]
    lines += ["Picks for today come this afternoon, once the books post lines."]
    return "\n".join(lines).strip()


# --------------------------------------------------------------------------- the afternoon picks note
def picks(day: str, rows: Sequence[Dict], bets: Sequence[Dict], tag_records_for, limits: Dict, top: int = 6) -> str:
    """This afternoon's Good bets (My Coach's own verdicts), each sized so the whole list fits the daily budget."""
    import coach as CO
    cands = [r for r in rows if r.get("price") is not None and r.get("chance") is not None]
    judged = []
    for sp in sorted({c.get("sport") for c in cands}):
        sp_c = [c for c in cands if c.get("sport") == sp]
        judged += CO.finder(sp_c, list(bets), tag_records_for(sp))
    good = [j for j in judged if j.get("verdict") == "🟢 Good bet"]
    good.sort(key=lambda j: -(j.get("edge") or 0))
    good = good[:top]
    head = [f"🎯 **H2 picks — {datetime.strptime(day, '%Y-%m-%d'):%a %b %-d}**", ""]
    if not good:
        maybe = sum(j.get("verdict") == "🟡 Maybe" for j in judged)
        return "\n".join(head + [f"No Good bets on the board right now ({len(judged)} checked, {maybe} Maybe). "
                                 "Sitting out is a fine result — no bet beats a bad bet."])
    budget = float(limits.get("daily_budget") or 40)
    stake = max(1.0, min(5.0, round(budget / max(len(good), 1) / 2)))   # half the budget across singles, $1–$5 each
    out = head + [f"{len(good)} Good bet(s), ${stake:.0f} each (your budget ${budget:.0f}, stop-loss "
                  f"${float(limits.get('stop_loss') or 25):.0f}):"]
    for j in good:
        price = j.get("price")
        out.append(f"• {j.get('sport')} · {j.get('pick')} {'' if price is None else f'({price:+.0f})'} — "
                   f"{j.get('time') or ''} {j.get('game') or ''} · edge {CO.pts(j['edge'])}".rstrip())
    out += ["", "Singles only — the coach's rule after Nov 8. Tick them on My Coach to log them."]
    return "\n".join(out)


# --------------------------------------------------------------------------- delivery
def chunks(text: str, limit: int = DISCORD_LIMIT) -> List[str]:
    out, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit and cur:
            out.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        out.append(cur)
    return out


def deliver(text: str, webhook: Optional[str], post=None) -> bool:
    if not webhook:
        return False
    if post is None:
        import requests

        def post(body):
            r = requests.post(webhook, json=body, timeout=20)
            r.raise_for_status()
    for c in chunks(text):
        post({"content": c, "allowed_mentions": {"parse": []}})
    return True


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    force = "--force" in argv
    argv = [a for a in argv if a != "--force"]
    kind = argv[0] if argv else "auto"
    day = argv[1] if len(argv) > 1 else today_et()
    if kind == "auto":
        # Nov 11: decide by the clock, not by what triggered the run -- GitHub fired the 6 AM schedule at 4:51 PM and
        # collapsed the warm-up's trigger into the review's, so the picks note never went. Every run now sends
        # whatever is due and not yet sent: the morning note once its review exists, the picks note after 3 PM.
        return max(run(k, day, force) for k in ("morning", "picks"))
    return run(kind, day, force)


def run(kind: str, day: str, force: bool = False) -> int:
    import model_store as MS
    import betlog as B
    key = KEY.format(date=day, kind=kind)
    if MS.get_setting(key) and not force:
        print(f"{kind} brief for {day} already sent.")
        return 0
    bets = B.list_bets()
    if kind == "morning":
        reports = {sp: r for sp in SPORTS if (r := MS.load_daily_review(sp, day))}
        if not reports:
            print(f"No morning review for {day} yet — the brief waits for it.")
            return 0
        since = ET.localize(datetime.strptime(day, "%Y-%m-%d") - timedelta(days=1)).replace(hour=20)
        text = morning(day, reports, bets, job_health(since.astimezone(timezone.utc)))
    elif kind == "picks":
        if datetime.now(ET).hour < 15 and not force:
            print("Picks go out after 3 PM New York, once the books have posted.")
            return 0
        import coach as CO
        import pick_records as PR
        import todays_best as TB
        rows = [r for r in TB.collect(day, PROPS_SPORTS)["rows"] if r.get("kind") == "Prop"]
        if not rows:
            print(f"No saved picks for {day} yet (the hourly warm-up saves them once the books post).")
            return 0
        text = picks(day, rows, bets, PR.tag_records, CO.limits())
    else:
        print(f"unknown brief kind: {kind}")
        return 2
    print(text)
    sent = False
    try:
        sent = deliver(text, os.environ.get("OWNER_BRIEF_WEBHOOK"))
    except Exception as exc:                                        # noqa: BLE001
        print(f"Couldn't post to Discord: {type(exc).__name__}: {exc}")
    MS.save_setting(key, {"at": datetime.now(timezone.utc).isoformat(), "text": text, "sent": sent})
    print("posted to Discord" if sent else "saved (shown on Home); no OWNER_BRIEF_WEBHOOK set")
    return 0


if __name__ == "__main__":
    sys.exit(main())
