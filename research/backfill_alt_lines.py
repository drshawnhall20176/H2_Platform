"""
Backfill one night's NBA alternate lines from the Odds API history, save them where the Long Shots look-back reads
them (model_store odds_archive, key "long_shots_alt"), then run the look-back scenario: every rung above the main
line, its honest chance, the DraftKings price, and how a flat $1 on each value rung would have done.

Owner request Nov 10 ("pull the alternate lines for last night's games so we can run our scenario").
Cost: the history endpoint bills 10 credits per market per region -> 80 per game (8 alternate markets). Stops early
if the key's remaining credits fall under FLOOR.
"""
import os
import sys
from datetime import datetime

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import book_menu as BM                                          # noqa: E402
import long_shots as LS                                          # noqa: E402
import model_store as MS                                         # noqa: E402
import nba_engine                                                # noqa: E402
import odds_api as O                                             # noqa: E402
import position_lines as PL                                      # noqa: E402
import postgame as PG                                            # noqa: E402
import props_engine as PE                                        # noqa: E402

DAY = os.environ.get("DAY", "2026-11-09")
BOOK = "draftkings"
FLOOR = 1500
SPORT = "basketball_nba"
key = os.environ["ODDS_API_KEY"]

et = pytz.timezone("US/Eastern")
noon = et.localize(datetime.strptime(DAY, "%Y-%m-%d").replace(hour=12)).astimezone(pytz.utc)
evs, hdr = O.fetch_historical_events(key, noon.strftime("%Y-%m-%dT%H:%M:%SZ"), sport=SPORT)
evs = evs.get("data") if isinstance(evs, dict) else evs
print(f"history events at {noon:%Y-%m-%d %H:%M}Z: {len(evs or [])}; credits left {hdr.get('remaining')}")
_rows, meta = nba_engine.build_slate(DAY)
print(f"slate {DAY}: {len(meta)} games")

saved = {}
for g in meta:
    ev = PL.match_event(evs or [], g["home_name"], g["away_name"])
    if not ev:
        print(f"  {g['label']}: no history event")
        continue
    quotes, left = [], None
    for mk in LS.ALT_TO_MAIN:
        try:
            js, h = O.fetch_historical_event_props(ev["id"], key, [mk], ev.get("commence_time"), sport=SPORT)
        except O.OddsAPIError as exc:
            print(f"  {g['label']} {mk}: {str(exc)[:120]}")
            if "401" in str(exc) or "403" in str(exc) or "429" in str(exc):
                sys.exit(1)
            continue
        left = h.get("remaining") or left
        quotes += BM.parse_menu_event((js or {}).get("data") or {}, BOOK)
    ok = MS.save_odds("NBA", DAY, g["home_name"], g["away_name"], ["long_shots_alt"], {"offers": quotes}, None)
    saved[g["label"]] = quotes
    print(f"  {g['label']}: {len(quotes)} DK alt quotes, saved={ok}, credits left {left}")
    if left is not None and float(left) < FLOOR:
        print("stopping: credits under floor")
        break

# ---- the scenario
snaps = MS.load_snapshots("NBA", [DAY])
res = PG.fetch_results("NBA", DAY, sorted({(s["team"], s["opp"]) for s in snaps}))
graded = PG.grade(snaps, res)
rows = []
for lab, q in saved.items():
    rows += LS.lookback([s for s in graded if s.get("game") == lab], q, PE.norm_name)
priced = [r for r in rows if r["Price"] and r["Hit"] is not None]
print(f"\nrungs graded {len([r for r in rows if r['Hit']])}; with a DK price {len(priced)}")
summ = LS.night_summary(priced)
print(f"priced rungs: {summ['hits']} hit, honest chances expected {summ['expected']:.1f}, "
      f"book's prices implied {sum(r['Book says'] for r in priced):.1f}")


def pl(rs):
    return sum((r["Price"] / 100 if r["Price"] > 0 else 100 / -r["Price"]) if r["Hit"] == "✅" else -1 for r in rs)


for cut, name in ((0.0, "EV > 0"), (0.25, "EV > +0.25"), (0.5, "EV > +0.50")):
    v = [r for r in priced if r["EV per $1"] > cut and r["Honest chance"] >= LS.MIN_REAL]
    print(f"$1 flat on every rung with {name}: {len(v)} bets, {sum(r['Hit'] == '✅' for r in v)} hit, "
          f"P/L ${pl(v):+.2f}")
print(f"$1 on every priced rung (no filter): {len(priced)} bets, P/L ${pl(priced):+.2f}")

print("\nvalue rungs (EV>0), best first:")
for r in sorted([r for r in priced if r["EV per $1"] > 0], key=lambda r: -r["EV per $1"])[:40]:
    print(f"  {r['Hit']} {r['Player']:<24} {r['Bet']:<20} DK {r['Price']:+6.0f}  honest {r['Honest chance']:.0%}  "
          f"fair {r['Fair price']:+6d}  EV {r['EV per $1']:+.2f}  actual {r['Actual']}  proj {r['Projection']:.1f}")
print("\nFears:")
for r in rows:
    if "Fears" in str(r["Player"]):
        print(f"  {r['Hit']} {r['Bet']:<14} DK {r['Price']}  honest {r['Honest chance']:.0%} fair {r['Fair price']:+d} "
              f"EV {r['EV per $1']}  actual {r['Actual']}")
