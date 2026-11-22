import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(".streamlit", exist_ok=True); open(".streamlit/secrets.toml","w").write('AUDIENCE = "owner"\n')
import streamlit as st
st.page_link = lambda *a, **k: None
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("views/45_NCAAMB_Game_Lab.py", default_timeout=600)
at.session_state["sport"] = "NCAAMB"
at.run()
print("exceptions:", [e.value[:200] for e in at.exception])
import pandas as pd
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 40)
for d in list(at.dataframe):
    v = d.value
    if "Leans" in v.columns:
        cols = [c for c in ["Game","Use","Model has","Book has","Leans","Book spread","Book total","Book ML"] if c in v.columns]
        print(v[cols].head(8).to_string())
