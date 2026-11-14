import os, runpy, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
d = [x for x in MS.snapshot_dates("NCAAF") if "2026-09-01" <= x <= "2026-11-13"]
print("NCAAF snapshot dates", d)
for x in d:
    s = MS.load_snapshots("NCAAF", [x])
    print("  ", x, len(s), "reads", len({r["game"] for r in s}), "games")
os.environ.update(LEAGUE="NCAAF", START="2026-10-01", END="2026-11-13", FLOOR="70000")
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "longshot_backtest.py"), run_name="__main__")
