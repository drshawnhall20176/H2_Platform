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
        s = io.StringIO()
        st = pstats.Stats(pr, stream=s).sort_stats("cumulative")
        st.print_stats(45)
        out = [l for l in s.getvalue().splitlines() if "/h2_platform/" in l or "{method 'recv" in l or "ssl" in l.lower()
               or "psycopg" in l]
        print("\n".join(out[:45]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
