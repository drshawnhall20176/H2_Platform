"""Nov 17 evening: a fresh NBA long-shot scan (+400 and longer, every market), ranked for the owner's team challenge."""
import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import long_shots_scan as S
res = S.scan("NBA", "2026-11-17", os.environ["ODDS_API_KEY"])
rows = res["rows"]
print("games", res["games"], "value rungs +400+", len(rows))
def show(tag, rs):
    for r in rs:
        print(f"{tag} {r['time']:>8} {r['Player']:24} {r['Bet']:22} {r['Market']:12} +{int(r['Price'])} "
              f"honest {r['Honest chance']:.1%} book {r.get('Book says')} raw {r.get('Model raw')} EV {r['EV per $1']:+.2f} "
              f"proj {r.get('Projection')} main {r.get('Main line')} agrees {S.agrees(r)} flags {r.get('Flags')} | {r['game']}")
show("ROW", rows[:40])
show("TOP", S.pick_top(rows, n=12))
