import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
want = [("lopez", "Assists"), ("ausar thompson", "RA"), ("mcdaniels", "RA"), ("sion james", "RA"), ("s. james", "RA")]
latest = {}
for s in MS.load_snapshots("NBA", ["2026-11-17"]):
    nm = str(s.get("player")).lower()
    for w, mk in want:
        if w in nm and s.get("market") == mk:
            k = (s["player"], mk)
            if k not in latest or str(s.get("ts")) > str(latest[k].get("ts")): latest[k] = s
for (p, m), s in latest.items():
    print(f"R {p:20} {m:8} line {s.get('line')} proj {s.get('projection'):.2f} side {s.get('side')} ch {s.get('chance')} "
          f"pmod {s.get('p_model')} pmkt {s.get('p_market')} o {s.get('over_price')} u {s.get('under_price')} use {s.get('use_tag')} ts {s.get('ts')} | {str(s.get('flags'))[:140]}")
names = sorted({s['player'] for s in MS.load_snapshots('NBA', ['2026-11-17']) if 'james' in str(s.get('player')).lower() or 'lopez' in str(s.get('player')).lower()})
print("NAMES", names)
