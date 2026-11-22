import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(".streamlit", exist_ok=True); open(".streamlit/secrets.toml","w").write('AUDIENCE = "owner"\n')
import streamlit as st
st.page_link = lambda *a, **k: None
from streamlit.testing.v1 import AppTest
for sp in ("NBA", "NCAAMB", "NFL"):
    at = AppTest.from_file("views/0_#L01f3c6_Command_Center.py", default_timeout=600)
    at.session_state["sport"] = sp
    at.run()
    dfs = [d.value for d in at.dataframe]
    hit = [d for d in dfs if "Pick" in getattr(d, "columns", []) and "Best price" in d.columns]
    print("=====", sp, "exceptions:", [e.value[:200] for e in at.exception])
    if hit: print(hit[0][["Time","Sport","Pick","Chance","Best price"]].to_string()[:1500])
    else: print("no strongest table;", [i.value[:120] for i in at.info])
