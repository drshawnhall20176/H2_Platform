"""
backfill_closing_lines.py — fill in close_odds for ALREADY-COMPLETED bets that never got one,
using The Odds API's historical odds product.

capture_closing_lines.py (the GitHub Action) can only ever capture a closing line for a game
that HASN'T STARTED YET when it runs — that's the whole design, and it's the right one for going
forward. But it means any bet that the live capture missed (workflow gap, book coverage hole,
game already started before the first run reached it) is permanently missing its close via that
path: the game's already over, there's no "not yet started" odds left to fetch. This script is
the one-time/occasional catch-up for those bets, using the SAME matching engine (clv_capture) and
the SAME database writer (betlog.update_bet) as the live path — the only thing that's different
is where the odds come from.

IMPORTANT — cost. This is NOT the same product as the rest of the app uses, and it is NOT cheap:
  - Requires a PAID Odds API plan. If your key is free-tier, every call below returns 401/403 —
    this script fails loudly on its first real call rather than quietly wasting a run.
  - Historical event-odds costs 10 credits x [markets requested] x [regions requested], PER EVENT
    PER SNAPSHOT — ten times the live per-event rate. This script only ever requests the specific
    markets a given event's missing bets actually need (never all 17 MLB markets blind), and
    prints a real cost estimate BEFORE spending anything, gated behind an explicit confirmation.

MLB ONLY FOR NOW — same honest scope as bet_settlement.py, and for the same reason: it's built
directly on mlb_engine.get_schedule (the free, authoritative source for a game's real commence
time and doubleheader game-number, already used elsewhere in this codebase) rather than routed
through sports.active(). A bet logged for another sport is left alone, not guessed at.

    python backfill_closing_lines.py                  # estimate cost, ask before spending
    python backfill_closing_lines.py --yes             # skip the confirmation prompt
    python backfill_closing_lines.py --limit 5          # only backfill the first 5 events (test run)
    python backfill_closing_lines.py --dates 2026-07-22,2026-07-23   # only these slate dates

Requires the same two things capture_closing_lines.py does:
    ODDS_API_KEY   — must be on a plan with historical access (see cost note above)
    DATABASE_URL   — your Supabase/Postgres URL, so backfilled closes land where the app reads them
"""

import argparse
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

import odds_api as O
import clv_capture as C
import betlog as B
import mlb_engine as E

SPORT_KEY = "MLB"
ODDS_SPORT = "baseball_mlb"


def snapshot_query_time(commence_iso: str, minutes_before: int) -> str:
    """The timestamp to actually query for a 'closing' snapshot -- commence_time MINUS a buffer,
    not commence_time itself.

    Confirmed against a real run, not theoretical: querying at the exact commence_time got back
    a raw response with ZERO bookmakers for ANY book on 4 of 5 events (not just missing
    draftkings -- an empty bookmakers list entirely). The likely reason: sportsbooks commonly
    suspend player-prop markets in the last few minutes before first pitch while lineups get
    finalized, so a snapshot at t=0 can land right inside that suspended window.

    This also matches how the LIVE capture path already behaves in practice, not just in theory:
    capture_closing_lines.py's actual 'closing' price for any bet is whatever its last
    successful run captured before the game started -- and given that workflow's own 15-30
    minute cadence, that's usually several minutes before literal first pitch already, never
    exactly at it. Querying history at the exact instant of commence_time was the mismatch, not
    the historical product itself."""
    dt = datetime.fromisoformat(commence_iso.replace("Z", "+00:00"))
    return (dt - timedelta(minutes=minutes_before)).strftime("%Y-%m-%dT%H:%M:%SZ")


def game_label(g: Dict) -> str:
    """Exact label a bet was logged under for this game -- must match mlb_engine's own
    construction (views/.../8_Dinger_Engine.py and build_slate both build labels this same way:
    away @ home, ALWAYS with the "(Game N)" suffix, even for gameNumber=1, not just doubleheaders
    -- confirmed against a real user's exported bet log, where every single row's `game` field
    carried the suffix). Getting this wrong silently loses every match, so it's centralized here
    instead of re-typed at each call site."""
    return f"{g['away_name']} @ {g['home_name']} (Game {g['gameNumber']})"


