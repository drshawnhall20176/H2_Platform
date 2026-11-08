"""Nov 8: the owner's real bets vs the platform's pools, the tracking models' records, last night's college bets."""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B           # noqa: E402
import model_store as MS     # noqa: E402

bets = [b for b in B.list_bets() if b.get("is_real_bet")]
legs = [b for b in bets if b.get("market") != "Parlay"]
cell = defaultdict(lambda: [0, 0, 0.0, 0.0])
for b in bets:
    r = b.get("result")
    if r not in ("win", "loss"):
        continue
    kind = "parlay" if b.get("market") == "Parlay" else ("leg" if b.get("ticket") else "single")
    mp = b.get("model_prob")
    band = "no model read" if mp is None else ("model 60%+" if mp >= 0.6 else ("model 55-60%" if mp >= 0.55 else ("model 50-55%" if mp >= 0.5 else "model under 50% (against the model)")))
    for key in ((kind, "all"), (kind, b.get("sport")), (kind, band)):
        c = cell[key]
        c[0] += r == "win"
        c[1] += 1
        st = float(b.get("stake") or 0)
        o = b.get("entry_odds")
        dec = (1 + (float(o) / 100 if float(o) > 0 else 100 / -float(o))) if o not in (None, "") else 1.909
        c[2] += st
        c[3] += st * (dec - 1) if r == "win" else -st
for k, (w, n, st, pl) in sorted(cell.items(), key=lambda kv: (kv[0][0], -kv[1][1])):
    print("UV", f"{k[0]:6s} {str(k[1]):38s} {w}-{n - w} ({w / n:.0%})  staked ${st:.0f}  P/L ${pl:+.2f}")
open_ = [b for b in bets if not b.get("result")]
print("UV open bets", len(open_), sorted({(b.get("sport"), b.get("slate_date")) for b in open_}))
# tracking models: college spreads v2 / NCAAF game picks review
rep = MS.load_daily_review("NCAAF", "2026-11-08") or {}
print("UV NCAAF game_picks", json.dumps(rep.get("game_picks"), default=str)[:1500])
for lg in ("NCAAF", "NCAAMB", "NBA", "NHL"):
    recs = [r for r in MS.load_game_picks(lg) if r.get("result") is not None]
    by = defaultdict(lambda: [0, 0])
    for r in recs:
        for k in ("result", "total_result", "ats_result", "ml_result"):
            if r.get(k) in ("win", "loss", "hit", "miss", "W", "L"):
                c = by[k]
                c[0] += r[k] in ("win", "hit", "W")
                c[1] += 1
    print("UV GAMEPICKS", lg, "graded records", len(recs), {k: f"{w}-{n - w}" for k, (w, n) in by.items()},
          "| keys", sorted(recs[0].keys())[:40] if recs else None)
