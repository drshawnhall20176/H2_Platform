"""
Nov 10: can a midday "price is dropping" alert be acted on in time? (Owner: yes, build it -- test first.)
For the same 10 NBA nights as nba_longshot_backtest.py, pull DraftKings alternate lines at 15:00 and 17:30 ET too
(saved; 11:00 and tip-off are already saved). A rung "moves" when its price has shortened by FACTOR since 11:00
(the book's chance went up FACTOR times). Bet it at the price we'd SEE at that check (not the 11am price) and grade it.
Also: does the move keep going to tip-off (closing-line value)?
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import book_menu as BM                                          # noqa: E402
import long_shots as LS                                          # noqa: E402
import model_store as MS                                         # noqa: E402
import odds_api as O                                             # noqa: E402
import position_lines as PL                                      # noqa: E402
import postgame as PG                                            # noqa: E402
import props_engine as PE                                        # noqa: E402
import sports                                                    # noqa: E402

SPORT, BOOK = "basketball_nba", "draftkings"
key = os.environ["ODDS_API_KEY"]
et = pytz.timezone("US/Eastern")
MOMENTS = {"am": (11, 0), "t15": (15, 0), "t1730": (17, 30), "close": None}
ARCH = {"am": ["long_shots_alt_am"], "close": ["long_shots_alt"], "t15": ["long_shots_alt_t15"],
        "t1730": ["long_shots_alt_t1730"]}


def hist(eid, mk, when):
    try:
        js, _h = O.fetch_historical_event_props(eid, key, [mk], when, sport=SPORT)
        return BM.parse_menu_event((js or {}).get("data") or {}, BOOK)
    except O.OddsAPIError:
        return []


def quotes_for(day, meta):
    out = {m: {} for m in MOMENTS}
    evs = None
    for g in meta:
        for m, hm in MOMENTS.items():
            have = MS.load_odds("NBA", day, g["home_name"], g["away_name"], ARCH[m])
            if have and have.get("offers"):
                out[m][g["label"]] = have["offers"]
                continue
            if hm is None:
                continue
            at = et.localize(datetime.strptime(day, "%Y-%m-%d").replace(hour=hm[0], minute=hm[1])).astimezone(pytz.utc)
            if evs is None:
                noon = et.localize(datetime.strptime(day, "%Y-%m-%d").replace(hour=11)).astimezone(pytz.utc)
                js, _h = O.fetch_historical_events(key, noon.strftime("%Y-%m-%dT%H:%M:%SZ"), sport=SPORT)
                evs = (js.get("data") if isinstance(js, dict) else js) or []
            ev = PL.match_event(evs, g["home_name"], g["away_name"])
            if not ev:
                continue
            ct = datetime.strptime(ev["commence_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
            if at >= ct:
                continue
            with ThreadPoolExecutor(8) as ex:
                qs = [q for r in ex.map(lambda mk: hist(ev["id"], mk, at.strftime("%Y-%m-%dT%H:%M:%SZ")),
                                        LS.ALT_TO_MAIN) for q in r]
            MS.save_odds("NBA", day, g["home_name"], g["away_name"], ARCH[m], {"offers": qs}, None)
            out[m][g["label"]] = qs
    return out


def price_map(quotes):
    d = {}
    for q in quotes:
        main = LS.ALT_TO_MAIN.get(q.get("market"))
        if main and str(q.get("name")).lower() == "over" and q.get("point") is not None:
            d[(PE.norm_name(q.get("description") or ""), main, float(q["point"]) + 0.5)] = float(q["price"])
    return d


def dec(p):
    return 1 + (p / 100 if p > 0 else 100 / -p)


rows = []                       # one per (night, player, rung) with prices at each moment + result + honest chance
dates = [d for d in MS.snapshot_dates("NBA") if "2026-10-21" <= d <= "2026-11-09"]
for day in sorted(dates):
    _r, meta = sports.get("NBA").engine.build_slate(day)
    q = quotes_for(day, meta)
    snaps = MS.load_snapshots("NBA", [day])
    graded = PG.grade(snaps, PG.fetch_results("NBA", day, sorted({(s["team"], s["opp"]) for s in snaps})))
    for lab in q["am"]:
        maps = {m: price_map(q[m].get(lab) or []) for m in MOMENTS}
        for r in LS.lookback([s for s in graded if s.get("game") == lab], [], PE.norm_name):
            if r["Hit"] is None:
                continue
            k = (PE.norm_name(r["Player"]), LS._MAIN_KEY.get(r["Market"]), float(r["_n"]))
            pr = {m: maps[m].get(k) for m in MOMENTS}
            if pr["am"] is None:
                continue
            rows.append(dict(r, night=day, **{f"p_{m}": v for m, v in pr.items()}))
    print(f"  {day}: rows so far {len(rows)}")

print(f"\nrungs with an 11am price: {len(rows)}")


def report(name, picks, moment):
    if not picks:
        print(f"  {name}: none")
        return
    pl = sum((dec(r[f"p_{moment}"]) - 1) if r["Hit"] == "✅" else -1 for r in picks)
    hits = sum(r["Hit"] == "✅" for r in picks)
    implied = sum(LS.implied(r[f"p_{moment}"]) for r in picks)
    clv = [r for r in picks if r.get("p_close")]
    beat = sum(LS.implied(r["p_close"]) > LS.implied(r[f"p_{moment}"]) for r in clv)
    print(f"  {name}: n={len(picks)} hit {hits} (book implied {implied:.1f}, honest {sum(r['Honest chance'] for r in picks):.1f})"
          f" ROI {pl / len(picks):+.1%}; price kept shortening to tip-off on {beat}/{len(clv)}")


for check in ("t15", "t1730"):
    print(f"\n== alert checked at {check} (bet at the {check} price)")
    for factor in (1.25, 1.5, 2.0):
        mv = [r for r in rows if r.get(f"p_{check}") and LS.implied(r[f"p_{check}"]) >= factor * LS.implied(r["p_am"])]
        report(f"price shortened {factor}x+ since 11am", mv, check)
        report(f"  ...and model honest >= book at {check}", [r for r in mv if r["Honest chance"] >=
                                                              LS.implied(r[f"p_{check}"]) * 0.9], check)
        report("  ...Assists only", [r for r in mv if r["Market"] == "Assists"], check)
    dn = [r for r in rows if r.get(f"p_{check}") and LS.implied(r[f"p_{check}"]) * 1.5 <= LS.implied(r["p_am"])]
    report("price LENGTHENED 1.5x+ (fade signal, betting it anyway)", dn, check)
print("\n== reference: every rung at 11am")
report("all rungs bet at 11am", rows, "am")
