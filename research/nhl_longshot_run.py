import os, runpy, sys
os.environ.update(LEAGUE="NHL", START="2026-10-25", END="2026-11-13", FLOOR="70000")
sys.argv = ["longshot_backtest.py"]
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "longshot_backtest.py"), run_name="__main__")
