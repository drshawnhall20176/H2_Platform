import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, intl_hoops as I
from datetime import date
games = MS.load_results("NCAAMB", since="2025-10-01")
gg = [g for g in games if g["date"][:10] < "2026-11-22"]
w = I.decay_weights(gg, "2026-11-22", "NCAAMB")
old = I.ratings_weighted(gg, w, I.LEAGUES["NCAAMB"]["lam"], (3.0, 200.0))
new = I.ratings_weighted(gg, w, I.LEAGUES["NCAAMB"]["lam"], I.HFA_PRIOR["NCAAMB"])
print("hfa old %.2f new %.2f" % (old["hfa"], new["hfa"]))
want = ["Memphis", "Fordham", "Cincinnati", "Wyoming", "GW Revolutionaries", "South Dakota"]
recs = [p for p in MS.load_game_picks("NCAAMB") if str(p.get("kickoff",""))[:10] in ("2026-11-22",) and any(w_ in p.get("home","") for w_ in want)]
for p in recs:
    neu = bool(p.get("neutral"))
    po = I.project(old, p["home"], p["away"], neutral=False); pn = I.project(new, p["home"], p["away"], neutral=neu)
    def n(t): 
        k = I.find_team(list(new["off"].keys()), t); return sum(1 for g in gg if g["home_team"]==k or g["away_team"]==k) if k else 0
    print(f"{p['away']} @ {p['home']} {'(neutral)' if neu else ''} | book home spread {p.get('home_spread')} total {p.get('line_total')} | OLD model home by {po['margin'] if po else None} total {po['total'] if po else None} | NEW home by {pn['margin'] if pn else None} total {pn['total'] if pn else None} | games on file: {p['away'].split()[0]} {n(p['away'])}, {p['home'].split()[0]} {n(p['home'])} | use {p.get('use')}")
