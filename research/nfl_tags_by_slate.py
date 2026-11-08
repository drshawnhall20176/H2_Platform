"""Nov 8: NFL Use tags by slate (does 'Single only' lose on every slate?) + the full CIN-ATL board, audited."""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import daily_review as D     # noqa: E402
import model_store as MS     # noqa: E402
import props_engine as PE    # noqa: E402

graded = D.grade_dates("NFL", [d for d in MS.snapshot_dates("NFL") if d < "2026-11-08"])
for d, rs in sorted(graded.items()):
    cell = defaultdict(lambda: [0, 0, 0.0])
    for r in rs:
        if r.get("result") not in ("hit", "miss"):
            continue
        tag = r.get("use_tag") or "none"
        side = r.get("side")
        price = r.get("price")
        dec = PE.decimal(price) if price is not None else 1.909
        for key in (tag, f"{tag} {side}", f"playable {side}" if tag.startswith(("🔒", "🎟", "🎯")) else f"pass {side}"):
            c = cell[key]
            c[0] += r["result"] == "hit"
            c[1] += 1
            c[2] += (dec - 1) if r["result"] == "hit" else -1
    for k, (h, n, pl) in sorted(cell.items()):
        if n >= 5:
            print("NT SLATE", d, f"{k:28s}", f"{h}/{n} = {h / n:.0%}", f"profit/$1 {pl / n:+.2f}")
# the Madrid game, fully audited
import ticket_audit as T     # noqa: E402
legs = [x for x in T.audit("NFL") if "CIN" in x["game"] and "ATL" in x["game"]]
print("NT CINATL legs", len(legs))
for x in sorted(legs, key=lambda x: (x["use"] not in (PE.USE_BOTH, PE.USE_PARLAY), -(x["ev"] if x["ev"] is not None else -9)))[:40]:
    print("NT LEG", f"{x['player']:24s} {x['market']:17s} {x['side']:5s} {x['line']:6g} | live {x['price']} others {x['others'][:3]}"
          f" | {x['chance']:.0%} | edge {('%+.1f%%' % (100 * x['ev'])) if x['ev'] is not None else '—'} | {x['use']}"
          f" | {', '.join(x['angles']) or '—'} | {'; '.join(x['flags']) or 'clean'}")
