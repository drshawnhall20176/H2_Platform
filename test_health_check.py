"""Nov 21: the morning health check (health_check.py)."""
from datetime import datetime, timezone

import health_check as HC

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


def _run(name, concl, hours_ago=2):
    from datetime import timedelta
    return {"name": name, "conclusion": concl, "created_at": (NOW - timedelta(hours=hours_ago)).isoformat()}


def test_failed_and_missing_jobs():
    runs = [_run("warm-slates", "failure"), _run("settle-results", "success"), _run("capture-closing-lines", "success"),
            _run("community-post", "success"), _run("capture-game-picks", "success", hours_ago=30)]
    out = HC.check_jobs(runs, NOW)
    texts = " | ".join(i["text"] for i in out)
    assert "warm-slates: 1 failed" in texts and "capture-game-picks didn't run" in texts
    assert next(i for i in out if "warm-slates" in i["text"])["level"] == "error"


def test_all_clear_and_banner():
    runs = [_run(n, "success") for n in HC.KEY_JOBS]
    rec = HC.run(now=NOW, runs=runs, checks={"issues": []}, status={}, left=12000, save=False, grading=lambda: [])
    assert rec["state"] == "ok"
    b = HC.banner(rec, rec["day"])
    assert b["icon"] == "✅" and "all clear" in b["text"]


def test_data_issues_and_low_credits_warn():
    rec = HC.run(now=NOW, runs=[_run(n, "success") for n in HC.KEY_JOBS],
                 checks={"issues": [{"check": "closes", "level": "warn", "detail": "2 bets"}]}, status={}, left=500,
                 save=False, grading=lambda: [])
    assert rec["state"] == "warn" and len([i for i in rec["items"] if i["level"] == "warn"]) == 2


def test_a_failure_a_later_run_made_good_is_a_note():
    from datetime import datetime, timezone
    import health_check as HC
    now = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
    runs = [{"name": "warm-slates", "conclusion": "failure", "created_at": "2026-11-22T21:00:00Z"},
            {"name": "warm-slates", "conclusion": "success", "created_at": "2026-11-22T22:00:00Z"},
            {"name": "close-watch", "conclusion": "success", "created_at": "2026-11-22T20:00:00Z"},
            {"name": "close-watch", "conclusion": "failure", "created_at": "2026-11-22T21:00:00Z"}]
    items = {i["text"].split(":")[0]: i["level"] for i in HC.check_jobs(runs, now) if i["text"].split(":")[0] in ("warm-slates", "close-watch")}
    assert items == {"warm-slates": "info", "close-watch": "warn"}
