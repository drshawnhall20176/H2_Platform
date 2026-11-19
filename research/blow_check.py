import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, script_effects as SE
cs = MS.get_setting("scenario_calls:NBA", None) or {}
for k in list(cs.get("pending") or []) + list(cs.get("graded") or []):
    if "Dallas" in str(k.get("fav")) + str(k.get("dog")) and str(k.get("kick", ""))[:10] in ("2026-11-18", "2026-11-19"):
        print("BC call", {x: k.get(x) for x in ("fav", "dog", "kick", "y", "margin", "home", "away")})
for g in MS.load_results("NBA", since="2026-11-17"):
    if "Dallas" in g["home_team"] + g["away_team"]:
        print("BC final", g)
print("BC data", {k: SE.DATA["NBA"].get(k) for k in ("close", "blow")})
