import players_cards as PCD
import player_context as PCX


ROWS = [{"player": "Jalen Brunson", "team": "NYK", "game": "Knicks @ Celtics", "time": "7:30 PM", "market": "Points",
         "side": "Over", "line": 27.5, "chance": 0.58},
        {"player": "Jaylen Brown", "team": "BOS", "game": "Knicks @ Celtics", "time": "7:30 PM", "market": "Points",
         "side": "Under", "line": 25.5, "chance": 0.55},
        {"player": "Bam Adebayo", "team": "MIA", "game": "Heat @ 76ers", "time": "5:10 PM", "market": "Rebounds",
         "side": "Over", "line": 9.5, "chance": 0.52}]


def test_players_grouped_by_game_in_start_order():
    got = PCD.by_game(ROWS)
    assert [g for g, _, _ in got] == ["Heat @ 76ers", "Knicks @ Celtics"]
    assert set(got[1][2]) == {"NYK", "BOS"}


def test_context_stat_keys_and_head_to_head():
    assert PCX.stat_key("Points") == "pts" and PCX.stat_key("Pts+Reb+Ast") == "pra" and PCX.stat_key("Saves") is None
    log = [{"pts": 30, "reb": 5, "ast": 7, "date": "2026-11-02T00:00Z", "min": 36},
           {"pts": 22, "reb": 3, "ast": 9, "date": "2026-10-20T00:00Z", "min": 33}]
    rows = PCX.h2h_rows(log, "pts", 27.5, "Over")
    assert [(r["value"], r["hit"]) for r in rows] == [(30.0, True), (22.0, False)] and rows[0]["date"] == "2026-11-02"
    assert [r["value"] for r in PCX.h2h_rows(log, "pra", None, "Over")] == [42.0, 34.0]
    assert PCX.rest_text("Knicks", {"rest_days": 1, "is_back_to_back": True}).endswith("back-to-back (played yesterday)")
    assert PCX.rest_text("Knicks", {"rest_days": 2}) == "Knicks: 2 days since their last game"
    assert PCX.rest_text("Knicks", None) == "Knicks: rest unknown"


def test_context_renders_with_the_engines_numbers(monkeypatch):
    from streamlit.testing.v1 import AppTest

    def app():
        import player_context as PCX
        PCX.load = lambda *a, **k: ([{"pts": 30, "date": "2026-11-02"}], {"Last 5": {"pts": 118.2}, "Last 10": {"pts": 115.0}},
                                    ({"rest_days": 1, "is_back_to_back": True}, {"rest_days": 2}))
        PCX.render({"PlayerId": 1, "_team_id": 2, "_opp_id": 3, "Market": "Points", "Line": 27.5, "Side": "Over",
                    "Opp": "Celtics", "Team": "Knicks"}, "NBA", "2026-11-25")
    at = AppTest.from_function(app, default_timeout=30)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    md = " ".join(m.value for m in at.markdown)
    assert "Against Celtics this season" in md and "118.2" in md
    assert any("back-to-back" in c.value for c in at.caption)


def test_players_page_opens_on_cards(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import today_visual as TV
    monkeypatch.setattr(TV, "all_props", lambda sport, day=None: ROWS)
    at = AppTest.from_file("views/58_Players.py", default_timeout=60)
    at.session_state["sport"] = "NBA"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.segmented_control(key="view_players").value == "Cards"
    assert any("Jalen Brunson" in b.label for b in at.button)
    at.segmented_control(key="view_players").set_value("Table").run()
    assert not any("Jalen Brunson" in b.label for b in at.button)
