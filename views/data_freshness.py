"""
data_freshness.py — a single, honest answer to "is the data this platform depends on actually
current, or silently stale?"

WHY THIS EXISTS: this session found four separate real bugs in the catcher-framing refresh
pipeline alone, and every single one was invisible until someone opened a page and noticed
something looked off — a parse failure, a column-mapping mismatch, a cross-endpoint string
mismatch, a missing hydration parameter. A green checkmark on a GitHub Actions run told us
nothing about whether the actual data behind the app was current. This module exists to make
that visible in one place, at a glance, instead of requiring a person to notice a downstream
symptom and go hunting.

TRACKS THE FILE-BASED SOURCES SPECIFICALLY (statcast_batters.csv, catcher_framing.csv,
pitcher_arsenals.csv, hitter_pitch_splits.csv, hitter_pitch_type_splits.csv) -- the exact files
that caused this session's real bugs, refreshed by refresh-statcast.yml and refresh-matchups.yml,
both on a real, confirmed daily (24h) cron schedule, not a guessed cadence. Line-history/CLV data
lives in a database rather than a committed file (a genuinely different mechanism -- checking its
freshness would mean a live DB query, not a file check), deliberately left out of this v1 rather
than forcing a different kind of check into the same shape.

A FILE'S OWN MODIFICATION TIME IS THE FRESHNESS SIGNAL, DELIBERATELY, NOT A NEW STATUS LOG: these
files are committed to git by their own refresh workflow and pulled fresh on each deploy -- if a
refresh silently fails, the file is never rewritten, so its mtime stays exactly where it was after
the last successful run. That's a real, honest signal already sitting on disk, not something that
needed new instrumentation added to every refresh script to produce.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

import statcast_data as SC
import matchup_data as MD

# (display name, file path, expected refresh cadence in hours, minimum sane row count)
# Cadences are the REAL, confirmed cron schedules from each file's own workflow (both currently
# daily) -- not guessed. min_rows are real, reasoned floors: a full-league Statcast/arsenal pull
# producing under a few dozen rows is itself a strong signal something upstream broke, the same
# kind of floor already used inside each refresh script's own validation step.
TRACKED_SOURCES = [
    ("Statcast batters", SC.DEFAULT_PATH, 24, 50),
    ("Catcher framing", SC.CATCHER_FRAMING_PATH, 24, 10),
    ("Pitcher arsenals", MD.ARSENAL_PATH, 24, 50),
    ("Hitter pitch splits", MD.HITTER_PATH, 24, 50),
    ("Hitter pitch type splits", MD.HITTER_TYPE_PATH, 24, 50),
]

STALE_MULTIPLIER = 2.0   # a source counts "stale" (yellow) once it's this many times older than
                        # its own expected cadence -- e.g. a daily source stale past 48h, not 24h
                        # exactly, so a run that's merely a few hours late (GitHub Actions queue
                        # delays are real and common) doesn't get flagged as if something broke


def check_source(name: str, path: str, expected_cadence_hours: float, min_rows: int,
                 now: Optional[float] = None) -> Dict[str, Any]:
    """Check ONE tracked data source's real freshness. now is injectable (a real unix timestamp)
    so this is deterministically testable rather than depending on wall-clock time during tests.

    Returns {"name", "status" ("green"/"yellow"/"red"), "reason" (None if green), "last_modified"
    (datetime or None), "age_hours" (float or None), "row_count" (int or None)}.

    STATUS LOGIC, STATED PLAINLY:
    - "red": the file is missing entirely, or exists but is empty/unreadable/below min_rows --
      the same kind of "committing anyway would be worse than refusing" floor already used inside
      the refresh scripts themselves, applied here as a READ-time check instead.
    - "yellow": the file is real and readable, but its own age exceeds STALE_MULTIPLIER times its
      expected cadence -- old enough that its own refresh workflow has very likely failed
      silently at least once, not just run a little late.
    - "green": present, readable, a real row count, and recently refreshed."""
    now = time.time() if now is None else now
    if not os.path.exists(path):
        return {"name": name, "status": "red", "reason": "File not found — refresh may have "
                "never run, or never successfully written this file",
                "last_modified": None, "age_hours": None, "row_count": None}

    mtime = os.path.getmtime(path)
    age_hours = round((now - mtime) / 3600, 1)
    last_modified = datetime.fromtimestamp(mtime)

    try:
        df = pd.read_csv(path)
        row_count = len(df)
    except Exception as e:  # noqa: BLE001
        return {"name": name, "status": "red", "reason": f"File exists but couldn't be read "
                f"as a CSV ({type(e).__name__}: {e})",
                "last_modified": last_modified, "age_hours": age_hours, "row_count": None}

    if row_count < min_rows:
        return {"name": name, "status": "red",
                "reason": f"Only {row_count} row(s) — below the expected floor of {min_rows}, "
                f"a strong sign the last refresh produced incomplete or empty data",
                "last_modified": last_modified, "age_hours": age_hours, "row_count": row_count}

    if age_hours > expected_cadence_hours * STALE_MULTIPLIER:
        return {"name": name, "status": "yellow",
                "reason": f"Last updated {age_hours:.0f}h ago — expected roughly every "
                f"{expected_cadence_hours:.0f}h, this is stale enough that the refresh has "
                f"likely failed at least once",
                "last_modified": last_modified, "age_hours": age_hours, "row_count": row_count}

    return {"name": name, "status": "green", "reason": None,
            "last_modified": last_modified, "age_hours": age_hours, "row_count": row_count}


def check_all_sources(sources: Optional[List] = None, now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Check every tracked source. sources defaults to TRACKED_SOURCES; overridable for testing
    with a smaller/synthetic set. Returns one result dict per source, in the same order given."""
    sources = TRACKED_SOURCES if sources is None else sources
    return [check_source(name, path, cadence, min_rows, now=now)
           for name, path, cadence, min_rows in sources]


def overall_status(results: List[Dict[str, Any]]) -> str:
    """The single worst status across all sources — "red" if any source is red, else "yellow" if
    any is yellow, else "green". A one-line summary for an at-a-glance indicator (e.g. Command
    Center's own KPI row) without needing the full per-source breakdown."""
    statuses = {r["status"] for r in results}
    if "red" in statuses:
        return "red"
    if "yellow" in statuses:
        return "yellow"
    return "green"
