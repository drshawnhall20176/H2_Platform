import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, model_store as MS
for i in (691, 698):
    b = next(x for x in B.list_bets() if x["id"] == i)
    B.update_bet(i, result="void", notes=(str(b.get("notes") or "") + " | void: Muchova replaced by Shnaider (DK voided)").strip(" |"))
MS.grade_game_pick("TENNIS", "espn-wta-187384", 0, 0, "void")
bets = {b["id"]: b for b in B.list_bets()}
print("NOW", [(i, bets[i]["result"]) for i in (691, 698)])
print("OPEN LEFT", [(b["id"], b.get("sport"), b.get("player")) for b in bets.values() if not b.get("result")])
