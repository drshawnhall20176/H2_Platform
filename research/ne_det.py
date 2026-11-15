import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
snaps = [s for s in MS.load_snapshots("NFL", ["2026-11-15"]) if "Detroit" in str(s.get("game")) or "DET" in str(s.get("game"))]
latest = {}
for s in snaps:
    k = (s.get("player"), s.get("market"), s.get("line"))
    if k not in latest or str(s.get("ts")) > str(latest[k].get("ts")):
        latest[k] = s
rows = sorted(latest.values(), key=lambda s: -(s.get("chance") or 0))
print("reads", len(rows), "game", rows[0].get("game") if rows else None)
for s in rows[:40]:
    print(f"R {s.get('player')} | {s.get('market')} {s.get('side')} {s.get('line')} | chance {s.get('chance')} | proj {s.get('projection')} | use {s.get('use_tag')} | price {s.get('price')} | p_mkt {s.get('p_market')} | gap {s.get('gap')} | flags {s.get('flags')} | ts {str(s.get('ts'))[:16]}")
