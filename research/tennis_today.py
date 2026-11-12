"""Nov 12: the owner's tennis bets today and the Tennis Lab's record -- today, last 7 / 30 days, by favourite size."""
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
import pytz
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B           # noqa: E402
import intl_picks as IP      # noqa: E402
import model_store as MS     # noqa: E402

today = datetime.now(pytz.timezone("US/Eastern")).date()
for b in B.list_bets():
    if str(b.get("sport")).upper() in ("TENNIS",) and str(b.get("slate_date")) >= (today - timedelta(days=1)).isoformat():
        print("TT bet", b["id"], b.get("slate_date"), b.get("player") or b.get("notes", "")[:60], b.get("market"),
              b.get("side"), "odds", b.get("entry_odds"), "stake", b.get("stake"), "result", b.get("result"),
              "pl", B.bet_pnl(b))
picks = MS.load_game_picks("TENNIS")
graded = [p for p in picks if p.get("result") in ("home", "away")]
print("TT graded picks", len(graded), "of", len(picks))


def fav(p):
    q = float(p["model_p"])
    return ("home", q) if q >= 0.5 else ("away", 1 - q)


for label, since in (("today", today), ("7 days", today - timedelta(days=7)), ("30 days", today - timedelta(days=30)),
                     ("all", today - timedelta(days=3650))):
    g = [p for p in graded if p["kickoff"][:10] >= since.isoformat()]
    if not g:
        continue
    w = sum(fav(p)[0] == p["result"] for p in g)
    exp = sum(fav(p)[1] for p in g)
    mkt = [p for p in g if p.get("line") is not None]
    mw = sum((p["line"] >= 0.5) == (p["result"] == "home") for p in mkt)
    print(f"TT {label}: model favourite won {w}/{len(g)} ({w / len(g):.0%}), expected {exp / len(g):.0%}; "
          f"books' favourite won {mw}/{len(mkt)}")
    bands = defaultdict(lambda: [0, 0, 0.0])
    for p in g:
        side, q = fav(p)
        b = "50-60" if q < .6 else "60-70" if q < .7 else "70-80" if q < .8 else "80+"
        bands[b][0] += 1
        bands[b][1] += side == p["result"]
        bands[b][2] += q
    if label in ("30 days", "all"):
        for b in ("50-60", "60-70", "70-80", "80+"):
            n, w2, s = bands[b]
            if n:
                print(f"TT   {label} model {b}%: n={n} won {w2 / n:.0%} (said {s / n:.0%})")
    # the bets the model actually recommends (edge vs books)
    pk = [p for p in g if p.get("pick")]
    if pk:
        pw = sum(p["pick"] == p["result"] for p in pk)
        print(f"TT   {label} model's value picks (vs books): {pw}/{len(pk)}")
today_g = [p for p in picks if p["kickoff"][:10] == today.isoformat()]
for p in sorted(today_g, key=lambda p: p["kickoff"]):
    side, q = fav(p)
    print("TT today", p["kickoff"][11:16], p["home"], "vs", p["away"], "fav", p[side], f"{q:.0%}", "books",
          None if p.get("line") is None else f"{p['line']:.0%} home", "pick", p.get("pick"), "result", p.get("result"))