def _unwrap_events_response(raw: object) -> List[Dict]:
    """Pull the event list out of fetch_historical_events' raw response, whatever shape it turns
    out to be -- wrapped ({"data": [...]}, matching the historical event-ODDS wrapper) or bare
    (a plain list, matching how the LIVE /events endpoint already behaves in this same module).
    Returns [] for anything else, rather than raising, so a genuine shape surprise shows up as
    an empty, diagnosable result instead of a crashed run."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        inner = raw.get("data")
        if isinstance(inner, list):
            return inner
    return []


def resolve_events_for_date(slate_date: str, api_key: str) -> Tuple[Dict[str, Dict], List[str], Dict]:
    """For one slate_date: the real MLB schedule (free, authoritative commence times) joined to
    this provider's OWN event ids for that date (needed only because the historical event-odds
    endpoint is keyed by the provider's event id, not MLB's gamePk).

    Returns (matched, unmatched_labels, last_headers):
      matched: {game_label: {"event_id", "commence_iso", "away_name", "home_name"}}
      unmatched_labels: real MLB games this date whose provider-side event couldn't be found by
        team-name match -- reported, not silently dropped, same as bet_settlement.py's own
        "unresolved" bucket for the same reason.
    """
    schedule = E.get_schedule(slate_date)
    if not schedule:
        return {}, [], {}

    # A timestamp at/after this date's LAST commence_time guarantees every game that day was
    # already posted when this historical snapshot was taken.
    last_start = max((g["game_date"] for g in schedule if g.get("game_date")), default=None)
    events_at = last_start or f"{slate_date}T23:59:00Z"
    raw, headers = O.fetch_historical_events(api_key, events_at, sport=ODDS_SPORT)
    events = _unwrap_events_response(raw)

    if not events:
        # The real MLB schedule (a separate, already-proven-working data source) says games
        # existed this date -- an empty events list here means either the shape assumption in
        # _unwrap_events_response is wrong, or the account/key genuinely has no historical
        # coverage for this date/sport. Print the raw shape so this is diagnosable from a run's
        # log instead of silently producing "0 game(s) resolved" with no further clue.
        preview = (f"keys={list(raw.keys())}" if isinstance(raw, dict)
                  else f"type={type(raw).__name__}, value={str(raw)[:200]!r}")
        print(f"    ⚠ 0 events returned for {slate_date} (MLB schedule shows {len(schedule)} "
             f"real game(s) that day) -- raw response {preview}")

    # Team-name match: exact first, then case/whitespace-normalized fallback. Odds API and MLB
    # Stats API both use full official team names for MLB in practice, so exact match should be
    # the common case -- the normalized fallback exists for the rare punctuation/whitespace
    # mismatch, not as the primary path.
    by_team_pair: Dict[Tuple[str, str], Dict] = {}
    for e in events:
        key = ((e.get("away_team") or "").strip().lower(), (e.get("home_team") or "").strip().lower())
        by_team_pair[key] = e

    matched: Dict[str, Dict] = {}
    unmatched: List[str] = []
    for g in schedule:
        label = game_label(g)
        key = (g["away_name"].strip().lower(), g["home_name"].strip().lower())
        e = by_team_pair.get(key)
        if e is None:
            unmatched.append(label)
            continue
        matched[label] = {
            "event_id": e.get("id"),
            "commence_iso": g.get("game_date") or e.get("commence_time"),  # prefer MLB's own precise time
            "away_name": g["away_name"], "home_name": g["home_name"],
        }
    return matched, unmatched, headers


def group_missing_bets_by_event(missing_bets: List[Dict], resolved: Dict[str, Dict]) -> Dict[str, Dict]:
    """Pure grouping, no I/O -- one entry per real matched event, carrying only the bets that
    reference it and only the UNION of markets those specific bets need (this is what keeps the
    10x-per-market historical cost from exploding: an event with one missing "Batter HR" bet
    costs 10 credits, not 170, because we never ask for the sport's other 16 markets it doesn't
    need)."""
    groups: Dict[str, Dict] = {}
    unresolved: List[Dict] = []
    for b in missing_bets:
        label = b.get("game")
        info = resolved.get(label)
        if info is None:
            unresolved.append(b)
            continue
        key = info["event_id"]
        grp = groups.setdefault(key, {"event": info, "bets": [], "markets": set()})
        grp["bets"].append(b)
        okey = C.MARKET_TO_ODDS_KEY.get(b.get("market"))
        if okey:
            grp["markets"].add(okey)
    return groups, unresolved


def estimate_cost(groups: Dict[str, Dict], regions: str) -> int:
    """10 credits x markets x regions, per event -- the documented historical event-odds rate.
    Pure function so the cost preview shown to the person before they spend anything is
    independently testable, not just eyeballed against a live run."""
    n_regions = len([r for r in regions.split(",") if r])
    return sum(10 * len(g["markets"]) * n_regions for g in groups.values())


def backfill_event(event_key: str, group: Dict, api_key: str, regions: str,
                   minutes_before: int = 10) -> Dict:
    """The one expensive call per event: fetch that event's historical odds at a snapshot
    shortly BEFORE its real commence time (see snapshot_query_time's docstring for why exact
    commence_time is the wrong moment to query), then match each of this event's missing bets
    against the returned offers using the EXACT SAME pure matcher (clv_capture.bet_close_price)
    the live capture path uses -- no separate matching logic to keep in sync."""
    info = group["event"]
    markets = sorted(group["markets"])
    query_iso = snapshot_query_time(info["commence_iso"], minutes_before)
    js, headers = O.fetch_historical_event_props(
        info["event_id"], api_key, markets, query_iso, regions=regions, sport=ODDS_SPORT)

    event_json = js.get("data")
    if event_json is None:
        # The documented wrapper shape wasn't there -- surface this loudly on the very first
        # occurrence instead of silently matching nothing, per this module's own docstring.
        print(f"    ⚠ unexpected historical response shape for event {info['event_id']} -- "
              f"no 'data' key. Raw keys: {list(js.keys())}")
        event_json = js

    offers = O.parse_event_offers(event_json, supported_markets=markets)
    snapshot_ts = js.get("timestamp")

    report = C.capture_updates(group["bets"], offers, market_map=C.MARKET_TO_ODDS_KEY)
    report["headers"] = headers
    report["snapshot_ts"] = snapshot_ts
    report["requested_date"] = query_iso
    report["commence_iso"] = info["commence_iso"]

    if report["no_match"]:
        # The previous run's log couldn't distinguish "the book genuinely has no historical data
        # for this market/snapshot" from "a parsing bug on our side is silently dropping real
        # data that WAS returned" -- both looked identical (a no_match line, quota barely moved).
        # This is the raw, PRE-FILTER view: every bookmaker key and market key the response
        # actually contained, before parse_event_offers' supported_markets filter drops anything.
        raw_books = {bm.get("key"): sorted({m.get("key") for m in bm.get("markets", [])})
                    for bm in (event_json.get("bookmakers") or [])}
        wanted_books = {(b.get("book") or "").strip().lower() for b in group["bets"]}
        print(f"    raw response had {len(raw_books)} bookmaker(s): {raw_books}")
        print(f"    bet(s) needed book(s): {sorted(wanted_books)}")

    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="skip the cost-confirmation prompt")
    ap.add_argument("--limit", type=int, default=None, help="only backfill the first N events (test run)")
    ap.add_argument("--dates", type=str, default=None,
                    help="comma-separated slate_dates to restrict to, e.g. 2026-07-22,2026-07-23")
    ap.add_argument("--regions", type=str, default="us")
    ap.add_argument("--minutes-before", type=int, default=10,
                    help="query this many minutes before each game's real commence time, not "
                         "commence_time itself -- default 10, based on a real run where querying "
                         "exact commence_time returned zero bookmakers on most events (props "
                         "commonly get suspended in the last few minutes before first pitch). "
                         "Try a larger value (e.g. 20 or 30) if this still comes back empty.")
    args = ap.parse_args()

    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ODDS_API_KEY not set — cannot fetch odds.")
        return 1
    if not os.environ.get("DATABASE_URL") and not getattr(B, "USING_POSTGRES", False):
        print("DATABASE_URL not set — backfilled closes would be written to an ephemeral SQLite "
              "file and lost. Set the DATABASE_URL secret (your Supabase URL) first.")
        return 1

    all_bets = B.list_bets(sport=SPORT_KEY)
    missing = [b for b in all_bets if b.get("close_odds") is None and (b.get("book") or "").strip()]
    skipped_no_book = [b for b in all_bets if b.get("close_odds") is None and not (b.get("book") or "").strip()]
    if args.dates:
        wanted = set(args.dates.split(","))
        missing = [b for b in missing if b.get("slate_date") in wanted]
    if not missing:
        print("No MLB bets are missing a closing line (for the given --dates, if set). Nothing to do.")
        return 0

    by_date: Dict[str, List[Dict]] = {}
    for b in missing:
        by_date.setdefault(b.get("slate_date"), []).append(b)
    print(f"{len(missing)} MLB bet(s) missing close_odds across {len(by_date)} slate date(s)"
         + (f"  ({len(skipped_no_book)} more skipped — no book recorded, no apples-to-apples close "
            "possible)" if skipped_no_book else "") + ".")

    resolved: Dict[str, Dict] = {}
    all_unmatched: List[str] = []
    print("\nResolving each date's real schedule against this provider's own event ids...")
    for slate_date in sorted(by_date):
        matched, unmatched, _ = resolve_events_for_date(slate_date, api_key)
        resolved.update(matched)
        all_unmatched.extend(f"{slate_date}: {u}" for u in unmatched)
        print(f"  {slate_date}: {len(matched)} game(s) resolved" +
             (f", {len(unmatched)} unresolved" if unmatched else ""))

    groups, unresolved_bets = group_missing_bets_by_event(missing, resolved)
    if args.limit is not None:
        groups = dict(list(groups.items())[:args.limit])

    if not groups:
        print("\nNo missing bets could be matched to a resolved event — nothing to backfill.")
        if unresolved_bets:
            print(f"({len(unresolved_bets)} bet(s) had no matching event; their 'game' field may "
                  "not match the schedule's team names exactly.)")
        print("\nExiting non-zero on purpose: a run that changes nothing shouldn't show green. "
             "Check the '⚠ 0 events returned' lines above (if any) for the actual cause.")
        return 2

    est = estimate_cost(groups, args.regions)
    n_bets_covered = sum(len(g["bets"]) for g in groups.values())
    print(f"\n{len(groups)} event(s), {n_bets_covered} bet(s) covered — "
         f"estimated cost: {est} credits (10 x markets x regions, per event).")
    for info_key, g in list(groups.items())[:10]:
        info = g["event"]
        print(f"  {info['away_name']} @ {info['home_name']} — {len(g['bets'])} bet(s), "
             f"markets={sorted(g['markets'])}, ~{10 * len(g['markets']) * len(args.regions.split(','))} credits")
    if len(groups) > 10:
        print(f"  ... and {len(groups) - 10} more event(s)")
    if unresolved_bets:
        print(f"  ({len(unresolved_bets)} bet(s) could not be matched to any event and will be skipped)")

    if not args.yes:
        resp = input(f"\nSpend ~{est} credits to backfill {n_bets_covered} bet(s)? [y/N] ").strip().lower()
        if resp != "y":
            print("Cancelled — no calls made, no credits spent.")
            return 0

    total_updates = 0
    total_no_match = 0
    for event_key, g in groups.items():
        info = g["event"]
        print(f"\n[{info['away_name']} @ {info['home_name']}] requesting {sorted(g['markets'])} "
             f"at {snapshot_query_time(info['commence_iso'], args.minutes_before)} "
             f"(commence {info['commence_iso']}, {args.minutes_before} min buffer)...")
        try:
            report = backfill_event(event_key, g, api_key, args.regions, args.minutes_before)
        except O.OddsAPIError as ex:
            print(f"  ✗ {ex}")
            if "401" in str(ex) or "403" in str(ex):
                print("  This usually means the key's plan doesn't include historical odds access "
                     "— check your plan at the-odds-api.com before retrying.")
            continue
        print(f"  snapshot returned: {report.get('snapshot_ts')} (requested {report.get('requested_date')})")
        for bet_id, price in report["updates"].items():
            try:
                B.update_bet(bet_id, close_odds=price)
                total_updates += 1
            except Exception as ex:  # noqa: BLE001
                print(f"  (failed to write bet {bet_id}: {ex})")
        if report["no_match"]:
            total_no_match += len(report["no_match"])
            print(f"  {len(report['no_match'])} bet(s) had no matching offer in this snapshot "
                 "(that book/player/line combo wasn't posted at close time).")
        used = report["headers"].get("used")
        remaining = report["headers"].get("remaining")
        if used is not None:
            print(f"  quota: {used} used, {remaining} remaining")

    print(f"\nBackfilled {total_updates} closing line(s). {total_no_match} bet(s) had no offer at close. "
         f"{len(unresolved_bets)} bet(s) had no matching event.")
    if total_updates == 0:
        print("Exiting non-zero on purpose: this run tried to backfill real bets but wrote zero "
             "rows. Check the ✗ error lines above (if any) for the actual cause.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
