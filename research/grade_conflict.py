"""Nov 21: Bet Log vs Command Center grading conflict on Nov 20 picks -- the actual stats from both paths."""
import sys
sys.path.insert(0, ".")
import betlog as B, model_store as MS, postgame as PG, props_engine as PE, settle_results as SR
D = "2026-11-20"
bets = {b["id"]: b for b in B.list_bets() if str(b.get("slate_date")) == D}
for sp in ("NCAAMB", "NBA"):
    snaps = MS.load_snapshots(sp, [D])
    res = PG.fetch_results(sp, D, sorted({(s["team"], s["opp"]) for s in snaps}))
    graded = PG.grade(snaps, res)
    mine = [b for b in bets.values() if b.get("sport") == sp]
    names = {PE.norm_name(b.get("player") or "") for b in mine}
    for g in graded:
        if PE.norm_name(g.get("player") or "") in names:
            print(f"GC postgame {sp} {g.get('player')} {g.get('market')} line={g.get('line')} actual={g.get('actual')} pid={g.get('player_id')}")
    try:
        sres = SR.settle_for_sport(sp, mine) if False else None
    except Exception as e:
        print("GC settle err", e)
    for b in sorted(mine, key=lambda b: b["id"]):
        print(f"GC bet #{b['id']} {b.get('player')} {b.get('market')} {b.get('side')} {b.get('line')} pid={b.get('player_id')} res={B._result(b)} notes={str(b.get('notes'))[:80]}")
