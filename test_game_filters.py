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


def test_team_select_lists_the_teams_playing_and_filters_to_one(monkeypatch):
    # Nov 16: the Find-a-team dropdown every Game Lab shares
    import components as C
    import streamlit as st
    games = [{"home": "Duke", "away": "Army"}, {"home": "Kansas", "away": "duke state"}, {"home": "Army", "away": "Navy"}]
    assert C.team_names(games) == ["Army", "Duke", "duke state", "Kansas", "Navy"]
    seen = {}

    def fake_selectbox(title, options, key=None, help=None, **k):
        seen.update(title=title, options=options)
        return seen.get("pick", C.ALL_TEAMS)
    monkeypatch.setattr(st, "selectbox", fake_selectbox)
    assert C.team_select(games, key="t") == games and seen["title"] == "Find a team"
    assert seen["options"] == ["All teams", "Army", "Duke", "duke state", "Kansas", "Navy"]
    seen["pick"] = "Army"
    assert C.team_select(games, key="t") == [games[0], games[2]]
    seen["pick"] = "Duke"
    assert C.team_select(games, key="t") == [games[0]]                 # an exact team, not every name containing it
    nfl = [{"home_name": "BAL", "away_name": "LAC"}, {"home_name": "KC", "away_name": "BUF"}]
    seen["pick"] = "KC"
    assert C.team_select(nfl, key="n", home=lambda m: m["home_name"], away=lambda m: m["away_name"]) == [nfl[1]]
    seen["pick"] = C.ALL_TEAMS
    C.team_select(games[:1], key="t2", options=["Army", "Duke", "Navy"])
    assert seen["options"] == ["All teams", "Army", "Duke", "Navy"]    # the full list survives another filter


def test_every_game_lab_has_the_find_a_team_dropdown():
    from pathlib import Path
    root = Path(__file__).parent
    assert 'C.team_select(on_day, key=f"hg_team_{league}"' in (root / "hoops_games_page.py").read_text()   # NBA, NHL, college hoops, international
    assert "st.text_input(\"Find a team\"" not in (root / "hoops_games_page.py").read_text()
    assert 'C.team_select(_up, key="ncaaf_v2_team"' in (root / "views" / "32_NCAAF_Game_Lab.py").read_text()
    assert 'C.team_select(slot_meta, key="gl_team"' in (root / "views" / "34_NFL_Game_Lab.py").read_text()
