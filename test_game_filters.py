import components as C


def test_by_kickoff_earliest_first_and_unknown_last():
    items = [{"kickoff": "2026-11-08T01:00:00Z"}, {"kickoff": None}, {"kickoff": "2026-11-07T17:00:00Z"}]
    out = C.by_kickoff(items)
    assert [i["kickoff"] for i in out] == ["2026-11-07T17:00:00Z", "2026-11-08T01:00:00Z", None]


def test_kick_dt_is_eastern():
    assert C._kick_dt("2026-11-08T01:00:00Z").hour == 20
    assert C._kick_dt("junk") is None


def test_game_lab_pages_run():
    from streamlit.testing.v1 import AppTest
    for f in ("views/32_NCAAF_Game_Lab.py", "views/43_Tennis_Lab.py", "views/45_NCAAMB_Game_Lab.py",
              "views/46_NBA_Game_Lab.py", "views/47_NHL_Game_Lab.py"):
        at = AppTest.from_file(f, default_timeout=90)
        at.run()
        assert not at.exception, (f, [e.value for e in at.exception])
