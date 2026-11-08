import os, runpy
os.environ["SPORT"] = "NBA"
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "teammate_out_study.py"), run_name="__main__")
