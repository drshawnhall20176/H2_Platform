"""research/time_analyst_desk.py — where the Analyst Desk spends its time on a cold open and on a click (Nov 4)."""
import cProfile
import io
import os
import pstats
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def main() -> int:
    from streamlit.testing.v1 import AppTest
    page = str(ROOT / "views" / "39_Analyst_Desk.py")
    at = AppTest.from_file(page, default_timeout=900)
    at.session_state["sport"] = os.environ.get("SPORT", "NBA")
    at.secrets["ODDS_API_KEY"] = os.environ.get("ODDS_API_KEY", "")
    for label in ("cold open", "click (rerun)"):
        pr = cProfile.Profile()
        t = time.time()
        pr.enable()
        at.run()
        pr.disable()
        print(f"\n===== {label}: {time.time() - t:.1f}s  exceptions={[str(e.value)[:200] for e in at.exception]}")
        for key in ("cumulative", "tottime"):
            s = io.StringIO()
            pstats.Stats(pr, stream=s).strip_dirs().sort_stats(key).print_stats(40)
            print(f"--- by {key}")
            print("\n".join(l for l in s.getvalue().splitlines() if l.strip() and not l.startswith(("   Ordered", "   List"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
