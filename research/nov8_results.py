import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, model_store as MS
bets = [b for b in B.list_bets() if b.get("is_real_bet") and str(b.get("slate_date"))[:10] == "2026-11-08"]
for b in sorted(bets, key=lambda b: b["id"]):
    print("NR", b["id"], b.get("sport"), B._ticket(b) or "single", "|", b.get("player") or "", b.get("market"), b.get("side"), b.get("line"),
          "|", b.get("entry_odds"), "$", b.get("stake"), "| model", b.get("model_prob"), "|", b.get("result"), "| pnl", B.bet_pnl(b), "|", b.get("notes"))
rep = MS.load_daily_review("NFL", "2026-11-09") or {}
for k in ("left", "unsettled", "needs_person", "open"):
    if rep.get(k):
        print("NR LEFT", k, str(rep[k])[:1500])
print("NR keys", list(rep.keys()))
