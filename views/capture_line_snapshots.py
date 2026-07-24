"""
capture_line_snapshots.py — the runner that captures REAL LINE MOVEMENT HISTORY.

DIFFERENT JOB FROM capture_closing_lines.py: that script tracks ONE closing price per your own
OPEN BET, for CLV ("did I beat the close on MY bet?"). This one tracks how EVERY player-prop line
on tonight's slate moves over the course of the day — not just the ones you've bet — building the
time series a future line-movement chart (the stock-candlestick analog Matchup Lab's existing
recent-form trend chart isn't) actually needs to exist before it can be drawn. Neither script
replaces the other; they answer genuinely different questions and both are worth running.

SPORT-AWARE, same as capture_closing_lines.py: every ENABLED sport in the registry gets its own
slate captured, using that sport's own odds_sport_key/markets — not hardcoded to MLB.

COST NOTE, read before scheduling this — genuinely different from capture_closing_lines.py's
footprint: that script only fetches props for games tied to bets you've actually placed, a small,
bounded set. This script fetches props for EVERY not-yet-started game across every enabled sport,
every run. Odds API bills by request/market. Recommend a coarser cadence than CLV capture's tight
per-evening schedule — a few times a day (morning line, midday, a couple hours before first
tip/pitch) is enough to see real movement without re-fetching the whole slate every 15 minutes.

DE-DUPLICATED ON WRITE (see line_history.py): a snapshot is only stored when the line or price
actually changed since the last capture for that exact (sport, player, market, side, book) — an
unchanged line at the next run doesn't add a redundant row, keeping storage and any future chart
meaningfully sparse rather than noisy.

Writes to the SAME database capture_closing_lines.py and the app use (line_history.py mirrors
betlog.py's dual-backend selection). Without DATABASE_URL the history is an ephemeral SQLite file
that vanishes when the runner ends — the runner refuses to run without it, same discipline as
capture_closing_lines.py.

    python capture_line_snapshots.py      # one capture pass, every enabled sport's full slate
"""

import os
from typing import Dict, List

import odds_api as O
import line_history as LH
import sports
from capture_closing_lines import not_started   # reused, not duplicated — same definition either script needs


def capture_for_sport(sport_key: str, api_key: str) -> Dict:
    """Snapshot every currently-offered line for one sport's not-yet-started games. Returns
    {"events_checked", "live_events", "offers_seen", "snapshots_recorded"}."""
    sport = sports.get(sport_key)
    empty = {"events_checked": 0, "live_events": 0, "offers_seen": 0, "snapshots_recorded": 0}
    if not sport.markets:
        return empty   # placeholder sport, nothing to capture yet

    events = O.fetch_events(api_key, sport=sport.odds_sport_key)
    live = not_started(events)
    if not live:
        return {**empty, "events_checked": len(events)}

    offers_seen = 0
    snapshots_recorded = 0
    for e in live:
        game_label = f"{e.get('away_team', '?')} @ {e.get('home_team', '?')}"
        try:
            js, _ = O.fetch_event_props(e["id"], api_key, sport.markets, sport=sport.odds_sport_key)
            offers = O.parse_event_offers(js, supported_markets=sport.markets)
        except Exception as ex:  # noqa: BLE001
            print(f"  (skip {sport_key} event {e.get('id')}: {type(ex).__name__})")
            continue

        for o in offers:
            for side, book_prices in (("over", o.get("over") or {}), ("under", o.get("under") or {})):
                for book, price in book_prices.items():
                    offers_seen += 1
                    try:
                        wrote = LH.record_snapshot(
                            sport=sport_key, player=o["player"], market=o["market"], side=side,
                            line=o.get("point"), price=price, book=book, game=game_label,
                            commence_time=e.get("commence_time"))
                        if wrote:
                            snapshots_recorded += 1
                    except Exception as ex:  # noqa: BLE001
                        print(f"  (failed to record {sport_key} {o.get('player')}/{o.get('market')}: {ex})")

    return {"events_checked": len(events), "live_events": len(live),
           "offers_seen": offers_seen, "snapshots_recorded": snapshots_recorded}


def main() -> int:
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ODDS_API_KEY not set — cannot fetch odds.")
        return 1
    if not os.environ.get("DATABASE_URL") and not getattr(LH, "USING_POSTGRES", False):
        print("DATABASE_URL not set — line history would be written to an ephemeral SQLite file "
              "and lost.\nSet the DATABASE_URL secret (your Supabase URL) so history persists "
              "where the app reads it.")
        return 1

    live_sports: List[str] = [s.key for s in sports.enabled_sports()]
    if not live_sports:
        print("No enabled sports — nothing to capture.")
        return 0
    print(f"Capturing line snapshots for {len(live_sports)} enabled sport(s): {', '.join(live_sports)}")

    total_recorded = 0
    total_seen = 0
    for sport_key in live_sports:
        try:
            report = capture_for_sport(sport_key, api_key)
        except Exception as ex:  # noqa: BLE001
            print(f"[{sport_key}] capture failed: {type(ex).__name__}: {ex}")
            continue
        print(f"[{sport_key}] {report['events_checked']} events · {report['live_events']} not yet "
             f"started · {report['offers_seen']} offer(s) seen · "
             f"{report['snapshots_recorded']} new snapshot(s) (line/price actually moved)")
        total_recorded += report["snapshots_recorded"]
        total_seen += report["offers_seen"]

    print(f"Recorded {total_recorded} new line-movement snapshot(s) out of {total_seen} offer(s) "
         f"checked ({total_seen - total_recorded} unchanged since last capture, correctly skipped).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
