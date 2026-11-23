"""table_style (Nov 23): every table's columns centered, a page's own settings kept."""
import pandas as pd

import table_style as TS


def test_every_column_is_centered_and_page_settings_are_kept():
    df = pd.DataFrame([{"Game": "A @ B", "Chance": 0.6, "Hidden": 1, "Named": 2, "Right": 3}])
    cfg = TS.centered(df, {"Chance": {"type_config": {"format": "percent"}}, "Hidden": None, "Named": "Nice name",
                           "Right": {"alignment": "right"}})
    assert cfg["Game"] == {"alignment": "center"}
    assert cfg["Chance"]["alignment"] == "center" and cfg["Chance"]["type_config"] == {"format": "percent"}
    assert cfg["Hidden"] is None and cfg["Named"] == {"label": "Nice name", "alignment": "center"}
    assert cfg["Right"]["alignment"] == "right"
    assert TS.centered([1, 2], None) is None


def test_installed_tables_render_centered():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string("""
import table_style as TS, streamlit as st, pandas as pd
TS.install()
st.dataframe(pd.DataFrame([{"Game": "A @ B", "Chance": 0.6}]),
             column_config={"Chance": st.column_config.NumberColumn(format="percent")})
c1, c2 = st.columns(2)
c1.data_editor(pd.DataFrame([{"x": 1}]), key="e")
""")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    protos = [d.proto for d in at.dataframe]
    assert all('"alignment": "center"' in p.columns or '"alignment":"center"' in p.columns for p in protos), \
        [p.columns for p in protos]
