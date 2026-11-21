import sys, json
sys.path.insert(0, ".")
import model_store as MS
for k in ("picks", "morning"):
    b = MS.get_setting(f"brief:2026-11-21:{k}")
    print("BR", k, type(b).__name__, (list(b.keys()) if isinstance(b, dict) else str(b)[:200]), (len(b.get("text") or "") if isinstance(b, dict) else None), (len(b.get("table") or []) if isinstance(b, dict) else None))
