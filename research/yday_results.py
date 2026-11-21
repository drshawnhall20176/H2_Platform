"""Nov 21: yesterday's (Nov 20) bets -- real and tracking-only -- and the morning brief's text."""
import sys
sys.path.insert(0, ".")
import betlog as B, model_store as MS
bets = [b for b in B.list_bets() if str(b.get("slate_date")) == "2026-11-20"]
for b in sorted(bets, key=lambda b: b.get("id") or 0):
    print(f"YR #{b.get('id')} real={b.get('is_real_bet')} hdr={B.is_parlay_header(b)} tkt={b.get('ticket')} "
          f"{b.get('sport')} {b.get('player')} {b.get('market')} {b.get('side')} {b.get('line')} @{b.get('entry_odds')} "
          f"stake={b.get('stake')} cat={b.get('category')} res={B._result(b)} pnl={B.bet_pnl(b)}")
for k in ("brief:2026-11-21", "morning_brief:2026-11-21", "brief:morning:2026-11-21"):
    v = MS.get_setting(k, None)
    if v:
        print("YR BRIEF", k, str(v)[:3000])
