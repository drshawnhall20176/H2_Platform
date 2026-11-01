"""
capture_ufc_odds.py — save every upcoming UFC bout's prices before it starts (ufc_review.capture), for the morning
review. Run by .github/workflows/capture-ufc-odds.yml through fight day.

Checks the free events list first and only pulls odds (2 credits: moneyline + rounds total, every US book) when a
bout starts within the next WINDOW_H hours, so non-fight days cost nothing.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import ufc_review as UR

EVENTS_URL = "https://api.the-odds-api.com/v4/sports/mma_mixed_martial_arts/events"
WINDOW_H = 14


def upcoming(events, now, hours=WINDOW_H) -> int:
    n = 0
    for ev in events or []:
        try:
            t = datetime.fromisoformat(str(ev.get("commence_time")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if now < t <= now + timedelta(hours=hours):
            n += 1
    return n


def main() -> int:
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("ODDS_API_KEY isn't set."); return 1
    now = datetime.now(timezone.utc)
    events = UR._http(EVENTS_URL, {"apiKey": key})
    if events is None:
        print("Couldn't read the UFC events list."); return 1
    n = upcoming(events, now)
    if not n and not os.environ.get("UFC_CAPTURE_FORCE"):
        print(f"No bout in the next {WINDOW_H} hours — nothing to save."); return 0
    saved = UR.capture(key, now=now)
    print(f"{n} bout(s) in the next {WINDOW_H} hours; saved prices for {saved} upcoming bout(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
