import os, runpy
os.environ["SPORT"] = "NFL"
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenario_study.py"), run_name="__main__")
