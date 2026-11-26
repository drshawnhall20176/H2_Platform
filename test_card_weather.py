"""Nov 26: football game cards say what the weather does to the props."""
import football_weather as FW


def test_impact_text_names_the_moved_markets():
    wx = {"wind": 17, "temp": 36, "indoor": False, "code": 63}
    t = FW.impact_text(wx)
    assert t.startswith("Weather effect on props: pass yards -9%") and "rush yards +5%" in t
    assert "already in the projections" in t
    assert "(measured on NFL games)" in FW.impact_text(wx, "NCAAF")


def test_impact_text_quiet_when_nothing_moves():
    assert FW.impact_text({"indoor": True}) == ""
    assert FW.impact_text({"wind": 5, "temp": 60}) == ""
    assert FW.impact_text(None) == ""
