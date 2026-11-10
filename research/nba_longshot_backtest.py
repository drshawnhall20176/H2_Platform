"""
Nov 10: does the Long Shots page beat the books' alternate prices over many NBA nights, not just Nov 9?
For every night with saved model reads (model_store snapshots), pull DraftKings alternate lines from the Odds API
history at two moments -- 11:00 ET (when the owner usually bets) and just before tip-off -- save them, then run the
look-back: which rungs the page would have called value, how many hit, and flat-$1 profit at each moment.
Cost ~80 credits per game per moment. Saved lines are reused (free) on re-runs.
"""
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

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

SPORT, BOOK, FLOOR = "basketball_nba", "draftkings", 100000
START, END = os.environ.get("START", "2026-10-21"), os.environ.get("END", "2026-11-09")
key = os.environ["ODDS_API_KEY"]
et = pytz.timezone("US/Eastern")
KEYS = {"am": ["long_shots_alt_am"], "close": ["long_shots_alt"]}
left = None


def hist(eid, mk, when):
    try:
        js, h = O.fetch_historical_event_props(eid, key, [mk], when, sport=SPORT)
        return BM.parse_menu_event((js or {}).get("data") or {}, BOOK), h.get("remaining")
    except O.OddsAPIError as exc:
        return [], f"ERR {str(exc)[:80]}"


