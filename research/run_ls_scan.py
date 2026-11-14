import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import long_shots_scan as LSS
for k, v in LSS.run(force=True).items():
    print("SCAN", k, v)
