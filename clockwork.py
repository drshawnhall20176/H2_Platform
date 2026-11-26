"""
clockwork.py — keep the scheduled jobs on schedule (Nov 19, ahead of the big weekend).

GitHub runs scheduled workflows "best effort" and, on this repo, skips most of them. Nov 18 00:00 – Nov 19 13:00 UTC:
warm-slates was due 21 times and ran 6; capture-closing-lines was due ~90 times and ran 8; settle-results was due ~40
times and ran 6. So a 7 PM tip-off's board could be the one built at 5:18 PM, and Wednesday's settled bets waited
until someone ran the job by hand. close-watch already works around this with one long-running job; this does the
same for everything else.

One run stays up to ~5h40m (started by its own cron every two hours -- any one start covers the window -- and on
demand). Every minute it reads the repo's recent runs; for each workflow below whose own cron came due DELAY minutes
ago (giving GitHub's schedule its chance) and that hasn't run since, it dispatches that workflow once. Due times
older than GRACE minutes are let go -- the next one is never far away. Dispatched runs use the workflow's defaults,
so only workflows that behave the same dispatched as scheduled are listed (not daily-review / tuning-report /
capture-ufc-odds, which treat a manual run as "force"); morning-brief is dispatched with kind=auto (INPUTS).
Nov 22: close-watch is listed after all -- it was "its own watcher", but GitHub skipped its 10:40 and 11:40 starts and
no shown pick got a captured close; a dispatched watcher replaces a running one (its concurrency), which covers the same
games. analyst-lock, hot-tickets and backup too (each posts or saves once a day; a dispatch can't double it).
The repo is public, so Actions minutes are free; each dispatch spends what the scheduled run would have.
"""
from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

WORKFLOWS = ("warm-slates", "settle-results", "capture-closing-lines", "capture-line-snapshots", "capture-game-picks",
             "capture-intl", "refresh-matchups", "refresh-ncaaf", "refresh-statcast", "refresh-calibration",
             "script-learn", "settle-analyst", "money-review",
             # Nov 22: skipped today -- close-watch ran once (3:44 AM) of four, analyst-lock 0 of 2, hot-tickets 0 of 3
             "close-watch", "analyst-lock", "hot-tickets", "backup",
             # Nov 26: the Rule scoreboard (owner: the rules must run with no intervention)
             "rule-scoreboard")
# Inputs for a dispatch, where the defaults would change what the run does. A run started by clockwork (GitHub's
# token) doesn't set off the workflow_run chain the scheduled one would, so morning-brief is dispatched on its own
# crons -- as "auto" (whatever note is due, never resent), which also runs the morning review when it's due.
INPUTS = {"morning-brief": {"kind": "auto"}, "community-post": {"kind": "auto"}}
WORKFLOWS = WORKFLOWS + tuple(INPUTS)
DELAY = 8           # minutes after a due time before stepping in
GRACE = 40          # minutes after a due time when it's let go
RUN_FOR = 340       # minutes one clockwork run stays up
RELOAD = 10         # minutes between re-reading the schedules from main (Nov 23)
HANDOFF = 8         # minutes before stopping that a run starts its successor (Nov 23)
WF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".github", "workflows")


# --------------------------------------------------------------------------- cron
def _field(spec: str, lo: int, hi: int) -> set:
    out = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = int(part)
            b = hi if step > 1 else a
        out.update(range(a, b + 1, step))
    return out


def matches(expr: str, t: datetime) -> bool:
    """Does a 5-field cron expression (UTC, GitHub's dialect) fire at minute t?"""
    mi, ho, dom, mon, dow = expr.split()
    dows = {d % 7 for d in _field(dow, 0, 7)}
    return (t.minute in _field(mi, 0, 59) and t.hour in _field(ho, 0, 23) and t.month in _field(mon, 1, 12)
            and (t.day in _field(dom, 1, 31) if dom != "*" else True)
            and ((t.isoweekday() % 7) in dows if dow != "*" else True))


def last_due(crons: Iterable[str], now: datetime, back: int = GRACE + DELAY + 5) -> Optional[datetime]:
    """The most recent minute at or before now (looking back `back` minutes) when any of the crons fired."""
    t = now.replace(second=0, microsecond=0)
    for _ in range(back + 1):
        if any(matches(c, t) for c in crons):
            return t
        t -= timedelta(minutes=1)
    return None


