import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B
bets = B.list_bets()
hdr = next((b for b in bets if b["id"] == 615), None)
print("DD header", hdr and (hdr.get("market"), hdr.get("entry_odds"), hdr.get("stake"), B._ticket(hdr)))
if hdr and hdr.get("market") == "Parlay" and float(hdr.get("entry_odds") or 0) == 100:
    legs = [b for b in bets if b["id"] in range(616, 621)]
    for b in [hdr] + legs:
        B.delete_bet(b["id"]); print("DD deleted", b["id"], b.get("player"), b.get("market"))
tot = sum(B.bet_pnl(b) or 0 for b in B.list_bets() if str(b.get("slate_date"))[:10] == "2026-11-08" and b.get("is_real_bet")
          and (not B._ticket(b) or B.is_parlay_header(b)))
print("DD day total", round(tot, 2))
