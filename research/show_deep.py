import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
for sp in ("NBA", "NCAAMB"):
    f = MS.get_setting(f"script_learn:{sp}", {}) or {}
    print(sp, f.get("fit_at"), "games", f.get("games"))
    for g in sorted(k for k in (f.get("effects") or {}) if k.startswith("deep")):
        print("  ", g, "n", (f.get("n") or {}).get(g), "trust", (f.get("trust") or {}).get(g), json.dumps(f["effects"][g]))
