"""Home page sport picker: in-season sports only, plus Tennis and International Hoops (Nov 5)."""
from datetime import date
from pathlib import Path

import sports as S


def test_in_season_windows():
    nov5 = date(2026, 11, 5)
    on = {s.key for s in S.selectable_sports(True, nov5)}
    assert {"NFL", "NCAAF", "NBA", "NHL", "NCAAMB", "UFC", "TENNIS", "INTL"} <= on
    assert "MLB" not in on and "WNBA" not in on                # World Series over Oct 28; WNBA ended in October
    assert S.in_season("MLB", date(2026, 7, 1)) and S.in_season("NFL", date(2027, 1, 20))   # wraps the new year
    assert not S.in_season("NCAAMB", date(2026, 7, 1))
    assert {"TENNIS", "INTL", "SOCCER"} <= {s.key for s in S.selectable_sports(False, nov5)}   # Nov 14: labs in both builds
    assert S.default_selectable(True, nov5) == "NFL"           # MLB is out of season -> first in-season sport
    assert S.get("TENNIS").label.startswith("Tennis") and not S.get("TENNIS").has_projections


def test_home_lists_only_selectable_sports_and_labs_open_their_pages():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(Path(__file__).parent / "Home.py"), default_timeout=60)
    at.run()
    # Nov 24: the sports are one multi-select chip row (Select Sport), labelled by their full names
    picker = at.button_group(key="desk_one")                    # Nov 24: one sport by default
    labels = [str(o) for o in picker.options]
    assert any("Tennis" in x for x in labels) and any("International Hoops" in x for x in labels)
    assert not any("coming soon" in x for x in labels)
    for key in [k for k in S.SEASON_WINDOWS if not S.in_season(k)]:
        assert not any(S.REGISTRY[key].label in x for x in labels)


def test_one_sport_by_default_and_several_on_request():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(Path(__file__).parent / "Home.py"), default_timeout=60)
    at.run()
    assert not at.toggle(key="desk_multi").value
    opts = [str(o) for o in at.button_group(key="desk_one").options]
    nba = next(o for o in opts if "NBA" in o)
    at.button_group(key="desk_one").set_value("NBA").run()
    assert at.session_state["sport"] == "NBA" and at.session_state["desk_sports"] == ["NBA"], nba
