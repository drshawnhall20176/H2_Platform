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
    assert "TENNIS" not in {s.key for s in S.selectable_sports(False, nov5)}    # labs are owner-only
    assert S.default_selectable(True, nov5) == "NFL"           # MLB is out of season -> first in-season sport
    assert S.get("TENNIS").label.startswith("Tennis") and not S.get("TENNIS").has_projections


def test_home_lists_only_selectable_sports_and_labs_open_their_pages():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(Path(__file__).parent / "Home.py"), default_timeout=60)
    at.run()
    labels = [b.label for b in at.button]
    assert any("Tennis" in x for x in labels) and any("International Hoops" in x for x in labels)
    assert not any("coming soon" in x for x in labels)
    for key in [k for k in S.SEASON_WINDOWS if not S.in_season(k)]:
        assert not any(S.REGISTRY[key].label in x for x in labels)
