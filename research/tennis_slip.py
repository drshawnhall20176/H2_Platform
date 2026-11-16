import os, sys, json
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
recs = MS.load_game_picks("TENNIS", ungraded=True)
for r in recs:
    names = (str(r.get("home")) + " " + str(r.get("away"))).lower()
    if any(k in names for k in ("trevisan", "maristany", "tiafoe", "alcaraz", "cobolli", "medvedev")):
        print(json.dumps({k: v for k, v in r.items() if v not in (None, "", [], {})}, default=str)[:2500])
print("total", len(recs))
