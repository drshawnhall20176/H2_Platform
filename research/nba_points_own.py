"""Nov 14 -- NBA points: regress the recent per-minute rate toward the player's OWN longer rate. Grid over minutes of
half-trust, the model's own walk-forward backtest (props_backtest)."""
import os, sys
from datetime import date
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import props_backtest as BT, player_props as PPR, position_data as PD
smp = PD.nba_league_props_sample(date.today().isoformat())
pg = (smp.get("cur") or []) + (smp.get("prior") or [])
print("NBA pgames", len(pg))
for mk in ("Points", "PRA", "PA", "PR"):
    for k in (0, 60, 120, 240, 480, 960):
        PPR.OWN_SHRINK_MIN["pts"] = float(k)
        r = BT.backtest_basketball(pg, "NBA", mk, max_cases=4000)
        lb = r.get("lean_base") or 0
        print(f"OWN {mk:7} K={k:4d} n={r['n']} brier {r['brier_model']:.4f} mae {r['mae_model']:.3f} side {r['side_rate']:.1%} "
              f"leans {r['lean_n']} hit {r['lean_rate']:.1%} base {lb:.1%} edge {(r['lean_rate'] - lb) * 100:+.1f} slope {r.get('slope') or 0:.2f}")
