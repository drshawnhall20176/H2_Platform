"""
capture_closing_lines.py — the runner that captures closing lines automatically.

Wakes on a timer (GitHub Action), fetches current odds for games that HAVEN'T started yet,
matches them to your open bets at the SAME book (via clv_capture), and writes the latest pre-game
price into each bet's close_odds. Run repeatedly through the evening: each run refreshes the price
for not-yet-started games, so the LAST update before a game starts becomes that game's closing
line. Once a game starts it drops out of the not-started set and its close_odds freezes — which is
exactly the closing line.

Writes to the SAME database the app reads. REQUIRES two env vars / GitHub secrets:
    ODDS_API_KEY   — to fetch odds
    DATABASE_URL   — the Supabase/Postgres URL, so closes are written where the app reads them
Without DATABASE_URL the bet log is an ephemeral SQLite file that vanishes when the runner ends,
so the capture would be lost — the runner refuses to run without it.

    python capture_closing_lines.py      # one capture pass
"""

import os
from datetime import datetime, timezone
from typing import List, Optional

import odds_api as O
import clv_capture as C
import betlog as B


def not_started(events: List[dict], now: Optional[datetime] = None) -> List[dict]:
    """Events whose commence_time is still in the future — the only ones whose price is a live
    pre-game (i.e. closing-ish) line. Anything already underway is excluded."""
    now = now or datetime.now(timezone.utc)
    live = []
    for e in events:
        try:
            start = datetime.fromisoformat(str(e.get("commence_time")).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if start > now:
            live.append(e)
    return live


def main() -> int:
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ODDS_API_KEY not set — cannot fetch odds.")
        return 1
    if not os.environ.get("DATABASE_URL") and not getattr(B, "USING_POSTGRES", False):
        print("DATABASE_URL not set — closes would be written to an ephemeral SQLite file and lost.\n"
              "Set the DATABASE_URL secret (your Supabase URL) so closing lines persist where the "
              "app reads them.")
        return 1

    open_bets = B.list_bets(settled=False)          # unsettled bets still need a closing line
    if not open_bets:
        print("No open bets — nothing to capture.")
        return 0

    # Fetch only the markets our open bets actually use (quota-friendly).
    needed = sorted({C.MARKET_TO_ODDS_KEY[b["market"]] for b in open_bets
                     if b.get("market") in C.MARKET_TO_ODDS_KEY})
    if not needed:
        print("Open bets have no recognizable prop markets — nothing to fetch.")
        return 0

    events = O.fetch_events(api_key)
    live = not_started(events)
    print(f"{len(open_bets)} open bets · {len(events)} events · {len(live)} not yet started · "
          f"markets: {', '.join(needed)}")
    if not live:
        print("No games left before first pitch — closing lines already frozen for started games.")
        return 0

    # Pull offers only for not-yet-started games, so any matched price is a live pre-game line.
    offers = []
    for e in live:
        try:
            js, _ = O.fetch_event_props(e["id"], api_key, needed)
            offers.extend(O.parse_event_offers(js))
        except Exception as ex:  # noqa: BLE001
            print(f"  (skip event {e.get('id')}: {type(ex).__name__})")

    report = C.capture_updates(open_bets, offers)
    updates = report["updates"]
    for bet_id, price in updates.items():
        try:
            B.update_bet(bet_id, close_odds=price)
        except Exception as ex:  # noqa: BLE001
            print(f"  (failed to write bet {bet_id}: {ex})")

    print(f"Captured/updated {len(updates)} closing lines.")
    if report["no_book"]:
        print(f"  {len(report['no_book'])} bets skipped — no book recorded, so no apples-to-apples "
              "close is possible. (Log bets via the Edge Board so the book is captured.)")
    if report["no_match"]:
        print(f"  {len(report['no_match'])} open bets had no current pre-game offer (game may have "
              "started, or that player/line isn't posted right now — a later run may catch it).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
