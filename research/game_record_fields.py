import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
for lg in ("NCAAMB", "NBA", "NHL", "NFL", "NCAAF", "UFC", "TENNIS", "EUROLEAGUE", "EUROCUP", "NBL", "BCL", "FEC", "EUROCUPW", "NKL"):
    try:
        recs = MS.load_game_picks(lg, ungraded=True)
    except Exception as e:
        print(lg, "ERR", e); continue
    print(f"== {lg}: {len(recs)} ungraded")
    if recs:
        r = recs[-1]
        print("   ", json.dumps({k: r[k] for k in sorted(r) if not isinstance(r[k], (list, dict))}, default=str)[:900])
