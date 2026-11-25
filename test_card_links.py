import card_links as CL


def test_mentioned_finds_players_with_a_line_in_order():
    rows = [{"player": "Jalen Brunson"}, {"player": "Joel Embiid"}, {"player": "Bam Adebayo"}, {"player": "Jalen Brunson"}]
    names, games = CL.mentioned("Joel Embiid looks good tonight; Jalen Brunson's assists too.", rows,
                                ["Knicks @ Celtics", None])
    assert names == ["Joel Embiid", "Jalen Brunson"] and games == ["Knicks @ Celtics"]
    assert CL.mentioned("nothing here", rows, [])[0] == []


def test_a_table_row_opens_its_card_once():
    from streamlit.testing.v1 import AppTest

    def app():
        import pandas as pd
        import streamlit as st
        import card_links as CL
        opened = st.session_state.setdefault("opened", [])
        CL.table(pd.DataFrame([{"Player": "A"}, {"Player": "B"}]), key="t", items=["a", "b"],
                 open_fn=lambda x: opened.append(x))
    at = AppTest.from_function(app, default_timeout=30)
    at.run()
    assert not at.exception and at.session_state["opened"] == []
    at.session_state["t__open"] = 1
    at.run()
    assert at.session_state["opened"] == ["b"]
    at.run()
    assert at.session_state["opened"] == ["b"]                             # not again on the next rerun


def test_game_row_matches_abbreviations(monkeypatch):
    import todays_best as TB
    w = {"game": "New York Jets @ Miami Dolphins", "_full": {"home": "Miami Dolphins", "away": "New York Jets"}}
    monkeypatch.setattr(TB, "winner_rows", lambda day, leagues=None, past=False: [w])
    assert CL.game_row({"game": "NYJ @ MIA", "date": "2026-11-29"}, "NFL") is w
    assert CL.game_row({"game": "New York Jets @ Miami Dolphins"}, "NFL") is w
    assert CL.game_row({"game": "BUF @ KC"}, "NFL") is None


SCAN = {"rows": [{"Player": "Cam Spencer", "Bet": "10+ Assists", "Market": "Assists", "Price": 650, "Honest chance": 0.17,
                  "Book says": 0.13, "tested": True, "game": "LAC @ MEM", "pick": "Cam Spencer 10+ Assists"},
                 {"Player": "Other Guy", "Bet": "40+ Points", "Market": "Points", "Price": 900, "Honest chance": 0.12,
                  "tested": False}]}


def test_scan_rows_keep_their_names_for_the_card():
    import long_shots_scan as LSS
    raw = LSS.sorted_rows(SCAN)
    assert raw[0]["Player"] == "Cam Spencer" and LSS.all_rows(SCAN)[0]["Pick"] == "Cam Spencer 10+ Assists"


def test_long_shot_marks_and_strip(monkeypatch):
    import today_visual as TV
    import long_shots_scan as LSS
    monkeypatch.setattr(TV, "_long_shots_cached", lambda sport, day: LSS.sorted_rows(SCAN))
    assert TV.ls_mark("NBA", "Cam Spencer") == "💎 " and TV.ls_mark("NBA", "Nobody") == ""
    assert [r["Bet"] for r in TV.long_shots_for("NBA", "cam spencer")] == ["10+ Assists"]
    from streamlit.testing.v1 import AppTest

    def app():
        import player_card as PC
        PC.long_shot_strip({"Player": "Cam Spencer"}, "NBA", rows=[{"Bet": "10+ Assists", "Price": 650,
                                                                   "Honest chance": 0.17, "Book says": 0.13,
                                                                   "tested": True}])
    at = AppTest.from_function(app, default_timeout=30)
    at.run()
    md = " ".join(m.value for m in at.markdown)
    assert "10+ Assists" in md and "+650" in md and "honest 17%" in md and "tested" in md
