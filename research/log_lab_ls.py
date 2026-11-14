import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lab_long_shots as L
import todays_best as TB
import betlog as B
DAY = "2026-11-14"
WANT = [("New Zealand Breakers to win", "Sydney Kings"), ("Reading to win", "Stockport"), ("Rochdale to win", "York"),
        ("Draw", "Botafogo-SP"), ("Draw", "Bosnia"), ("Shea Charles anytime goal", None),
        ("András Schäfer anytime goal", None)]
rows = [r for v in L.collect(DAY).values() for r in v["top"]]
items = []
for pick, game in WANT:
    m = [r for r in rows if r["pick"] == pick and (game is None or game in r["game"])]
    if not m:
        print("NOT FOUND:", pick, game); continue
    r = m[0]
    items.append(dict(r, best=r["pick"], bet_price=r["price"]))
    print("found:", r["pick"], "|", r["game"], int(r["price"]))
res = TB.log_selection(items, "Singles", 1.0, 0.0, None, True, "long-shot,lab", DAY)
print("RESULT", res)
for b in B.list_bets():
    if b.get("id") in res["singles"]:
        print(b["id"], b["sport"], b["game"], b["player"], b["market"], b["side"], b["line"], b["entry_odds"], b["stake"], b["notes"])
