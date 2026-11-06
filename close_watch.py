"""
close_watch.py — capture each open bet's closing price just before ITS game starts (Nov 6).

Why: capture-closing-lines runs on a 15-30 minute cron, but GitHub skips most scheduled runs -- on Sunday Nov 1 it ran
4 times all day, the first at 1:17pm ET, after every early NFL game had kicked off. Since Oct 30 only 25 of 126 logged
singles got a closing price, and closing-line value is the evidence an investor trusts most.

How: one long run (up to WATCH_MINUTES) that knows the kickoff of every game with an open bet and wakes for it:
  CAPTURE_LEADS minutes before kickoff (45 and 5), it fetches that one game's odds -- the player-prop markets and/or
  spread / total / moneyline the bets need -- at the bet's own book and line, and writes close_odds. The 5-minute
  capture overwrites the 45-minute one; if the line has moved off the bet's number by then, the earlier price stays.
Started three times a day by cron (any one that lands covers ~6 hours) and right after bets are logged (log-plays).
Only games with open bets are fetched, once or twice each, so it costs fewer Odds API credits than polling every game.

Skipped on purpose: live bets (placed after the start -- notes begin "Live"), parlay headers and legs (no single
price), and sports without an Odds API feed (tennis, the international leagues).

    python close_watch.py                    # watch until the window ends
    python close_watch.py --once             # one capture pass for games starting within the next 60 minutes
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

WATCH_MINUTES = 345
CAPTURE_LEADS = (45, 5)
EVENTS_REFRESH_S = 1800
GAME_MARKETS = {"Spread": "spreads", "Puck Line": "spreads", "Run Line": "spreads", "Total": "totals",
                "Moneyline": "h2h"}


def _norm(s) -> str:
    return "".join(c for c in str(s or "").lower() if c.isalnum())


def _when(e: Dict) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(e.get("commence_time")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def watchable(b: Dict) -> bool:
    import betlog as B
    return (not B.is_parlay_header(b) and not B._ticket(b) and b.get("entry_odds") is not None
            and not str(b.get("notes") or "").strip().lower().startswith("live")
            and bool((b.get("book") or "").strip()))


def match_event(bet: Dict, events: List[Dict]) -> Optional[Dict]:
    """The event for a bet's game label ("Away @ Home" / "A vs B"): both teams' names found in it."""
    g = _norm(bet.get("game"))
    if not g:
        return None
    for e in events:
        h, a = _norm(e.get("home_team")), _norm(e.get("away_team"))
        if h and a and h in g and a in g:
            return e
    return None


def game_line_price(bet: Dict, event_json: Dict) -> Optional[int]:
    """The bet's price at its own book and line for a spread / total / moneyline, from one event's odds."""
    import odds_api as O
    key = GAME_MARKETS.get(bet.get("market"))
    book = O.canonical_book(bet.get("book"))
    if not key or not book:
        return None
    side = str(bet.get("side") or "")
    for bm in event_json.get("bookmakers") or []:
        if O.canonical_book(bm.get("key")) != book:
            continue
        for mk in bm.get("markets") or []:
            if mk.get("key") != key:
                continue
            for oc in mk.get("outcomes") or []:
                if key == "totals":
                    if str(oc.get("name", "")).lower() != side.lower():
                        continue
                elif _norm(oc.get("name")) != _norm(side):
                    continue
                if key != "h2h" and bet.get("line") is not None and oc.get("point") is not None \
                        and float(oc["point"]) != float(bet["line"]):
                    continue
                if oc.get("price") is not None:
                    return int(oc["price"])
    return None


def capture_event(event: Dict, bets: List[Dict], api_key: str, sport_key: str) -> Dict[int, int]:
    """{bet_id: price} for one game's bets."""
    import clv_capture as C
    import odds_api as O
    import sports
    sp = sports.get(sport_key)
    prop_keys = sorted({sp.market_map[b["market"]] for b in bets if b.get("market") in sp.market_map})
    game_keys = sorted({GAME_MARKETS[b["market"]] for b in bets if b.get("market") in GAME_MARKETS})
    markets = prop_keys + [k for k in game_keys if k not in prop_keys]
    if not markets:
        return {}
    js, _ = O.fetch_event_props(event["id"], api_key, markets, sport=O.feed_for(event, sp.odds_sport_key))
    offers = O.parse_event_offers(js, supported_markets=prop_keys) if prop_keys else []
    out = {}
    for b in bets:
        if b.get("market") in GAME_MARKETS:
            p = game_line_price(b, js)
        else:
            p = C.bet_close_price(b, offers, market_map=sp.market_map, single_line_markets=sp.single_line_markets)
        if p is not None:
            out[int(b["id"])] = p
    return out


