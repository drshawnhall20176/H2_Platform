"""Nov 16: the commercial (customer) sidebar and the Model Record proof page."""
import re
from pathlib import Path
from types import SimpleNamespace as P

import model_record as MR
import nav_layout as NL

SRC = Path(__file__).with_name("streamlit_app.py").read_text()


def test_who_gets_the_commercial_layout():
    assert NL.is_commercial("commercial") and NL.is_commercial("Commercial")
    assert NL.is_commercial("owner", preview=True) and NL.is_commercial(None, preview=True)
    assert not NL.is_commercial("owner") and not NL.is_commercial(None)
    assert not NL.is_commercial("public") and not NL.is_commercial("public", preview=True)   # Discord build unchanged


def test_five_sections_and_no_page_listed_twice():
    assert NL.SECTION_ORDER == (NL.TODAY, NL.GAMES, NL.PLAYERS, NL.RECORD, NL.BETA) and set(NL.LAYOUT) == set(NL.SECTION_ORDER)
    titles = [t for ts in NL.LAYOUT.values() for t in ts]
    assert len(titles) == len(set(titles))
    assert NL.commercial_section("Best Bets") == NL.TODAY and NL.commercial_section("Game Lab") == NL.GAMES
    assert NL.commercial_section("Hot Hand Engine") == NL.PLAYERS and NL.commercial_section("Model Record") == NL.RECORD
    for beta in ("Soccer Lab", "International Hoops", "Tennis Lab"):
        assert NL.commercial_section(beta) == NL.BETA


def test_owner_tools_are_not_part_of_the_product():
    for hidden in ("Bet Log", "My Coach", "Data Health", "Model Performance", "Track Record", "Command Center",
                   "Retrospective", "Postgame Review", "Reports", "Progression Plan", "Edge Board", "Media Room"):
        assert NL.commercial_section(hidden) is None
    owner_only = set(re.findall(r'"([^"]+)"', re.search(r"owner_only_titles = \{(.*?)\}", SRC, re.DOTALL).group(1)))
    assert owner_only and not owner_only & set(NL._SECTION_OF)          # nothing owner-only is ever laid out


def test_every_laid_out_title_is_a_real_page():
    titles = set(re.findall(r'"\d+": \("([^"]+)"', SRC)) | {"Home"}
    assert set(NL._SECTION_OF) <= titles


def test_arrange_orders_sections_and_pages_and_folds_home_into_today():
    got = NL.arrange({NL.OWNER_HOME: [P(title="Home")], NL.PLAYERS: [P(title="QB Lab"), P(title="Matchup Lab")],
                      NL.TODAY: [P(title="Long Shots"), P(title="Best Bets")], NL.BETA: [], NL.RECORD: [P(title="Model Record")]})
    assert list(got) == [NL.TODAY, NL.PLAYERS, NL.RECORD]               # customer order; the empty section dropped
    assert [p.title for p in got[NL.TODAY]] == ["Home", "Best Bets", "Long Shots"]
    assert [p.title for p in got[NL.PLAYERS]] == ["Matchup Lab", "QB Lab"]


def test_the_app_wires_the_layout_and_leaves_the_public_build_alone():
    assert 'if audience == "owner":\n        st.sidebar.toggle("👀 Preview the commercial layout", key=NL.PREVIEW_KEY' in SRC
    assert "sections = NL.arrange(sections)" in SRC
    assert 'NL.commercial_section(title) if commercial else SECTION_OF.get(key' in SRC
    assert '"56": ("Model Record"' in SRC
    assert 'if title == "Model Record" and audience == "public":\n            continue' in SRC


def test_model_record_rows_carry_sample_size_range_and_status():
    props = MR.props_table(["NBA", "NHL", "NFL"], records_for=lambda sp: {
        "NBA": {"🎯 Single": (30, 50), "🎟️ Parlay leg": (4, 10)}, "NHL": {"🎯 Single": (8, 25), "x": (0, 0)}}.get(sp, {}))
    assert [(r["Sport"], r["Pick type"], r["Record"], r["Graded"], r["Status"]) for r in props] == [
        ("NBA", "🎯 Single", "30–20", 50, "Holding up"), ("NBA", "🎟️ Parlay leg", "4–6", 10, "Small sample"),
        ("NHL", "🎯 Single", "8–17", 25, "Losing badly")]
    assert props[0]["Hit rate"] == 0.6 and 0.09 < props[0]["90% range (±)"] < 0.13
    lines = MR.lines_table(["NBA", "NHL"], records_for=lambda lg: {
        "Spread": (24, 50), "Total": (0, 0), "Moneyline": (30, 40), ("Spread", 1): (5, 6)} if lg == "NBA" else {})
    assert [(r["Pick type"], r["Status"]) for r in lines] == [("Spread", "Holding up"), ("Moneyline", "Holding up")]
    assert MR.lines_table(["NBA"], records_for=lambda lg: {"Spread": (23, 50)})[0]["Status"] == "Losing"   # under 47.6%


def test_a_failing_record_source_shows_nothing_rather_than_breaking():
    def boom(_):
        raise RuntimeError("db down")
    assert MR.props_table(["NBA"], records_for=boom) == [] and MR.lines_table(["NBA"], records_for=boom) == []


def test_model_record_page_renders_without_a_database():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("views/56_Model_Record.py", default_timeout=60).run()
    assert not at.exception
    assert any("Model Record" in str(m.value) for m in at.markdown) or at.info
