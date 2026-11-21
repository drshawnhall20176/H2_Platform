import sys, json
sys.path.insert(0, ".")
import shutoff as SO, bankroll_sim as BS
SO.refit()
rec = BS.load()
print("BSX", json.dumps({k: v for k, v in (rec or {}).items()}, default=str))
