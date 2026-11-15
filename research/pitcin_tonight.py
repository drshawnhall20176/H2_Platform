"""Tonight's PIT @ CIN: every model read on the board (newest), with the book price and the model's chance."""
import os, sys, json
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
day = "2026-11-15"
snaps = MS.load_snapshots("NFL", [day])
latest = {}
for s in snaps:
    g = str(s.get("game") or "")
    if not ("CIN" in g or "Cincinnati" in g) or not ("PIT" in g or "Pittsburgh" in g):
        continue
    if s.get("line") is None or s.get("projection") is None: continue
    k = (s.get("player"), s.get("market"))
    if k not in latest or str(s.get("ts")) > str(latest[k].get("ts")): latest[k] = s
print("reads", len(latest), "newest ts", max((str(s.get("ts")) for s in latest.values()), default=None))
def imp(p):
    if p is None: return None
    p = float(p); return 100 / (p + 100) if p > 0 else -p / (-p + 100)
rows = []
for (pl, mk), s in latest.items():
    side = s.get("side"); price = s.get("over_price") if side == "Over" else s.get("under_price")
    ch = s.get("chance"); be = imp(price)
    ev = None if ch is None or price is None else ch * (1 + (float(price) / 100 if float(price) > 0 else 100 / -float(price))) - 1
    fl = s.get("flags")
    rows.append((pl, mk, s["line"], s["projection"], side, ch, price, be, ev, s.get("use_tag"), s.get("gap"), fl, s.get("team")))
for r in sorted(rows, key=lambda r: -(r[5] or 0)):
    ch = "—" if r[5] is None else f"{r[5]:.0%}"; be = "—" if r[7] is None else f"{r[7]:.0%}"
    ev = "—" if r[8] is None else f"{r[8]:+.2f}"
    print(f"{r[0]:22} {r[12]:4} {r[1]:18} line {r[2]:6} proj {r[3]:6.1f} -> {r[4]:5} chance {ch:4} price {r[6]} (b/e {be}) EV {ev} | {r[9]} | gap {r[10]} | {r[11]}")