def plan(open_bets: List[Dict], events_by_sport: Dict[str, List[Dict]]) -> List[Tuple[datetime, str, Dict, List[Dict]]]:
    """[(kickoff, sport, event, bets)] for every game with a watchable open bet, soonest first."""
    games: Dict[str, Tuple[datetime, str, Dict, List[Dict]]] = {}
    for b in open_bets:
        if not watchable(b):
            continue
        sp = b.get("sport") or ""
        e = match_event(b, events_by_sport.get(sp) or [])
        when = _when(e) if e else None
        if not e or not when:
            continue
        games.setdefault(e["id"], (when, sp, e, []))[3].append(b)
    return sorted(games.values(), key=lambda g: g[0])


def _events(api_key: str, sports_needed) -> Dict[str, List[Dict]]:
    import odds_api as O
    import sports
    out = {}
    for sk in sports_needed:
        try:
            sp = sports.get(sk)
            if not getattr(sp, "odds_sport_key", None):
                continue
            out[sk] = O.fetch_events_all(api_key, sport=sp.odds_sport_key)
        except Exception as exc:                                # noqa: BLE001 -- tennis / intl aren't in the registry
            print(f"  [{sk}] no odds feed ({type(exc).__name__})")
    return out


def run(api_key: str, minutes: int = WATCH_MINUTES, once: bool = False, now_fn=lambda: datetime.now(timezone.utc),
        sleep_fn=time.sleep) -> int:
    import betlog as B
    end = now_fn() + timedelta(minutes=minutes)
    done: set = set()                                           # (event id, lead) already captured
    written = 0
    events_at, events_by_sport = None, {}
    while now_fn() < end:
        open_bets = [b for b in B.list_bets(settled=False) if watchable(b)]
        if not open_bets:
            print("No open bets to watch.")
            break
        if events_at is None or (now_fn() - events_at).total_seconds() > EVENTS_REFRESH_S:
            events_by_sport = _events(api_key, sorted({b.get("sport") or "" for b in open_bets}))
            events_at = now_fn()
        games = [g for g in plan(open_bets, events_by_sport) if g[0] > now_fn()]
        due, nxt = [], None
        for when, sp, e, bets in games:
            for lead in CAPTURE_LEADS:
                at = when - timedelta(minutes=lead)
                if (e["id"], lead) in done:
                    continue
                if at <= now_fn() or (once and when <= now_fn() + timedelta(minutes=60)):
                    due.append((lead, when, sp, e, bets))
                    done.add((e["id"], lead))
                elif nxt is None or at < nxt:
                    nxt = at
        for lead, when, sp, e, bets in due:
            try:
                got = capture_event(e, bets, api_key, sp)
            except Exception as exc:                            # noqa: BLE001
                print(f"  [{sp}] {e.get('away_team')} @ {e.get('home_team')}: fetch failed ({type(exc).__name__})")
                continue
            for bid, price in got.items():
                try:
                    B.update_bet(bid, close_odds=price)
                    written += 1
                except Exception as exc:                        # noqa: BLE001
                    print(f"  failed to write bet {bid}: {exc}")
            print(f"[{sp}] {e.get('away_team')} @ {e.get('home_team')} (starts {when:%H:%M} UTC, T-{lead}m): "
                  f"{len(got)}/{len(bets)} bets priced")
        if once:
            break
        if nxt is None:
            print("No more kickoffs with open bets in view.")
            break
        if nxt >= end:
            print(f"Next capture ({nxt:%H:%M} UTC) is after this run's window; a later run takes it.")
            break
        wait = max(30.0, min((nxt - now_fn()).total_seconds(), 900.0))   # re-check at least every 15 min (new bets)
        sleep_fn(wait)
    print(f"Wrote {written} closing price(s).")
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--minutes", type=int, default=WATCH_MINUTES)
    a = ap.parse_args()
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key or not os.environ.get("DATABASE_URL"):
        print("ODDS_API_KEY and DATABASE_URL are both required.")
        return 1
    run(api_key, minutes=a.minutes, once=a.once)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
