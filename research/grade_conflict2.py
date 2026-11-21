"""Nov 21: what does the Bet Log's settlement path see for the Nov 20 picks?"""
import sys
sys.path.insert(0, ".")
import betlog as B, retro as R, settle_results as SR, sports
D = "2026-11-20"
bets = [b for b in B.list_bets() if str(b.get("slate_date")) == D and b.get("player_id")]
for sp in ("NCAAMB", "NBA"):
    res = sports.get(sp).engine.get_player_results(D)
    print(f"GC2 {sp} results players={len(res)}")
    for b in [b for b in bets if b.get("sport") == sp]:
        a = res.get(b["player_id"]) or res.get(int(b["player_id"]))
        stat = R.MARKET_STAT.get(b.get("market")) if hasattr(R, "MARKET_STAT") else None
        print(f"GC2 #{b['id']} {b['player']} {b['market']} {b['side']} {b['line']} stat_key={stat} "
              f"actual={({k: a.get(k) for k in (stat if isinstance(stat, (list, tuple)) else [stat]) if k} if a else None)} "
              f"grade_now={SR.settle_bet(b, res)} logged={B._result(b)}")
