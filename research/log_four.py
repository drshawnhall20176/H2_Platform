import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, todays_best as TB, betlog as B
WANT = [("Justin Jefferson", "Receptions", "Under", 7.5, None), ("Rashee Rice", "Receptions", "Under", 5.5, None),
        ("Terrel Bernard", "Solo Tackles", "Under", 3.5, None), ("Nico Collins", "Receptions", "Under", 4.5, -125)]
snaps = MS.load_snapshots("NFL", ["2026-11-15"])
items = []
for who, mk, side, line, px in WANT:
    c = sorted([s for s in snaps if s.get("player") == who and s.get("market") == mk and float(s.get("line") or -1) == line],
               key=lambda s: str(s.get("ts")), reverse=True)
    if not c:
        print("NOT FOUND", who); continue
    s = c[0]
    price = px if px is not None else (s.get("over_price") if side == "Over" else s.get("under_price"))
    items.append({"sport": "NFL", "game": s["game"], "player": who, "market": mk, "side": side, "line": line,
                  "price": price, "book": s.get("book") or "draftkings", "chance": s.get("chance"),
                  "pick": f"{who} {mk} {side} {line:g}"})
res = TB.log_selection(items, "Parlay", 2.0, 2.5, 925, True, "nfl-sweet-spot", "2026-11-15")
print("RESULT", res)
ids = set(res.get("singles") or []) | ({res["ticket"]} if res.get("ticket") else set())
for b in B.list_bets():
    if b.get("id") in ids or (res.get("ticket") and (b.get("parlay_id") == res["ticket"] or b.get("parent_id") == res["ticket"])):
        print("BET", b["id"], b.get("player"), b.get("market"), b.get("side"), b.get("line"), b.get("entry_odds"), b.get("stake"), b.get("parlay_id"), b.get("game"))
