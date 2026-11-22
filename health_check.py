"""
health_check.py — one morning answer to "did everything work overnight?" (Nov 21).

Owner, Nov 21: get the build to A+. Item 7 of the plan: he shouldn't find a broken night on the site. After the morning
review (daily-review workflow, last step) this checks:

  * jobs      -- every scheduled workflow that ran in the last 24 hours: any that failed, and the key jobs (boards,
                 settlement, closing lines, Discord posts) that didn't run at all;
  * grading   -- yesterday's shown-picks ledgers graded; the morning review saved for each sport with a slate;
  * data      -- the morning data checks (data_checks.py): errors and warnings;
  * shut-off  -- markets switched off or put on watch this morning (shutoff.py);
  * credits   -- Odds API credits left (a free call that only reads the counter).

The result (KEY) shows as one line at the top of the Command Center and Today -- ✅ all clear, or ⚠️ / ❌ with the
list. `python health_check.py` (needs GITHUB_TOKEN + GITHUB_REPOSITORY for the jobs check; DATABASE_URL; ODDS_API_KEY).
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Sequence

KEY = "health:morning"
KEY_JOBS = ("warm-slates", "settle-results", "capture-closing-lines", "community-post", "capture-game-picks",
            "analyst-lock", "hot-tickets")
LOW_CREDITS = 2000
IGNORE = ("research", "inspect-day")    # analysis runs started by hand, not the platform's jobs


def _item(area: str, level: str, text: str) -> Dict:
    return {"area": area, "level": level, "text": text}


def check_jobs(runs: Sequence[Dict], now: datetime) -> List[Dict]:
    """runs: GitHub workflow runs ({"name", "conclusion", "created_at"}) from the last 24 hours."""
    out = []
    since = now - timedelta(hours=24)
    recent = [r for r in runs if datetime.fromisoformat(str(r.get("created_at")).replace("Z", "+00:00")) >= since
              and r.get("name") not in IGNORE]
    failed: Dict[str, int] = {}
    for r in recent:
        if r.get("conclusion") in ("failure", "timed_out", "startup_failure"):
            failed[r.get("name")] = failed.get(r.get("name"), 0) + 1
    for name, n in sorted(failed.items()):
        ok = sum(1 for r in recent if r.get("name") == name and r.get("conclusion") == "success")
        out.append(_item("jobs", "error" if not ok else "warn",
                         f"{name}: {n} failed run(s) in the last 24 hours" + (f" ({ok} succeeded)" if ok else "")))
    ran = {r.get("name") for r in recent if r.get("conclusion") == "success"}
    for name in KEY_JOBS:
        if name not in ran and name not in failed:
            out.append(_item("jobs", "warn", f"{name} didn't run in the last 24 hours"))
    return out


def fetch_runs(now: datetime) -> List[Dict]:
    import requests
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return []
    since = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs, page = [], 1
    while page <= 5:
        r = requests.get(f"https://api.github.com/repos/{repo}/actions/runs",
                         params={"created": f">={since}", "per_page": 100, "page": page},
                         headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                         timeout=30)
        r.raise_for_status()
        got = r.json().get("workflow_runs") or []
        runs += [{"name": x.get("name"), "conclusion": x.get("conclusion"), "created_at": x.get("created_at")}
                 for x in got]
        if len(got) < 100:
            break
        page += 1
    return runs


def check_grading(yest: str, today: str, load=None, review=None, sports_=("NBA", "NHL", "NFL", "NCAAF", "NCAAMB")):
    import pick_ledger as PL
    load = load or PL.load
    out = []
    led = load("strong", "ALL", yest)
    if led["rows"] and not led.get("graded_at"):
        out.append(_item("grading", "error", f"yesterday's strongest picks ({len(led['rows'])}) aren't graded yet"))
    elif led["rows"]:
        r = PL.record("strong", "ALL", yest, get=None) if load is PL.load else None
        if r:
            out.append(_item("grading", "info", f"yesterday's strongest picks: {r['hits']}–{r['misses']}"
                             + (f", {r['units']:+.2f}u at the prices shown" if r.get("priced") else "")))
    if review is None:
        import model_store as MS
        review = MS.load_daily_review
    missing = []
    for sp in sports_:
        try:
            led_sp = load("money", sp, yest)
            if led_sp["rows"] and not review(sp, today):
                missing.append(sp)
        except Exception:                                       # noqa: BLE001
            continue
    if missing:
        out.append(_item("grading", "warn", f"no morning review saved yet for {', '.join(missing)}"))
    return out


def check_data(checks: Optional[Dict]) -> List[Dict]:
    if not checks:
        return [_item("data", "warn", "the morning data checks haven't run")]
    out = [_item("data", i["level"] if i["level"] in ("error", "warn") else "warn", f"{i['check']}: {i['detail']}")
           for i in checks.get("issues") or []]
    return out


def check_shutoff(status: Optional[Dict], today: str) -> List[Dict]:
    out = []
    for k, v in sorted(((status or {}).get("groups") or {}).items()):
        if v.get("state") == "off" and (status.get("since") or {}).get(k, "") >= today:
            out.append(_item("shut-off", "warn", f"switched off this morning: {k.replace('|', ' · ')} "
                             f"({v['n']} picks, {v['roi']:+.1%} per $1)"))
        elif v.get("state") == "watch":
            out.append(_item("shut-off", "info", f"on watch: {k.replace('|', ' · ')} ({v['n']} picks, "
                             f"{v['roi']:+.1%} per $1)"))
    return out


def credits_left() -> Optional[int]:
    import requests
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        return None
    r = requests.get("https://api.the-odds-api.com/v4/sports", params={"apiKey": key}, timeout=20)
    v = r.headers.get("x-requests-remaining")
    return int(float(v)) if v is not None else None


def check_credits(left: Optional[int]) -> List[Dict]:
    if left is None:
        return []
    if left < LOW_CREDITS:
        return [_item("credits", "warn", f"Odds API credits low: {left:,} left")]
    return [_item("credits", "info", f"Odds API credits: {left:,} left")]


def summarize(items: Sequence[Dict]) -> str:
    e = sum(i["level"] == "error" for i in items)
    w = sum(i["level"] == "warn" for i in items)
    if e:
        return "error"
    return "warn" if w else "ok"


def run(now: Optional[datetime] = None, runs=None, checks=None, status=None, left=None, save=True,
        grading: Optional[Callable] = None) -> Dict:
    import props_engine as PE
    now = now or datetime.now(timezone.utc)
    today = PE._et_today()
    yest = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    items: List[Dict] = []
    steps = [
        ("jobs", lambda: check_jobs(fetch_runs(now) if runs is None else runs, now)),
        ("grading", grading or (lambda: check_grading(yest, today))),
        ("data", lambda: check_data(_setting(f"health:checks:{today}") if checks is None else checks)),
        ("shut-off", lambda: check_shutoff(_setting("shutoff:status") if status is None else status, today)),
        ("credits", lambda: check_credits(credits_left() if left is None else left)),
    ]
    for area, fn in steps:
        try:
            items += fn()
        except Exception as exc:                                # noqa: BLE001
            items.append(_item(area, "warn", f"couldn't check ({type(exc).__name__}: {str(exc)[:100]})"))
    rec = {"day": today, "at": now.isoformat(timespec="seconds"), "state": summarize(items), "items": items}
    if save:
        try:
            import model_store as MS
            MS.save_setting(KEY, rec)
        except Exception:                                       # noqa: BLE001
            pass
    return rec


def _setting(key):
    import model_store as MS
    return MS.get_setting(key, None)


def banner(rec: Optional[Dict], today: str) -> Optional[Dict]:
    """{"icon", "text", "items"} for the page line, or None when there's no check for today yet."""
    if not rec or rec.get("day") != today:
        return None
    try:
        import pytz
        at = datetime.fromisoformat(rec["at"]).astimezone(pytz.timezone("US/Eastern")).strftime("%-I:%M %p")
    except Exception:                                           # noqa: BLE001
        at = ""
    probs = [i for i in rec.get("items") or [] if i["level"] in ("error", "warn")]
    icon = {"ok": "✅", "warn": "⚠️", "error": "❌"}.get(rec.get("state"), "ℹ️")
    text = (f"Health check {at}: all clear" if not probs else
            f"Health check {at}: {len(probs)} thing{'s' if len(probs) != 1 else ''} to look at")
    return {"icon": icon, "text": text, "items": rec.get("items") or []}


def render(today: str) -> None:
    """The one-line banner (owner pages)."""
    import streamlit as st
    try:
        b = banner(_setting(KEY), today)
    except Exception:                                           # noqa: BLE001
        b = None
    if not b:
        return
    with st.expander(f"{b['icon']} {b['text']}", expanded=False):
        mark = {"error": "❌", "warn": "⚠️", "info": "ℹ️"}
        for i in b["items"]:
            st.markdown(f"{mark.get(i['level'], '•')} **{i['area']}** — {i['text']}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    rec = run()
    print(f"Morning check: {rec['state']}")
    for i in rec["items"]:
        print(f"  [{i['level']}] {i['area']}: {i['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
