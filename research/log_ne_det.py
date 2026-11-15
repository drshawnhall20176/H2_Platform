import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, todays_best as TB, betlog as B
WANT = [("Sam LaPorta", "Receptions", "Under", 4.5), ("A.J. Brown", "Receiving Yards", "Over", 51.5),
        ("Jahmyr Gibbs", "Rush Yards", "Over", 89.5), ("Hunter Henry", "Receiving Yards", "Over", 39.5),
        ("Jared Goff", "Pass Completions", "Under", 23.5), ("Rhamondre Stevenson", "Rush Attempts", "Under", 11.5),
        ("Jake Bates", "FG Made", "Over", 1.5), ("Roger McCreary", "Tackles + Assists", "Over", 3.5)]
snaps = [s for s in MS.load_snapshots("NFL", ["2026-11-15"]) if s.get("game") == "NE @ DET"]
items = []
for who, mk, side, line in WANT:
    c = sorted([s for s in snaps if s.get("player") == who and s.get("market") == mk and float(s.get("line") or -1) == line],
               key=lambda s: str(s.get("ts")), reverse=True)
    if not c:
        print("NOT FOUND", who, mk); continue
    s = c[0]
    price = s.get("over_price") if side == "Over" else s.get("under_price")
    items.append({"sport": "NFL", "game": s["game"], "player": who, "market": mk, "side": side,
                  "line": line, "price": price, "book": s.get("book") or "draftkings", "chance": s.get("chance"),
                  "pick": f"{who} {mk} {side} {line:g}"})
res = TB.log_selection(items, "Singles", 3.0, 0.0, None, True, "ne-det-pick6", "2026-11-15")
print("RESULT", res)
for b in B.list_bets():
    if b.get("id") in (res.get("singles") or []):
        print("BET", b["id"], b["player"], b["market"], b["side"], b["line"], b["entry_odds"], b["stake"], b["book"])
