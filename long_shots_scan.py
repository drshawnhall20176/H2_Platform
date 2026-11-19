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
(EV > 0), no "check news" / thin-sample flag, the model's projection within 25% of the book's main line (agrees()),
one rung per player, highest honest chance first. Testing so far: only
NBA Assists (+27%) and NFL Rush Yards (+32-36%) value rungs have made money -- the rest lost 19-32% -- so those are
marked "tested".
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

SPORTS = ("NBA", "NFL", "NHL", "NCAAF")
MIN_PRICE = 400
TOP_N = 4
EVERY_H = 3.0
KEY = "longshots:{sport}:{date}"
ALT_ARCHIVE = ["long_shots_alt"]
TESTED = {"NBA": ("Assists",), "NFL": ("Rush Yards",),          # NHL Goals: a lead only (+28% at 11am, even at close)
          "NCAAF": ("Rush Yards", "Receiving Yards")}            # Nov 14: +37% / +31% at 11am, +26% / +24% at kickoff


SKIP = {"NCAAF": ("Pass Yards",)}                   # Nov 14: college Pass Yards value rungs lost 27-33% in testing
AGREE = 0.25              # projection within 25% (or 1 unit) of the book's own main line


def agrees(r: Dict, tol: float = AGREE) -> bool:
    """Nov 14: the model and the book roughly agree on the player's normal night. The first scan's "most probable"
    rungs were the model's biggest disagreements (7.5 assists projected vs the book's 4.5) -- and in testing, where
    the model disagrees with the book, the book is usually right (it knows about a role or minutes change). A long
    shot here should be a tail outcome on a normal night, not a bet that the book has the player wrong."""
    proj, main = r.get("Projection"), r.get("Main line")
    if proj is None or main is None:
        return False
    return abs(float(proj) - float(main)) <= max(tol * float(main), 1.0)


def pick_top(rows: Sequence[Dict], n: int = TOP_N, min_price: int = MIN_PRICE) -> List[Dict]:
    """The n most probable value long shots, one per player, where the model and the book agree on the main line."""
    ok = [r for r in rows if (r.get("Price") or 0) >= min_price and (r.get("EV per $1") or 0) > 0
          and not r.get("Flags") and agrees(r)]
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
    out.update(sport=sport, game=game, time=time_, tested=r.get("Market") in TESTED.get(sport, ()),
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
    offers = BBD.recent_offers(sport, day, api_key)      # Nov 16: the board warm-slates just built, when fresh
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
                  if (r.get("Price") or 0) >= MIN_PRICE and (r.get("EV per $1") or 0) > 0
                  and r.get("Market") not in SKIP.get(sport, ())]
    found.sort(key=lambda r: -(r.get("Honest chance") or 0))
    res = {"at": now.isoformat(), "rows": found[:200], "top": pick_top(found), "games": games}
    return recheck(res, sport) or res                                       # Nov 18: tonight's injury report too


TESTED_NOTE = "✅ Tested market: positive in testing so far (promising, not proven)"
UNTESTED_NOTE = "Other market: these lost overall in testing"


def lead_cards(saved: Optional[Dict], n: int = TOP_N) -> List[Dict]:
    """Nov 16: the Long Shots page's lead -- the day's scan as cards, tested markets first, then the most probable.
    Each: {pick, price, chance, book, ev, game, time, tested, note}. Empty when there is no scan yet."""
    top = list((saved or {}).get("top") or [])
    top.sort(key=lambda r: (not r.get("tested"), -(r.get("Honest chance") or 0)))
    return [{"pick": r.get("pick") or f"{r.get('Player')} {r.get('Bet')}", "price": r.get("Price"),
             "chance": r.get("Honest chance"), "book": r.get("Book says"), "ev": r.get("EV per $1"),
             "game": r.get("game") or "", "time": r.get("time") or "", "tested": bool(r.get("tested")),
             "note": TESTED_NOTE if r.get("tested") else UNTESTED_NOTE} for r in top[:n]]


def all_rows(saved: Optional[Dict]) -> List[Dict]:
    """Every value long shot in the day's scan as table rows, tested markets first, then the most probable."""
    rows = sorted((saved or {}).get("rows") or [], key=lambda r: (not r.get("tested"), -(r.get("Honest chance") or 0)))
    return [{"Time": r.get("time") or "", "Game": r.get("game") or "", "Pick": r.get("pick"), "Price": r.get("Price"),
             "Honest chance": r.get("Honest chance"), "Book says": r.get("Book says"), "EV per $1": r.get("EV per $1"),
             "Market": ("✅ " if r.get("tested") else "") + str(r.get("Market") or "")} for r in rows]


def load(sport: str, day: str, get=None, live: Optional[bool] = None) -> Optional[Dict]:
    """The day's saved scan. live (default: on for the real store): re-checked against tonight's injury report."""
    try:
        import model_store as MS
        saved = (get or MS.get_setting)(KEY.format(sport=sport, date=day))
    except Exception:                                           # noqa: BLE001
        return None
    if live if live is not None else get is None:
        saved = recheck(saved, sport)
    return saved


def recheck(saved: Optional[Dict], sport: str, status=None) -> Optional[Dict]:
    """Nov 18 (RJ Barrett, ruled out at 5:55 PM, topped the 4:13 PM scan): drop rungs for players now ruled out,
    keep questionable ones in the full list with a flag but out of the top picks, and re-pick the top."""
    if not saved or not saved.get("rows"):
        return saved
    try:
        import injury_check as IC
        status = status or (lambda name: IC.status(sport, name))
        rows = []
        for r in saved["rows"]:
            s = status(r.get("Player"))
            if s == "out":
                continue
            if s == "questionable":
                r = dict(r, Flags=list(r.get("Flags") or []) + ["questionable tonight — check news"],
                         pick=f"{r.get('pick')} (questionable)")
            rows.append(r)
        if len(rows) == len(saved["rows"]) and not any(status(r.get("Player")) for r in rows):
            return saved
        return {**saved, "rows": rows, "top": pick_top(rows), "rechecked": True}
    except Exception:                                           # noqa: BLE001
        return saved


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
        if not force and not stale(load(sp, day, live=False)):
            out[sp] = {"skipped": "scanned under 3 hours ago"}
            continue
        try:
            res = scan(sp, day, api)
            MS.save_setting(KEY.format(sport=sp, date=day), res)
            out[sp] = {"games": res["games"], "value_rungs": len(res["rows"]),
                       "top": [f"{r['Player']} {r['Bet']} {int(r['Price']):+d} ({r['Honest chance']:.0%})" for r in res["top"]]}
        except Exception as exc:                                # noqa: BLE001 -- one sport never stops the other
            out[sp] = {"error": f"{type(exc).__name__}: {exc}"}
    try:                                                        # Nov 14: soccer anytime goalscorers (lab_long_shots)
        import lab_long_shots as LLS
        out["SOCCER"] = LLS.run_scorers(day, force=force)
    except Exception as exc:                                    # noqa: BLE001
        out["SOCCER"] = {"error": f"{type(exc).__name__}: {exc}"}
    return out


if __name__ == "__main__":
    for k, v in run(force="--force" in sys.argv).items():
        print(k, v)
