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
    assert NL.is_commercial("public") and NL.is_commercial("public", preview=True)   # Nov 25: the Discord build is live


def test_four_sections_plain_names_and_no_page_listed_twice():
    assert NL.SECTION_ORDER == (NL.TODAY, NL.RESEARCH, NL.RECORD, NL.BETA) and set(NL.LAYOUT) == set(NL.SECTION_ORDER)
    titles = [t for pairs in NL.LAYOUT.values() for t, _ in pairs]
    labels = [lb for pairs in NL.LAYOUT.values() for _, lb in pairs]
    assert len(titles) == len(set(titles)) and len(labels) == len(set(labels))
    assert NL.commercial_section("Today") == NL.TODAY and NL.commercial_section("Best Bets") == NL.TODAY
    assert NL.commercial_section("Game Lab") == NL.RESEARCH and NL.commercial_section("Players") == NL.RESEARCH
    assert NL.commercial_section("Model Record") == NL.RECORD
    assert (NL.label("Game Lab"), NL.label("Best Bets"), NL.label("Model Record"), NL.label("Analyst Desk")) == (
        "Games", "All picks", "Track record", "Daily write-up")
    assert NL.label("Something Else") == "Something Else"
    for beta in ("Soccer Lab", "International Hoops", "Tennis Lab"):
        assert NL.commercial_section(beta) == NL.BETA


def test_owner_tools_and_the_separate_player_tools_are_not_in_the_customer_sidebar():
    for hidden in ("Bet Log", "My Coach", "Data Health", "Model Performance", "Track Record", "Command Center",
                   "Retrospective", "Postgame Review", "Reports", "Progression Plan", "Edge Board", "Media Room",
                   "Home", "Hot Hand Engine", "Matchup Lab", "Position Matchups", "QB Lab", "Anytime TD Engine"):
        assert NL.commercial_section(hidden) is None
    owner_only = set(re.findall(r'"([^"]+)"', re.search(r"owner_only_titles = \{(.*?)\}", SRC, re.DOTALL).group(1)))
    assert owner_only and not owner_only & set(NL._SECTION_OF)          # nothing owner-only is ever laid out


def test_every_laid_out_title_is_a_real_page():
    titles = set(re.findall(r'"\d+": \("([^"]+)"', SRC))
    assert set(NL._SECTION_OF) <= titles and set(NL.COMMERCIAL_ONLY) <= titles


def test_arrange_orders_sections_and_pages_and_today_replaces_home():
    got = NL.arrange({NL.OWNER_HOME: [P(title="Home")], NL.RESEARCH: [P(title="Players"), P(title="Games")],
                      NL.TODAY: [P(title="Long shots"), P(title="All picks"), P(title="Today")], NL.BETA: [],
                      NL.RECORD: [P(title="Track record")]})
    assert list(got) == [NL.TODAY, NL.RESEARCH, NL.RECORD]               # customer order; the empty section dropped
    assert [p.title for p in got[NL.TODAY]] == ["Today", "All picks", "Long shots"]     # no Home
    assert [p.title for p in got[NL.RESEARCH]] == ["Games", "Players"]


def test_the_app_wires_the_layout_and_leaves_the_owner_and_public_builds_alone():
    assert 'if audience == "owner":\n        st.session_state.setdefault(NL.PREVIEW_KEY, True)' in SRC
    assert 'st.sidebar.toggle("👀 Customer layout", key=NL.PREVIEW_KEY' in SRC
    assert "sections = NL.arrange(sections)" in SRC
    assert 'NL.commercial_section(title) if commercial else SECTION_OF.get(key' in SRC
    assert 'if title in NL.COMMERCIAL_ONLY and not commercial:\n            continue' in SRC
    assert 'if title == "Model Record" and audience == "public" and not commercial:\n            continue' in SRC
    assert "title=NL.label(title) if commercial else title" in SRC


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


def test_sidebar_controls_in_the_owners_order():
    # Nov 25 (owner): Sport, My sportsbook, My pick'em app, Layout, then the public-build note
    # Nov 27: the Sport picker's place is held by a container (drawn once the page is known)
    i = [SRC.index(x) for x in ("_sport_slot = st.sidebar.container()", "MB.sidebar()", '"📱 Layout"',
                                "🌐 Public build")]
    assert i == sorted(i)
    import my_books as MB
    import inspect
    src = inspect.getsource(MB.sidebar)
    assert src.index("sportsbook") < src.index("pick'em")



def test_the_office_sidebar_has_sport_at_the_top_too():
    # Nov 27 (owner): the Test list's sidebar had Sport at the bottom; one order on every page
    assert "_office_slot" not in SRC and SRC.count("slot=_sport_slot") >= 4      # customer, Office, classic x2
    assert "sports.render_sport_selector()" not in SRC                            # no read-only label anywhere
