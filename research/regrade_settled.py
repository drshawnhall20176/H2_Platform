"""Nov 21: regrade settled basketball prop bets against FINAL box scores (settlement used to read games still in
progress). Dry run prints every mismatch; regrade_apply.py writes the corrections."""
import os, sys
sys.path.insert(0, ".")
import betlog as B, settle_results as SR, sports
APPLY = os.environ.get("REGRADE_APPLY") == "1"
FROM = "2026-10-20"
bets = [b for b in B.list_bets() if str(b.get("slate_date") or "") >= FROM and B._result(b) in ("win", "loss")
        and b.get("sport") in ("NBA", "NCAAMB", "WNBA") and b.get("market") and b.get("player")]
print(f"RG {len(bets)} settled basketball prop bets since {FROM}")
by = {}
for b in bets:
    by.setdefault((b["sport"], str(b["slate_date"])), []).append(b)
fix, tally = [], {}
for (sp, d), bs in sorted(by.items()):
    res = sports.get(sp).engine.get_player_results(d)
    if not res:
        print(f"RG {sp} {d}: no final results"); continue
    known = SR._ids_by_name(bs, res)
    for b in bs:
        bb = b if b.get("player_id") is not None else dict(b, player_id=known.get(SR._norm(b.get("player"))))
        g = SR.settle_bet(bb, res) if bb.get("player_id") is not None else None
        old = B._result(b)
        t = tally.setdefault(d, [0, 0, 0])
        if g is None:
            t[2] += 1; continue
        if g != old:
            t[1] += 1
            fix.append((b, g))
            print(f"RG MISMATCH #{b['id']} {d} {sp} {b['player']} {b['market']} {b['side']} {b.get('line')} "
                  f"logged={old} final={g} ticket={B._ticket(b) or '-'} real={b.get('is_real_bet')}")
        else:
            t[0] += 1
for d, (ok, bad, unk) in sorted(tally.items()):
    print(f"RG {d}: agree {ok}, wrong {bad}, can't regrade {unk}")
print(f"RG total wrong: {len(fix)}")
if APPLY:
    for b, g in fix:
        B.update_bet(b["id"], result=g)
        print(f"RG fixed #{b['id']} -> {g}")
    tick = {B._ticket(b) for b, _ in fix if B._ticket(b)}
    print(f"RG tickets touched: {sorted(tick)}")
