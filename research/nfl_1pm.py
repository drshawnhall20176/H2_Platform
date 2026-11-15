import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, todays_best as TB
snaps = MS.load_snapshots("NFL", ["2026-11-15"])
latest = {}
for s in snaps:
    k = (s.get("player"), s.get("market"), s.get("line"), s.get("game"))
    if k not in latest or str(s.get("ts")) > str(latest[k].get("ts")):
        latest[k] = s
rows = list(latest.values())
times = {}
for s in rows: times.setdefault(s.get("game"), s.get("game_time") or s.get("kickoff") or "")
print("GAMES", sorted(times.items(), key=lambda kv: str(kv[1])))
newest = max(str(s.get("ts")) for s in rows)
print("newest read", newest)
fresh = [s for s in rows if str(s.get("ts")) >= newest[:13]]
print("reads in newest build", len(fresh))
fresh.sort(key=lambda s: -(s.get("chance") or 0))
for s in fresh[:90]:
    print(f"R {s.get('game')} | {s.get('player')} | {s.get('market')} {s.get('side')} {s.get('line')} | ch {s.get('chance'):.3f} | mkt {s.get('p_market')} | proj {s.get('projection'):.1f} | {s.get('use_tag')} | {s.get('gap')} | o{s.get('over_price')} u{s.get('under_price')} | {s.get('flags')}")
p = TB.load_props("NFL", "2026-11-15")
print("TODAYS BEST", p.get("at"))
for r in p.get("rows") or []:
    print("TB", r.get("time"), r.get("game"), r.get("pick") or r.get("Pick"), r.get("use") or r.get("Use"), r.get("chance") or r.get("Chance"))
