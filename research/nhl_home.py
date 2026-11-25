"""Nov 25 health check: 'NHL game model leans road on 11 of 13 upcoming games'. Is home ice under-rated? Aggregates only."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date, timedelta
import model_store as MS

recs = MS.load_game_picks("NHL")
graded = [r for r in recs if r.get("final_home") is not None and r.get("model_margin") is not None]
up = [r for r in recs if r.get("final_home") is None and r.get("model_margin") is not None and str(r.get("kickoff") or "")[:10] >= date.today().isoformat()]
print("graded", len(graded), "upcoming", len(up))
for days in (14, 28, 60, 400):
    lo = (date.today() - timedelta(days=days)).isoformat()
    sub = [r for r in graded if str(r.get("kickoff") or "")[:10] >= lo]
    if not sub:
        continue
    act = [float(r["final_home"]) - float(r["final_away"]) for r in sub]
    mod = [float(r["model_margin"]) for r in sub]
    mk = [-float(r["home_spread"]) for r in sub if r.get("home_spread") is not None]
    hw = sum(1 for a in act if a > 0) / len(act)
    mp = [float(r["model_p"]) for r in sub if r.get("model_p") is not None]
    fh = [float(r["fair_home"]) for r in sub if r.get("fair_home") is not None]
    print(f"== last {days} days: {len(sub)} games: home won {hw:.1%}; avg actual home margin {sum(act)/len(act):+.2f}; "
          f"model {sum(mod)/len(mod):+.2f}; model home win% {sum(mp)/len(mp) if mp else float('nan'):.1%}; "
          f"market no-vig home {sum(fh)/len(fh) if fh else float('nan'):.1%}")
print("== upcoming ==")
if up:
    mod = [float(r["model_margin"]) for r in up]
    mp = [float(r["model_p"]) for r in up if r.get("model_p") is not None]
    fh = [float(r["fair_home"]) for r in up if r.get("fair_home") is not None]
    print(f"  {len(up)} games: model favors home in {sum(1 for m in mod if m > 0)}; avg model home margin {sum(mod)/len(mod):+.2f}; "
          f"model home win% {sum(mp)/len(mp) if mp else float('nan'):.1%}; market no-vig home {sum(fh)/len(fh) if fh else float('nan'):.1%}")
    for r in sorted(up, key=lambda r: str(r.get("kickoff")))[:16]:
        print(f"   {r.get('away')} @ {r.get('home')}: model home {float(r.get('model_p') or 0):.0%} vs market "
              f"{'' if r.get('fair_home') is None else format(float(r['fair_home']), '.0%')}, margin {float(r['model_margin']):+.2f}")
try:
    import nhl_engine as NE
    print("hfa-ish constants:", {k: getattr(NE, k) for k in dir(NE) if "HFA" in k.upper() or "HOME" in k.upper()}) 
except Exception as e:
    print("no nhl_engine", e)
