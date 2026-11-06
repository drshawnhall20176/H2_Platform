import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import analyst_ledger as AL, betlog as B, investor as I, model_store as MS
calls = AL.fetch_calls(); reports = {}
for sp in I.SPORTS:
    ms = MS.daily_review_mornings(sp)
    if ms:
        reports[sp] = MS.load_daily_review(sp, ms[0]) or {}
bets = B.list_bets()
lc = I.locked_calls(calls)
print("LOCKED", {k: lc[k] for k in ("locked", "n", "hit", "said", "lo", "hi", "first", "last", "published")})
for r in lc["by_sport"]: print("  ", r)
for t in I.use_tags(reports): print("TAG", t["sport"], t["use"], t["n"], t["hit"] and round(t["hit"], 3), t["said"] and round(t["said"], 3), t["lo"] and round(t["lo"], 3), t["morning"])
print("CAL rows", len(I.calibration(reports)))
for c in I.calibration(reports): print("  CAL", c)
print("CLV", I.closing_line(bets))
rm = I.real_money(bets); print("REAL", {k: rm.get(k) for k in ("settled", "roi", "singles", "singles_hit", "lo", "hi", "first", "last", "clv_n", "beat_close_rate")})
