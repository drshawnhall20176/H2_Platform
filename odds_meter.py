"""
odds_meter.py — where the Odds API credits go (Nov 16).

The Odds API reports what each call cost in the `x-requests-last` response header (and the balance in
`x-requests-remaining`). Until now nothing kept that, so "what used 8,000 credits yesterday?" could only be estimated
from the code. Every fetch helper that can reach the Odds API calls record(url, headers); the totals are saved per
New York day, per job and per feed (model_store.add_odds_usage -> table odds_usage), and Data Health shows them.

Job = the GitHub workflow that made the call ("warm-slates", "capture-intl", "research" ...), with " (manual)" added
when someone started it by hand, or "app" / "app-public" for the Streamlit apps. Set ODDS_JOB to override.

Totals are flushed when a script ends (atexit) and, in the long-running apps, at most once every FLUSH_S seconds.
A failure here never affects the fetch that reported it.
"""
from __future__ import annotations

import atexit
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

HOST = "the-odds-api.com"
FLUSH_S = 120.0
_lock = threading.Lock()
_pending: Dict[Tuple[str, str, str], List[int]] = {}      # (day, job, feed) -> [credits, calls]
_remaining: Optional[int] = None
_last_flush = time.time()


def job() -> str:
    """Who is spending: ODDS_JOB, else the GitHub workflow (hand-started runs marked), else the app."""
    j = os.environ.get("ODDS_JOB")
    if j:
        return j
    wf = os.environ.get("GITHUB_WORKFLOW")
    if wf:
        return wf + (" (manual)" if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" else "")
    return "app-public" if str(os.environ.get("AUDIENCE") or "").lower() == "public" else "app"


def feed(url: str) -> str:
    """The Odds API sport key in the URL, with the kind of call: "basketball_nba props", "soccer_epl lines",
    "americanfootball_nfl historical", "events list" (free)."""
    u = str(url or "")
    m = re.search(r"/sports/([^/?]+)(/.*)?$", u.split("?")[0])
    if not m:
        return "other"
    key, rest = m.group(1), m.group(2) or ""
    if "/historical/" in u:
        return f"{key} historical"
    if re.search(r"/events/[^/]+/odds", rest):
        return f"{key} props"
    if rest.startswith("/odds"):
        return f"{key} lines"
    return f"{key} lists"


def _day(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    try:
        import pytz
        return now.astimezone(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
    except Exception:                                           # noqa: BLE001
        return now.strftime("%Y-%m-%d")


def _int(x) -> Optional[int]:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def record(url: str, headers, now: Optional[datetime] = None) -> int:
    """Count one response. Returns the credits it cost (0 for other hosts, free calls or a missing header)."""
    global _remaining
    try:
        if HOST not in str(url or "") or headers is None:
            return 0
        cost = _int(headers.get("x-requests-last")) or 0
        left = _int(headers.get("x-requests-remaining"))
        with _lock:
            cell = _pending.setdefault((_day(now), job(), feed(url)), [0, 0])
            cell[0] += cost
            cell[1] += 1
            if left is not None:
                _remaining = left
            due = time.time() - _last_flush >= FLUSH_S
        if due:
            flush()
        return cost
    except Exception:                                           # noqa: BLE001 -- the meter never breaks a fetch
        return 0


def pending() -> Dict[Tuple[str, str, str], List[int]]:
    with _lock:
        return {k: list(v) for k, v in _pending.items()}


def flush(db_path: Optional[str] = None) -> int:
    """Save what has been counted since the last flush. Returns the rows written; unsaved counts are kept."""
    global _last_flush
    with _lock:
        rows = [{"day": d, "job": j, "feed": f, "credits": c, "calls": n, "remaining": _remaining}
                for (d, j, f), (c, n) in _pending.items() if n]
        taken = dict(_pending)
        _pending.clear()
        _last_flush = time.time()
    if not rows:
        return 0
    try:
        import model_store as MS
        if MS.add_odds_usage(rows, db_path=db_path):
            return len(rows)
    except Exception:                                           # noqa: BLE001
        pass
    with _lock:                                                 # not saved (no store, or a test run): keep counting
        for k, (c, n) in taken.items():
            cell = _pending.setdefault(k, [0, 0])
            cell[0] += c
            cell[1] += n
    return 0


def by_job(rows: List[Dict]) -> List[Dict]:
    """[{day, job, credits, calls}] biggest spender first within each day (newest day first)."""
    agg: Dict[Tuple[str, str], List[int]] = {}
    for r in rows or []:
        cell = agg.setdefault((str(r.get("day")), str(r.get("job"))), [0, 0])
        cell[0] += int(r.get("credits") or 0)
        cell[1] += int(r.get("calls") or 0)
    out = [{"day": d, "job": j, "credits": c, "calls": n} for (d, j), (c, n) in agg.items()]
    out.sort(key=lambda r: (r["day"], r["credits"]), reverse=True)
    return out


def by_day(rows: List[Dict]) -> List[Dict]:
    """[{day, credits, calls}] newest first."""
    agg: Dict[str, List[int]] = {}
    for r in rows or []:
        cell = agg.setdefault(str(r.get("day")), [0, 0])
        cell[0] += int(r.get("credits") or 0)
        cell[1] += int(r.get("calls") or 0)
    return [{"day": d, "credits": c, "calls": n} for d, (c, n) in sorted(agg.items(), reverse=True)]


atexit.register(flush)
