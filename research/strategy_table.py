"""research/strategy_table.py — print the Progression Plan's strategy table (Nov 4). Read-only."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    import betlog as B
    import model_store as MS
    import progression as P
    s = dict(P.DEFAULTS, **(MS.get_setting(P.SETTINGS_KEY, {}) or {}))
    bets = B.list_bets(is_real_bet=True)
    r = P.plan(s, bets)
    print(f"BANKROLL {r['bankroll']} profit {r['profit']} singles {r['singles']} ROI {r['singles_roi']} parlays {r['parlays']} "
          f"ROI {r['parlay_roi']} parlay share {r['discipline']['parlay_share']}")
    for x in P.strategies(bets, str(s["start_date"])):
        f = lambda v, sg=False: "—" if v is None else (f"{v:+.1%}" if sg else f"{v:.0%}")
        print(f"STRAT {x['strategy']:22s} bets {x['bets']:3d} parlays {x['parlays']} staked ${x['staked']:7.2f} "
              f"profit ${x['profit']:+8.2f} ROI {f(x['roi'], True):>7s} | legs {x['legs']:3d} won {f(x['leg_hit']):>4s} "
              f"implied {f(x['leg_implied']):>4s} as-singles {f(x['singles_per_leg'], True):>7s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
