"""Nov 26: Today says why it has no player picks."""
import customer_today as CT


def test_empty_reason_names_the_dark_sports_and_the_reads():
    t = CT.empty_reason(["NBA", "NHL"], {"NFL": 235, "NCAAMB": 330, "NCAAF": 20})
    assert t.startswith("No pick clears the bar today: NBA and NHL have no games today; the model read 585 NCAAF, "
                        "NCAAMB and NFL props, and none earned a bet")
    assert "Test list" in t


def test_empty_reason_before_any_build():
    assert "haven't been built yet" in CT.empty_reason([], {})
    assert CT.empty_reason(["NHL"], {}).startswith("No pick clears the bar today: NHL has no games today.")
