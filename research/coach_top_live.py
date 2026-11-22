import sys, os, time, resource
sys.path.insert(0, ".")
import slate_store as SS, best_bets_data as BBD
SS._in_app = lambda: True
BBD._in_app = lambda: True
import streamlit as st
st.page_link = lambda *a, **k: None
from streamlit.testing.v1 import AppTest
for pick in ("🌐 All sports", "NBA"):
    t = time.time()
    at = AppTest.from_file("views/51_My_Coach.py", default_timeout=300)
    at.secrets["AUDIENCE"] = "owner"
    for k in ("ODDS_API_KEY", "DATABASE_URL"):
        if os.environ.get(k): at.secrets[k] = os.environ[k]
    at.session_state["coach_top_sport"] = pick
    at.run()
    print(f"CT {pick}: exc={[str(e.value)[:200] for e in at.exception]} t={time.time()-t:.0f}s peak={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e3:.0f}MB")
    for c in at.caption:
        if c.value.startswith("Rules applied"):
            print("CT", c.value)
    for i in at.info:
        print("CT info:", i.value[:150])
    for df in at.dataframe:
        d = df.value
        if "Coach" in d.columns and "Earned chance" in d.columns:
            print("CT", d.drop(columns=["Why", "Game"], errors="ignore").to_string()[:3000])
            break
