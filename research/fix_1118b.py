import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, betlog as B, calibration as CAL
B.update_bet(759, result="void", notes="Grayson Allen ruled Out (DNP) -- void, stake returned")
print("BET", [ {k: x.get(k) for k in ("id","result","stake")} for x in B.list_bets() if x.get("id")==759])
ok = MS.approve_calibration("NBA:trust", 0.54, {"auto": False, "morning": "2026-11-18", "was": 0.46, "kind": "props",
     "why": "owner-approved revert: the Nov 18 cut had flat log loss (0.6872) and held out on 1 of 13 splits"})
print("TRUST", ok, CAL.trust("NBA"))
