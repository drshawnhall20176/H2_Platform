import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
st.page_link = lambda *a, **k: None
st.switch_page = lambda *a, **k: None
from streamlit.testing.v1 import AppTest
for page in ("views/21_Media_Room.py", "views/22_Podcast_Studio.py"):
    for sp in ("NBA", "NFL", "NCAAMB"):
        at = AppTest.from_file(page, default_timeout=300)
        at.session_state["sport"] = sp
        at.run()
        print("=====", page, sp, "exceptions:", [e.value[:200] for e in at.exception])
        codes = [c.value for c in at.code]
        txt = "\n".join(codes)
        print(txt[:1800] if txt else "(no copy block)")
        print("captions:", [c.value[:160] for c in at.caption][:4])
