"""Nov 10: are the model's MILESTONE chances honest in the tail? (owner: Fears 8+ assists at +1500 hit; could we have
seen it?) Walk-forward NBA backtest (props_backtest, no peeking): for every player-game, the model's chance of N+ at
rungs above his projection, vs how often N+ actually happened. Books price these long shots at 5-20%, so the 5-30%
range is what matters."""
import os, sys, math
from collections import defaultdict
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import props_backtest as BT, props_engine as PE, position_data as PD, player_props as PPR

cap = []
_orig = PE.read_line
def spy(model, vals, line, dist, *a, **k):
    cap.append((model, list(vals), dist))
    return _orig(model, vals, line, dist, *a, **k)
PE.read_line = spy
sample = PD.nba_league_props_sample(date.today().isoformat())
pg = (sample.get("cur") or []) + (sample.get("prior") or [])
print("TC pgames", len(pg))
BINS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 0.30), (0.30, 0.40), (0.40, 0.55)]
for market in ("Points", "Rebounds", "Assists", "Threes Made", "PRA"):
    cap.clear()
    BT_cases = []
    orig_summ = BT.summarize
    BT.summarize = lambda cases: (BT_cases.extend(cases), orig_summ(cases))[1]
    BT.backtest_basketball(pg, "NBA", market, max_cases=6000)
    BT.summarize = orig_summ
    step = PE.ladder_step(market, 10)
    cell = defaultdict(lambda: [0, 0, 0.0])
    for (model, vals, dist), c in zip(cap, BT_cases):
        base = math.floor(model / step) * step
        for k in (1, 2, 3):
            n = base + k * step
            p = PE.prob_over(model, vals, n - 0.5, dist)
            if p is None:
                continue
            for lo, hi in BINS:
                if lo <= p < hi:
                    x = cell[(lo, hi)]; x[0] += 1; x[1] += c["actual"] >= n; x[2] += p
    print("TC", market, "cases", len(BT_cases), "dist", PPR.DIST.get(market, "normal"))
    for lo, hi in BINS:
        n, h, ps = cell[(lo, hi)]
        if n >= 30:
            print("TC  ", f"model {lo:.0%}-{hi:.0%}: n={n:5d} said {ps/n:5.1%} happened {h/n:5.1%}  ratio {h/ps:.2f}")
PE.read_line = _orig
