import os, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
for d in ("2026-11-01", "2026-11-08", "2026-11-15"):
    print("MK", d, dict(Counter(s.get("market") for s in MS.load_snapshots("NFL", [d]))))
