"""
long_shots_scan.py — the day's long shots, scanned ahead of time (Nov 14).

Owner: on Today's best, show the top 3-4 most probable long shots for each sport that has a Long Shots tab (NBA, NFL);
and the public build should see the long shots without spending Odds API credits on every click.

Once every few hours (warm-slates, and the afternoon picks run) this runs the Long Shots finder over every game today
that hasn't started -- the same model reads, alternate lines and honest (tail-corrected) chances as the page -- and
saves:
  * each game's alternate prices in the odds archive (the page's look-back and the public page read them, free);
  * `longshots:<SPORT>:<date>` = {"at", "rows": every rung priced +400 or longer that the honest chance says is worth
    it, "top": the TOP_N most probable of those}.

"Most probable long shot" here = priced +MIN_PRICE or longer, worth more than its price at the honest chance
(EV > 0), no "check news" / thin-sample flag, one rung per player, highest honest chance first. Testing so far: only
NBA Assists (+27%) and NFL Rush Yards (+32-36%) value rungs have made money -- the rest lost 19-32% -- so those are
marked "tested".
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

SPORTS = ("NBA", "NFL")
MIN_PRICE = 400
TOP_N = 4
EVERY_H = 3.0
KEY = "longshots:{sport}:{date}"
ALT_ARCHIVE = ["long_shots_alt"]
TESTED = {"NBA": "Assists", "NFL": "Rush Yards"}


def pick_top(rows: Sequence[Dict], n: int = TOP_N, min_price: int = MIN_PRICE) -> List[Dict]:
    """The n most probable value long shots, one per player."""
    ok = [r for r in rows if (r.get("Price") or 0) >= min_price and (r.get("EV per $1") or 0) > 0
          and not r.get("Flags")]
    ok.sort(key=lambda r: (-(r.get("Honest chance") or 0), -(r.get("EV per $1") or 0)))
    out, seen = [], set()
    for r in ok:
        if r.get("Player") in seen:
            continue
        seen.add(r.get("Player"))
        out.append(r)
        if len(out) >= n:
            break
    return out


def _slim(r: Dict, sport: str, game: str, time_: str) -> Dict:
    keep = ("Player", "Bet", "Market", "Price", "Book says", "Honest chance", "Model raw", "EV per $1", "Projection",
            "Main line", "Flags", "player", "market", "side", "line", "price", "book", "pid")
    out = {k: r.get(k) for k in keep if k in r}
    out.update(sport=sport, game=game, time=time_, tested=r.get("Market") == TESTED.get(sport),
               pick=r.get("pick") or f"{r.get('Player')} {r.get('Bet')}", chance=r.get("Honest chance"))
    return out


def scan(sport: str, day: str, api_key: str, book: str = "draftkings", now: Optional[datetime] = None) -> Dict:
    import best_bets_data as BBD
    import book_menu as BM
    import long_shots as LS
    import model_store as MS
    import odds_api as O
    import position_lines as PL
    import props_engine as PE
    import sports
    now = now or datetime.now(timezone.utc)
    sp = sports.get(sport)
    _, meta = sp.engine.build_slate(day)
    def _today(m):                                              # NFL's slate is the week: keep today's games
        d = sports.game_dt(m.get("game_date"))
        return d.strftime("%Y-%m-%d") == day if d else str(m.get("game_date") or day)[:10] == day
    meta = [m for m in meta or [] if _today(m)]
    if not meta:
        return {"at": now.isoformat(), "rows": [], "top": [], "games": 0}
    offers = BBD.fetch_generic_offers(sport, day, api_key)
    reads = BBD.slate_reads_for(sport, day, meta, offers, book) or {}
    evs = O.fetch_events_all(api_key, sport=sp.odds_sport_key)
    alts = list(LS.SPORTS[sport]["alt"])
    found, games = [], 0
    for g in meta:
        ev = PL.match_event(evs, g["home_name"], g["away_name"])
        if not ev:
            continue
        try:
            ko = datetime.fromisoformat(str(ev.get("commence_time")).replace("Z", "+00:00"))
        except ValueError:
            ko = None
        if ko and ko <= now:                                    # started: the alternate prices are live prices
            continue
        res = BM.fetch_menu(api_key, sp.odds_sport_key, [ev["id"]], alts, book,
                            feed_by_event={ev["id"]: ev.get("_feed") or sp.odds_sport_key})
        quotes = res.get("quotes") or []
        if not quotes:
            continue
        games += 1
        try:
            MS.save_odds(sport, day, g.get("home_name") or "", g.get("away_name") or "", ALT_ARCHIVE,
                         {"offers": quotes}, ev.get("commence_time"))
        except Exception:                                       # noqa: BLE001
            pass
        import pytz
        t = "" if not ko else ko.astimezone(pytz.timezone("US/Eastern")).strftime("%-I:%M %p")
        rows = LS.finder({k: v for k, v in reads.items() if v.get("game") == g["label"]}, quotes, PE.norm_name,
                         PE.prob_over, sport=sport)
        found += [_slim(r, sport, g["label"], t) for r in rows
                  if (r.get("Price") or 0) >= MIN_PRICE and (r.get("EV per $1") or 0) > 0]
    found.sort(key=lambda r: -(r.get("Honest chance") or 0))
    return {"at": now.isoformat(), "rows": found[:200], "top": pick_top(found), "games": games}


def load(sport: str, day: str, get=None) -> Optional[Dict]:
    try:
        import model_store as MS
        return (get or MS.get_setting)(KEY.format(sport=sport, date=day))
    except Exception:                                           # noqa: BLE001
        return None


def stale(saved: Optional[Dict], now: Optional[datetime] = None, hours: float = EVERY_H) -> bool:
    if not saved or not saved.get("at"):
        return True
    try:
        t = datetime.fromisoformat(str(saved["at"]))
    except ValueError:
        return True
    return ((now or datetime.now(timezone.utc)) - t).total_seconds() > hours * 3600


def run(day: Optional[str] = None, force: bool = False) -> Dict[str, Dict]:
    import model_store as MS
    import pytz
    import sports
    api = os.environ.get("ODDS_API_KEY", "")
    day = day or datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
    out = {}
    for sp in SPORTS:
        if not sports.in_season(sp) or not api:
            continue
        if not force and not stale(load(sp, day)):
            out[sp] = {"skipped": "scanned under 3 hours ago"}
            continue
        try:
            res = scan(sp, day, api)
            MS.save_setting(KEY.format(sport=sp, date=day), res)
            out[sp] = {"games": res["games"], "value_rungs": len(res["rows"]),
                       "top": [f"{r['Player']} {r['Bet']} {int(r['Price']):+d} ({r['Honest chance']:.0%})" for r in res["top"]]}
        except Exception as exc:                                # noqa: BLE001 -- one sport never stops the other
            out[sp] = {"error": f"{type(exc).__name__}: {exc}"}
    return out


if __name__ == "__main__":
    for k, v in run(force="--force" in sys.argv).items():
        print(k, v)
