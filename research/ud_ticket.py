import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
want = {"NBA": [("zion", "Rebounds"), ("mcdaniels", "RA"), ("jokic", "PRA"), ("jokić", "PRA")],
        "NFL": [("brissett", "Pass Yards"), ("justice hill", "Rush + Rec Yards"), ("justice hill", "Rush Yards"), ("justice hill", "Receiving Yards")]}
for sp, ws in want.items():
    for d in ("2026-11-16", "2026-11-17"):
        latest = {}
        for s in MS.load_snapshots(sp, [d]):
            nm = str(s.get("player")).lower()
            for w, mk in ws:
                if w in nm and s.get("market") == mk:
                    k = (s["player"], mk)
                    if k not in latest or str(s.get("ts")) > str(latest[k].get("ts")): latest[k] = s
        for (p, m), s in latest.items():
            print(f"R {sp} {d} {p:20} {m:16} line {s.get('line')} proj {s.get('projection')} side {s.get('side')} ch {s.get('chance')} "
                  f"pmod {s.get('p_model')} use {s.get('use_tag')} gap {s.get('gap')} | {str(s.get('flags'))[:80]}")
# long shots logged / suggested?
import betlog as B
for b in B.list_bets():
    if str(b.get("slate_date")) in ("2026-11-16",) and any(x in str(b.get("player")).lower() for x in ("brissett", "hill", "zion", "jokic", "mcdaniels")):
        print("BET", b.get("id"), b.get("player"), b.get("market"), b.get("side"), b.get("line"), b.get("entry_odds"), b.get("result"), b.get("notes"))
