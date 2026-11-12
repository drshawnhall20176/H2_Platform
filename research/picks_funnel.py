"""Nov 12: why the afternoon note had only 2 picks -- per sport, what was saved, judged, and each verdict."""
import os, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B
import coach as CO
import pick_records as PR
import todays_best as TB
import props_engine as PE

day = "2026-11-12"
bets = B.list_bets()
for sp in ("NBA", "NFL", "NHL", "NCAAF", "NCAAMB"):
    saved = TB.load_props(sp, day)
    rows = [r for r in (saved or {}).get("rows") or []]
    print(f"\n{sp}: saved board at {(saved or {}).get('at')} -- {len(rows)} playable-tagged props")
    c = [r for r in rows if r.get("price") is not None and r.get("chance") is not None]
    if not c:
        continue
    j = CO.finder(c, bets, PR.tag_records(sp))
    print("  verdicts:", dict(Counter(x["verdict"] for x in j)))
    why = Counter()
    for x in j:
        if x["verdict"] != "🟢 Good bet":
            why[str(x.get("why", ""))[:90]] += 1
    for w, n in why.most_common(6):
        print(f"   {n:3d} x {w}")
    print("  tags:", dict(Counter(str(r.get("use")) for r in rows)))
g = TB.game_rows(day)
print("\ngame-line / intl / tennis playable reads:", dict(Counter(r["sport"] for r in g)))
w = TB.winner_rows(day)
print("every game's lean (winner_rows):", dict(Counter(r.get("sport") for r in w)))
