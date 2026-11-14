import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import long_shots_scan as L
for k, v in L.run(force=True).items():
    print("SCAN", k, v)
