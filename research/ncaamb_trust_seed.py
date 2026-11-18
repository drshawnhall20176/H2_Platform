"""Nov 18: college basketball props start on the NBA's measured trust (0.54) instead of 1.0 (the model as is) until
their own graded reads say otherwise -- the NBA props model ran overconfident by exactly this much."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, calibration as CAL
ok = MS.approve_calibration("NCAAMB:trust", 0.54, {"auto": False, "morning": "2026-11-18", "was": 1.0, "kind": "props",
     "why": "seeded from the NBA's measured trust: same props model, no college graded reads yet"})
print("SEED", ok)
