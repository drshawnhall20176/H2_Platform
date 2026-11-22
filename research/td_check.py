import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(".streamlit", exist_ok=True); open(".streamlit/secrets.toml","w").write('AUDIENCE = "owner"\n')
import streamlit as st
st.page_link = lambda *a, **k: None
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("views/13_Anytime_TD_Engine.py", default_timeout=600)
at.session_state["sport"] = "NFL"
at.run()
print("exceptions:", [e.value[:200] for e in at.exception])
for d in at.dataframe:
    v = d.value
    v = getattr(v, "data", v)
    if "Time" in v.columns: print(v[["Time","Player","Team","Opp"]].head(8).to_string()); break
