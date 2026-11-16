import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
want = ("tatum", "trae young", "edgecombe", "sengun")
latest = {}
for s in MS.load_snapshots("NBA", ["2026-11-16"]):
    if not any(w in str(s.get("player")).lower() for w in want): continue
    if s.get("market") not in ("RA", "Rebounds", "Assists"): continue
    k = (s["player"], s["market"])
    if k not in latest or str(s.get("ts")) > str(latest[k].get("ts")): latest[k] = s
for (p, m), s in sorted(latest.items()):
    print(f"R {p:20} {m:9} line {s.get('line')} proj {s.get('projection')} side {s.get('side')} ch {s.get('chance')} "
          f"pm {s.get('p_model')} mkt {s.get('p_market')} o {s.get('over_price')} u {s.get('under_price')} | {s.get('use_tag')} | ts {s.get('ts')} | {str(s.get('flags'))[:120]}")
