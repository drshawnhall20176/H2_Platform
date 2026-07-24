"""
capture_closing_lines.py — the runner that captures closing lines automatically.

Wakes on a timer (GitHub Action), fetches current odds for games that HAVEN'T started yet,
matches them to your open bets at the SAME book (via clv_capture), and writes the latest pre-game
price into each bet's close_odds. Run repeatedly through the evening: each run refreshes the price
for not-yet-started games, so the LAST update before a game starts becomes that game's closing
line. Once a game starts it drops out of the not-started set and its close_odds freezes — which is
exactly the closing line.

SPORT-AWARE: open bets are grouped by their `sport` column and each sport's events/markets/
market_map are fetched and matched separately, using that sport's own registry entry
(sports.get(...).odds_sport_key / .market_map / .single_line_markets) rather than assuming MLB.
This runner used to be MLB-only in three separate spots (fetch_events with no sport=, markets
filtered through clv_capture's MLB-only default MARKET_TO_ODDS_KEY, parse_event_offers with no
supported_markets=) — the same class of gap that fetch_slate_props had before it was fixed for
Edge Board. WNBA bets were silently never getting a closing line captured. Fixed here the same way.

Writes to the SAME database the app reads. REQUIRES two env vars / GitHub secrets:
    ODDS_API_KEY   — to fetch odds
    DATABASE_URL   — the Supabase/Postgres URL, so closes are written where the app reads them
Without DATABASE_URL the bet log is an ephemeral SQLite file that vanishes when the runner ends,
so the capture would be lost — the runner refuses to run without it.

    python capture_closing_lines.py      # one capture pass, every sport with open bets
"""

import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import odds_api as O
import clv_capture as C
import betlog as B
import sports


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


def capture_for_sport(sport_key: str, sport_bets: List[Dict], api_key: str) -> Dict:
    """Capture closing lines for one sport's open bets. Returns the same shape as
    clv_capture.capture_updates, plus 'events_checked'/'live_events' for the summary line."""
    sport = sports.get(sport_key)
    needed = sorted({sport.market_map[b["market"]] for b in sport_bets
                     if b.get("market") in sport.market_map})
    if not needed:
        return {"updates": {}, "no_book": [], "no_match": [b.get("id") for b in sport_bets],
               "events_checked": 0, "live_events": 0}

    events = O.fetch_events(api_key, sport=sport.odds_sport_key)
    live = not_started(events)
    if not live:
        return {"updates": {}, "no_book": [], "no_match": [b.get("id") for b in sport_bets],
               "events_checked": len(events), "live_events": 0}

    offers = []
    for e in live:
        try:
            js, _ = O.fetch_event_props(e["id"], api_key, needed, sport=sport.odds_sport_key)
            offers.extend(O.parse_event_offers(js, supported_markets=needed))
        except Exception as ex:  # noqa: BLE001
            print(f"  (skip {sport_key} event {e.get('id')}: {type(ex).__name__})")

    report = C.capture_updates(sport_bets, offers, market_map=sport.market_map,
                               single_line_markets=sport.single_line_markets)
    report["events_checked"] = len(events)
    report["live_events"] = len(live)
    return report


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

    open_bets = B.list_bets(settled=False)          # unsettled bets still need a closing line, any sport
    if not open_bets:
        print("No open bets — nothing to capture.")
        return 0

    by_sport: Dict[str, List[Dict]] = {}
    for b in open_bets:
        by_sport.setdefault(b.get("sport") or "MLB", []).append(b)   # legacy rows default to MLB
    print(f"{len(open_bets)} open bet(s) across {len(by_sport)} sport(s): "
          f"{', '.join(f'{k}={len(v)}' for k, v in by_sport.items())}")

    total_updates = 0
    for sport_key, sport_bets in by_sport.items():
        try:
            report = capture_for_sport(sport_key, sport_bets, api_key)
        except Exception as ex:  # noqa: BLE001
            print(f"[{sport_key}] capture failed: {type(ex).__name__}: {ex}")
            continue

        print(f"[{sport_key}] {len(sport_bets)} open bets · {report['events_checked']} events · "
              f"{report['live_events']} not yet started")
        for bet_id, price in report["updates"].items():
            try:
                B.update_bet(bet_id, close_odds=price)
                total_updates += 1
            except Exception as ex:  # noqa: BLE001
                print(f"  (failed to write bet {bet_id}: {ex})")
        if report["no_book"]:
            print(f"  {len(report['no_book'])} bets skipped — no book recorded, so no apples-to-apples "
                  "close is possible. (Log bets via the Edge Board so the book is captured.)")
        if report["no_match"]:
            print(f"  {len(report['no_match'])} open bets had no current pre-game offer (game may have "
                  "started, or that player/line isn't posted right now — a later run may catch it).")

    print(f"Captured/updated {total_updates} closing line(s) total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
