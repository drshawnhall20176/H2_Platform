"""Nov 9: repair the Nov 8 bets logged without player/side/line (stale My Coach cache), grade them and the NBA parlay
legs from the graded kickoff snapshots, then settle the tickets."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, daily_review as D, props_engine as PE
WRITE = True
bets = {b["id"]: b for b in B.list_bets()}
g = {}
for sp in ("NFL", "NBA"):
    g[sp] = [r for rows in D.grade_dates(sp, ["2026-11-08"]).values() for r in rows]
    print("RP graded rows", sp, len(g[sp]), "keys", sorted(g[sp][0].keys())[:30] if g[sp] else None)
def res_word(r):
    return {"hit": "win", "miss": "loss", "push": "push"}.get(r.get("result"))
for bid in range(610, 627):
    b = bets.get(bid)
    if not b or b.get("market") == "Parlay" or B.is_parlay_header(b):
        continue
    mp = b.get("model_prob")
    cands = [r for r in g["NFL"] if r.get("market") == b.get("market") and r.get("chance") is not None
             and abs(float(r["chance"]) - float(mp)) < 0.0015]
    print("RP", bid, b.get("market"), mp, "->", [(r.get("player"), r.get("side"), r.get("line"), r.get("price"), r.get("result"), r.get("game")) for r in cands][:4])
    if len(cands) == 1 and WRITE:
        r = cands[0]
        B.update_bet(bid, player=r.get("player"), side=r.get("side"), line=float(r["line"]), game=r.get("game"),
                     **({"result": res_word(r)} if res_word(r) else {}))
for bid in range(628, 633):
    b = bets.get(bid)
    if not b:
        continue
    key = (PE.norm_name(b.get("player")), b.get("market"), b.get("side"), float(b.get("line")))
    cands = [r for r in g["NBA"] if (PE.norm_name(r.get("player")), r.get("market"), r.get("side"), float(r.get("line") or -1)) == key]
    print("RP NBA", bid, key, "->", [(r.get("result"), r.get("actual"), r.get("game")) for r in cands][:2])
    if cands and res_word(cands[0]) and WRITE:
        B.update_bet(bid, result=res_word(cands[0]), game=cands[0].get("game"))
allb = B.list_bets()
for t in B.ticket_settlements(allb):
    if WRITE:
        B.update_bet(t["id"], result=t["result"])
    print("RP ticket", t)
for b in B.list_bets():
    if str(b.get("slate_date"))[:10] == "2026-11-08" and b.get("is_real_bet") and b["id"] >= 610:
        print("RP NOW", b["id"], B._ticket(b) or "single", b.get("player"), b.get("market"), b.get("side"), b.get("line"), b.get("entry_odds"), b.get("stake"), b.get("result"), B.bet_pnl(b))
