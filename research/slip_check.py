import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
import pytz, numpy as np
import model_store as MS, long_shots as LS, props_engine as PE, slip_sim as SIM
day = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
snaps = MS.load_snapshots("NBA", [day])
print("snapshots today", len(snaps))
legs = [("Michael Porter", "Points", 18, "g1"), ("Dosunmu", "Points", 15, "g2"), ("LaMelo Ball", "Points", 18, "g2"),
        ("LaMelo Ball", "Threes Made", 4, "g2"), ("McDaniels", "Rebounds", 6, "g2"), ("Antetokounmpo", "Points", 25, "g3"),
        ("Ausar Thompson", "Rebounds", 6, "g3")]
out = []
for who, mk, n, g in legs:
    c = [s for s in snaps if who.lower() in str(s.get("player") or "").lower() and s.get("market") == mk]
    c.sort(key=lambda s: str(s.get("ts") or ""), reverse=True)
    if not c:
        print(f"LEG {who} {mk} {n}+: no read today"); out.append(None); continue
    s = c[0]
    f = LS.fit(s, "NBA")
    raw = LS.rung_raw(f, n) if f else None
    hon = LS.honest(raw, mk, "NBA") if raw is not None else None
    print(f"LEG {s.get('player')} {mk} {n}+ | proj {s.get('projection'):.1f} line {s.get('line')} over {s.get('over_price')} under {s.get('under_price')} "
          f"| model P(over main) {s.get('p_model')} mkt {s.get('p_market')} | P({n}+) raw {raw:.0%} honest {hon:.0%} | team {s.get('team')} opp {s.get('opp')} | game {s.get('game')} flags {s.get('flags')}")
    out.append({"p": hon, "player": s.get("player"), "game": g, "team": s.get("team"), "sport": "NBA", "side": "Over"})
ok = [o for o in out if o]
if len(ok) == len(legs):
    ps = np.array([o["p"] for o in ok])
    R = SIM.correlation_matrix(ok)
    Z = np.random.default_rng(1).multivariate_normal(np.zeros(len(ok)), R, 200000)
    from scipy.stats import norm
    hit = (Z < norm.ppf(ps)).all(axis=1).mean()
    print(f"SLIP independent {np.prod(ps):.2%}  correlated {hit:.2%}  break-even at +1073: {1/11.73:.2%}")
