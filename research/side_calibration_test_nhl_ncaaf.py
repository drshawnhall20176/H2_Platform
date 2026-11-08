import os, runpy
os.environ["AUDIT_SPORTS"] = "NHL,NCAAF"
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "side_calibration_test.py"), run_name="__main__")
