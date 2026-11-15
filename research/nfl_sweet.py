import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, props_engine as PE
snaps = MS.load_snapshots("NFL", ["2026-11-15"])
latest = {}
for s in snaps:
    k = (s.get("player"), s.get("market"), s.get("line"), s.get("game"), s.get("side"))
    if k not in latest or str(s.get("ts")) > str(latest[k].get("ts")): latest[k] = s
newest = max(str(s.get("ts")) for s in latest.values())
rows = [s for s in latest.values() if str(s.get("ts")) >= newest[:13]]
MK = ("Rush Yards", "Solo Tackles", "Receptions", "Kicking Points", "FG Made")
out = []
for s in rows:
    if s.get("market") not in MK or s.get("game") == "NE @ DET": continue
    pr = s.get("over_price") if s.get("side") == "Over" else s.get("under_price")
    if pr is None or s.get("chance") is None: continue
    edge = s["chance"] * PE.decimal(pr) - 1
    fl = " ".join(s.get("flags") or [])
    bad = any(x in fl for x in ("no games in the sample", "snap share down"))
    if 0 < edge <= 0.10 and 0.55 <= s["chance"] < 0.66 and not bad:
        out.append((s, pr, edge))
out.sort(key=lambda t: (-t[0]["chance"]))
print("newest", newest, "candidates", len(out))
for s, pr, e in out:
    print(f"S {s.get('game')} | {s['player']} | {s['market']} {s['side']} {s['line']} | {pr:+.0f} | ch {s['chance']:.3f} mkt {s.get('p_market')} | edge {e:+.3f} | proj {s['projection']:.1f} | {s.get('use_tag')} | {s.get('gap')} | {s.get('flags')}")
