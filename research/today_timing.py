import os, sys, time
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB, customer_today as CT, pick_records as PR, line_history as LH, sports
day = "2026-11-17"
def t(label, f):
    a = time.time(); r = f(); print(f"T {label}: {time.time()-a:.1f}s"); return r
live = [s.key for s in sports.enabled_sports() if sports.in_season(s.key)]
keys = [k for k in live if k in CT.PROPS_SPORTS]
print("keys", keys)
b = t("collect", lambda: TB.collect(day, keys))
w = t("winner_rows", lambda: TB.winner_rows(day))
for sp in TB.MOVE_SPORTS:
    idx = t(f"sport_index {sp}", lambda: LH.sport_index(sp, since=day))
    print("   series", len(idx), "rows", sum(len(v) for v in idx.values()))
    t(f"market_moves {sp}", lambda: TB.market_moves(sp, day, [dict(r) for r in b["rows"]], index=idx))
t("prop_picks", lambda: CT.prop_picks(b["rows"]))
t("line_picks", lambda: CT.line_picks(w))
for sp in ("NBA", "NCAAMB", "NHL", "NFL", "NCAAF"):
    t(f"tag_records {sp}", lambda: PR.tag_records(sp))
    t(f"lean_records {sp}", lambda: PR.lean_records(sp))
