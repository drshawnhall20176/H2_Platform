import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
for sp in ("NBA", "NCAAMB"):
    f = MS.get_setting(f"script_learn:{sp}", {}) or {}
    print("MIN", sp, f.get("fit_at"), json.dumps(f.get("minutes")))