def crons_of(name: str, wf_dir: str = WF_DIR) -> List[str]:
    try:
        text = open(os.path.join(wf_dir, f"{name}.yml")).read()
    except OSError:
        return []
    return re.findall(r'-\s*cron:\s*"([^"]+)"', text)


def due(now: datetime, last_run: Dict[str, datetime], crons: Dict[str, List[str]]) -> List[str]:
    """Workflows to dispatch now: a cron came due DELAY..GRACE minutes ago and nothing has run since."""
    out = []
    for wf, cs in crons.items():
        t = last_due(cs, now)
        if t is None:
            continue
        age = (now - t).total_seconds() / 60
        if age < DELAY or age > GRACE:
            continue
        ran = last_run.get(wf)
        if ran is not None and ran >= t - timedelta(minutes=2):
            continue
        out.append(wf)
    return out


# --------------------------------------------------------------------------- GitHub
def _api(method: str, path: str, **kw):
    import requests
    r = requests.request(method, f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/{path}",
                         headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                                  "Accept": "application/vnd.github+json"}, timeout=30, **kw)
    r.raise_for_status()
    return r.json() if r.content else {}


def recent_runs() -> Dict[str, datetime]:
    """{workflow file stem: when its latest run was created} over the last 100 runs."""
    out: Dict[str, datetime] = {}
    for r in _api("GET", "actions/runs", params={"per_page": 100}).get("workflow_runs", []):
        stem = os.path.splitext(os.path.basename(r.get("path") or ""))[0]
        t = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
        if stem and (stem not in out or t > out[stem]):
            out[stem] = t
    return out


def live_crons(names, fetch=None) -> Dict[str, List[str]]:
    """Nov 23 (owner: "these schedule misses are a real problem"): the schedules as they are on main NOW, read through
    the API. A run used to read them once from its own checkout and keep them ~5.5 hours, so the 7:41 / 8:41 AM board
    rebuilds added that morning were unknown to the run already going, and both were missed. Falls back to the
    checkout's copy for any file the API can't give."""
    import base64
    fetch = fetch or (lambda path: _api("GET", f"contents/{path}", params={"ref": "main"}))
    out = {}
    for wf in names:
        try:
            text = base64.b64decode(fetch(f".github/workflows/{wf}.yml")["content"]).decode()
            cs = re.findall(r'-\s*cron:\s*"([^"]+)"', text)
        except Exception:                                       # noqa: BLE001
            cs = crons_of(wf)
        if cs:
            out[wf] = cs
    return out


def dispatch(wf: str, ref: str = "main") -> None:
    body = {"ref": ref}
    if INPUTS.get(wf):
        body["inputs"] = INPUTS[wf]
    _api("POST", f"actions/workflows/{wf}.yml/dispatches", json=body)


def main() -> int:
    crons = live_crons(WORKFLOWS)
    print("watching:", ", ".join(f"{k} ({len(v)} cron)" for k, v in crons.items()), flush=True)
    stop = time.time() + RUN_FOR * 60
    sent: Dict[str, datetime] = {}
    loaded, handed = time.time(), False
    while time.time() < stop:
        now = datetime.now(timezone.utc)
        if time.time() - loaded >= RELOAD * 60:                 # Nov 23: schedule changes reach a running watch
            new = live_crons(WORKFLOWS)
            if new and new != crons:
                print(f"{now:%H:%M} UTC schedules changed on main: reloaded", flush=True)
                crons = new
            loaded = time.time()
        if not handed and stop - time.time() <= HANDOFF * 60:   # Nov 23: start the next watch before this one ends --
            try:                                                # a dispatched run is never skipped the way the
                dispatch("clockwork")                           # schedule's starts are, so the watch never lapses
                handed = True
                print(f"{now:%H:%M} UTC started the next clockwork run", flush=True)
            except Exception as exc:                            # noqa: BLE001
                print(f"{now:%H:%M} UTC couldn't start the next run: {exc}", flush=True)
        try:
            runs = recent_runs()
            for wf, t in sent.items():                          # a dispatch just sent counts as a run
                if runs.get(wf) is None or t > runs[wf]:
                    runs[wf] = t
            for wf in due(now, runs, crons):
                dispatch(wf)
                sent[wf] = now
                print(f"{now:%H:%M} UTC dispatched {wf} (GitHub skipped its scheduled run)", flush=True)
        except Exception as exc:                                # noqa: BLE001 -- one bad minute never ends the watch
            print(f"{now:%H:%M} UTC check failed: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(60 - datetime.now(timezone.utc).second % 60 + 2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
