"""research/progression_check.py — audit what the Progression Plan is counting (Nov 4). Read-only."""
import os
import sys
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    import betlog as B
    import model_store as MS
    import progression as P
    saved = MS.get_setting(P.SETTINGS_KEY, None)
    print("SAVED SETTINGS:", saved)
    allb = B.list_bets()
    real = B.list_bets(is_real_bet=True)
    r = P.plan(saved or {}, real, date.today())
    s = r["settings"]
    print(f"PLAN: start {s['start_date']} bankroll {s['start_bankroll']} -> {r['bankroll']} (profit {r['profit']}), "
          f"settled {r['settled']}, singles {r['singles']}, parlays {r['parlays']}, singles ROI {r['singles_roi']}, "
          f"parlay ROI {r['parlay_roi']}, max_dd {r['max_dd']}, stage {r['stage']}")
    print("MONTHS:", r["months"])
    print("DISCIPLINE:", r["discipline"])
    start = str(s["start_date"])
    since = [b for b in allb if str(b.get("slate_date") or b.get("ts_placed") or "")[:10] >= start]
    money = B.money_bets(since)
    rows = defaultdict(lambda: {"n": 0, "open": 0, "stake": 0.0, "pnl": 0.0})
    for b in money:
        real_flag = b.get("is_real_bet") not in (False, 0, "0", "false")
        k = (str(b.get("slate_date"))[:10], b.get("sport"), "REAL" if real_flag else "tracking")
        rows[k]["n"] += 1
        rows[k]["stake"] += float(b.get("stake") or 0)
        rows[k]["pnl"] += B.bet_pnl(b) or 0
        rows[k]["open"] += 0 if B._result(b) else 1
    print("\nBY DATE / SPORT / KIND (money rows since start):")
    for k in sorted(rows):
        v = rows[k]
        print(f"  {k[0]} {k[1]:7s} {k[2]:8s} n={v['n']:3d} open={v['open']:2d} stake=${v['stake']:8.2f} pnl=${v['pnl']:+8.2f}")
    print("\nOPEN REAL MONEY ROWS:")
    for b in money:
        if b.get("is_real_bet") not in (False, 0, "0", "false") and not B._result(b):
            print(f"  #{b['id']} {b.get('slate_date')} {b.get('sport')} {b.get('player') or b.get('ticket')} {b.get('market')} "
                  f"{b.get('side')} {b.get('line')} @ {b.get('entry_odds')} stake {b.get('stake')} notes={b.get('notes')}")
    print("\nNOV 1-3 ROWS WITH TAGS (to check real vs tracking):")
    for b in sorted(money, key=lambda x: x.get("id") or 0):
        if str(b.get("slate_date"))[:10] <= "2026-11-03":
            print(f"  #{b['id']} {str(b.get('slate_date'))[:10]} {b.get('sport')} real={b.get('is_real_bet')} "
                  f"{(b.get('player') or b.get('ticket') or '')[:28]:28s} {b.get('market')} stake={b.get('stake')} "
                  f"res={B._result(b) or 'open'} notes={(b.get('notes') or '')[:40]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
