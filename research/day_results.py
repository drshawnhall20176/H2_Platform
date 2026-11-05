"""research/day_results.py — every real bet for a day with its result and profit (read-only)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    import betlog as B
    day = os.environ.get("DAY", "2026-11-04")
    rows = [b for b in B.list_bets(is_real_bet=True) if str(b.get("slate_date"))[:10] in (day, "2026-11-05")
            and float(b.get("stake") or 0) > 0]
    tot_s = tot_p = 0.0
    for b in sorted(rows, key=lambda x: (x.get("sport") or "", x.get("id"))):
        pnl = B.bet_pnl(b) if b.get("result") else None
        if b.get("result"):
            tot_s += float(b["stake"]); tot_p += pnl or 0
        print(f"#{b['id']:>4} {b.get('sport'):7s} {str(b.get('player'))[:28]:28s} {str(b.get('market'))[:11]:11s} "
              f"{str(b.get('side'))[:22]:22s} {b.get('line')!s:6s} {b.get('entry_odds'):+.0f} ${float(b['stake']):.2f} "
              f"{b.get('result') or 'OPEN':5s} {'' if pnl is None else f'{pnl:+.2f}'} {'T:' + b['ticket'] if b.get('ticket') else ''}")
    print(f"settled stake ${tot_s:.2f}, profit ${tot_p:+.2f}, open {sum(1 for b in rows if not b.get('result'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
