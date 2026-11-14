import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, model_store as MS
ps = {p["game_id"]: p for p in MS.load_game_picks("TENNIS")}
for gid in ("espn-wta-186768", "espn-atp-186551", "espn-wta-187384"):
    p = ps.get(gid)
    print("PICK", gid, None if not p else {k: p.get(k) for k in ("home", "away", "kickoff", "result", "final_home", "final_away", "model_p")})
bets = {b["id"]: b for b in B.list_bets()}
for i in range(664, 700):
    b = bets.get(i)
    if b and (b.get("sport") == "TENNIS"):
        print("BET", i, b.get("slate_date"), b.get("player"), b.get("market"), b.get("result"), b.get("entry_odds"), b.get("stake"), str(b.get("notes"))[:70], b.get("parlay_id") or b.get("ticket_id") or b.get("parent_id"))
print("bet keys", sorted(next(iter(bets.values())).keys()))