def night_quotes(day):
    """{moment: {label: quotes}} for one night, from the archive or the history API."""
    global left
    noon = et.localize(datetime.strptime(day, "%Y-%m-%d").replace(hour=11)).astimezone(pytz.utc)
    _rows, meta = nba_engine.build_slate(day)
    evs = None
    out = {"am": {}, "close": {}}
    for g in meta:
        for moment, mkey in KEYS.items():
            have = MS.load_odds("NBA", day, g["home_name"], g["away_name"], mkey)
            if have and have.get("offers"):
                out[moment][g["label"]] = have["offers"]
                continue
            if evs is None:
                js, _h = O.fetch_historical_events(key, noon.strftime("%Y-%m-%dT%H:%M:%SZ"), sport=SPORT)
                evs = (js.get("data") if isinstance(js, dict) else js) or []
            ev = PL.match_event(evs, g["home_name"], g["away_name"])
            if not ev:
                continue
            ct = datetime.strptime(ev["commence_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
            when = noon if moment == "am" else ct - timedelta(minutes=5)
            if when >= ct:
                continue
            with ThreadPoolExecutor(8) as ex:
                res = list(ex.map(lambda mk: hist(ev["id"], mk, when.strftime("%Y-%m-%dT%H:%M:%SZ")), LS.ALT_TO_MAIN))
            quotes = [q for qs, _ in res for q in qs]
            errs = [r for _, r in res if isinstance(r, str) and r.startswith("ERR")]
            if errs:
                print(f"  {day} {g['label']} {moment}: {errs[0]}")
            left = next((r for _, r in res if r and not str(r).startswith("ERR")), left)
            MS.save_odds("NBA", day, g["home_name"], g["away_name"], mkey, {"offers": quotes}, None)
            out[moment][g["label"]] = quotes
    return out


def pl(r):
    return (r["Price"] / 100 if r["Price"] > 0 else 100 / -r["Price"]) if r["Hit"] == "✅" else -1.0


dates = [d for d in MS.snapshot_dates("NBA") if START <= d <= END]
print(f"nights with saved reads {START}..{END}: {len(dates)}")
agg = {m: defaultdict(list) for m in KEYS}
for day in sorted(dates):
    q = night_quotes(day)
    snaps = MS.load_snapshots("NBA", [day])
    res = PG.fetch_results("NBA", day, sorted({(s["team"], s["opp"]) for s in snaps}))
    graded = PG.grade(snaps, res)
    line = [day]
    for moment in KEYS:
        rows = []
        for lab, quotes in q[moment].items():
            rows += LS.lookback([s for s in graded if s.get("game") == lab], quotes, PE.norm_name)
        priced = [r for r in rows if r["Price"] and r["Hit"] is not None]
        for r in priced:
            r["night"] = day
        agg[moment]["all"] += priced
        v = [r for r in priced if r["EV per $1"] > 0]
        line.append(f"{moment}: {len(priced)} priced, value {len(v)} hit {sum(r['Hit'] == '✅' for r in v)} "
                    f"P/L {sum(pl(r) for r in v):+.0f}")
    print("  " + " | ".join(line) + f" | credits left {left}")
    if left is not None and float(left) < FLOOR:
        print("stopping: credit floor")
        break

for moment in KEYS:
    pr = agg[moment]["all"]
    if not pr:
        continue
    print(f"\n===== {moment.upper()} prices: {len(pr)} priced rungs over {len({r['night'] for r in pr})} nights")
    print(f"all rungs: hit {sum(r['Hit'] == '✅' for r in pr)}, honest expected {sum(r['Honest chance'] for r in pr):.0f}, "
          f"book implied {sum(r['Book says'] for r in pr):.0f}, $1 each P/L {sum(pl(r) for r in pr):+.0f}")
    for cut in (0.0, 0.25, 0.5, 1.0):
        v = [r for r in pr if r["EV per $1"] > cut]
        if v:
            print(f"  EV>{cut:+.2f}: n={len(v)} hit {sum(r['Hit'] == '✅' for r in v)} expected "
                  f"{sum(r['Honest chance'] for r in v):.0f} book {sum(r['Book says'] for r in v):.0f} "
                  f"P/L {sum(pl(r) for r in v):+.0f} ROI {sum(pl(r) for r in v) / len(v):+.1%}")
    print("  by market (EV>0): ")
    for mk in sorted({r["Market"] for r in pr}):
        v = [r for r in pr if r["EV per $1"] > 0 and r["Market"] == mk]
        if v:
            print(f"    {mk:<12} n={len(v):4d} hit {sum(r['Hit'] == '✅' for r in v):3d} exp "
                  f"{sum(r['Honest chance'] for r in v):5.1f} book {sum(r['Book says'] for r in v):5.1f} "
                  f"ROI {sum(pl(r) for r in v) / len(v):+.1%}")
    print("  by price (EV>0):")
    for lo, hi in ((100, 300), (300, 600), (600, 1200), (1200, 3001)):
        v = [r for r in pr if r["EV per $1"] > 0 and lo <= r["Price"] < hi]
        if v:
            print(f"    +{lo}..+{hi}: n={len(v)} hit {sum(r['Hit'] == '✅' for r in v)} exp "
                  f"{sum(r['Honest chance'] for r in v):.1f} book {sum(r['Book says'] for r in v):.1f} "
                  f"ROI {sum(pl(r) for r in v) / len(v):+.1%}")
    print("  where the model agrees with the book's direction but is a bit higher (book implied >= 70% of honest):")
    v = [r for r in pr if r["EV per $1"] > 0 and r["Book says"] >= 0.7 * r["Honest chance"]]
    if v:
        print(f"    n={len(v)} hit {sum(r['Hit'] == '✅' for r in v)} exp {sum(r['Honest chance'] for r in v):.1f} "
              f"book {sum(r['Book says'] for r in v):.1f} ROI {sum(pl(r) for r in v) / len(v):+.1%}")

# morning -> close moves: did the book move toward the model?
am = {(r["night"], r["Player"], r["Bet"]): r for r in agg["am"]["all"]}
cl = {(r["night"], r["Player"], r["Bet"]): r for r in agg["close"]["all"]}
both = [(am[k], cl[k]) for k in am if k in cl]
if both:
    v = [(a, c) for a, c in both if a["EV per $1"] > 0]
    toward = sum(c["Book says"] > a["Book says"] for a, c in v)
    print(f"\nmorning value rungs also priced at close: {len(v)}; book shortened the price (moved toward the model) on "
          f"{toward} ({toward / max(len(v), 1):.0%}); lengthened on {sum(c['Book says'] < a['Book says'] for a, c in v)}")
    print(f"  ROI betting them in the morning {sum(pl(a) for a, _ in v) / max(len(v), 1):+.1%} vs at close "
          f"{sum(pl(c) for _, c in v) / max(len(v), 1):+.1%}")
    big = [(a, c) for a, c in v if c["Book says"] >= a["Book says"] * 1.5]
    print(f"  rungs whose price shortened by 1.5x+ (big news moves): n={len(big)} hit "
          f"{sum(a['Hit'] == '✅' for a, _ in big)} morning ROI {sum(pl(a) for a, _ in big) / max(len(big), 1):+.1%}")
