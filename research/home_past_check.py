"""Nov 19: render Home (Today's best) for yesterday, NBA, against the real store -- every table's columns and how
many rows carry a result (owner: no result column on yesterday's page; blowout watch shows one result)."""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(".streamlit", exist_ok=True)
open(".streamlit/secrets.toml", "w").write('AUDIENCE = "owner"\n')
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("Home.py", default_timeout=600)
at.session_state["sport"] = os.environ.get("SP", "NCAAMB")
at.session_state["home_best_date"] = datetime.date(2026, 11, 18)
if len(sys.argv) > 1 or os.environ.get("ALLP"):
    at.session_state["home_best_show"] = "All playable"
at.run()
print("HP exceptions", [str(e.value)[:300] for e in at.exception])
for m in at.markdown:
    if m.value.startswith("#####") or m.value.startswith("####"):
        print("HP section", m.value[:80])
for i, d in enumerate(at.dataframe):
    df = d.value
    try:
        cols = list(df.columns)
    except Exception:
        cols = "?"
    print("HP table", i, len(df), cols)
    for c in cols:
        if c in ("Result", "Hit", "What happened", "Pick result", "Winner result", "Final", "Actual"):
            vals = df[c].astype(str).value_counts().to_dict()
            print("HP   ", c, dict(list(vals.items())[:8]))
at.session_state["home_best_show"] = "All playable"
at.run()
for i, d in enumerate(at.dataframe):
    df = d.value
    print("HP2 table", i, len(df), list(df.columns)[-3:])
    if "Result" in df.columns:
        print("HP2   Result", df["Result"].astype(str).value_counts().to_dict())
for r in at.radio:
    print("HP radio", r.key, r.value, r.options)
