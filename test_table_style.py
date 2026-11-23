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


def test_phone_detection():
    assert TS.is_phone("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile/15E148 Safari")
    assert TS.is_phone("Mozilla/5.0 (Linux; Android 14; Pixel 8) Mobile Safari/537.36")
    assert not TS.is_phone("Mozilla/5.0 (Linux; Android 14; SM-X710) Safari/537.36")          # Android tablet
    assert not TS.is_phone("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15")
    assert not TS.is_phone("")


def test_cards_put_time_and_game_on_top_and_the_left_columns_first():
    df = pd.DataFrame([{"Time": "7:00 PM", "Game": "A @ <B>", "Blowout risk (15+ pts)": "🟥 71%", "Chance": 0.613,
                        "Empty": "—", "✓ Tick": False, "Hidden": "x"}])
    h = TS.cards_html(df, {"Chance": {"type_config": {"format": "percent"}}, "Hidden": None})
    assert "<span>7:00 PM</span>A @ &lt;B&gt;" in h and "🟥 71%" in h and "61%" in h
    assert "Empty" not in h and "✓ Tick" not in h and "Hidden" not in h
    assert h.index("Blowout risk") < h.index("Chance")


def test_a_phone_gets_cards_and_the_full_table_one_tap_away():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string("""
import table_style as TS, streamlit as st, pandas as pd
TS.install(); TS.install_phone()
df = pd.DataFrame([{"Time": "7:00 PM", "Game": f"A{i} @ B{i}", "x": 1, "y": 2, "z": 3, "w": 4} for i in range(3)])
st.dataframe(df)
st.dataframe(df[["Time", "Game"]])                      # narrow: stays a table
ev = st.dataframe(df, on_select="rerun", key="sel")     # a selection table stays a table
""")
    at.session_state[TS.LAYOUT_KEY] = "Phone"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("h2c-t" in m.value for m in at.markdown)
    assert len(at.dataframe) == 3                           # the full table inside the expander, plus the two kept
    assert any("Full table (3 rows" in e.label for e in at.expander)
    at.session_state[TS.LAYOUT_KEY] = "Full"
    at.run()
    assert not any("h2c-t" in m.value for m in at.markdown) and len(at.dataframe) == 3
