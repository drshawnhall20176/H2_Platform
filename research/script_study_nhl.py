import os, runpy
os.environ["SPORT"] = "NHL"
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "script_study.py"), run_name="__main__")
