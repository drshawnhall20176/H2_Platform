import sys
sys.path.insert(0, ".")
import pick_ledger as PL, todays_best as TB, money_score as MSC
D = "2026-11-21"
cache = {}
rows = PL.rows("strong", "ALL", D)
recs = {}
for r in TB.winner_rows(D, leagues=list(MSC.MONEY_LEAGUES)):
    gid = (r.get("_rec") or {}).get("game_id")
    if gid is not None:
        recs[gid] = r.get("_full") or {}
for r in rows:
    if r.get("money_market"):
        c = PL.game_close(r, recs.get(r.get("game_id")))
    else:
        c = PL.prop_close(r, PL._snap_closes(r["sport"], D, cache))
    print(f"CL {r.get('sport')} {r.get('pick')} {r.get('line') or r.get('money_line')} {r.get('price')} -> {c}")
