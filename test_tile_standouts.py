"""Nov 26: each side's top read on the game tiles."""
import today_visual as TV


def test_standouts_best_earned_chance_per_team_skipping_no_edge():
    props = [{"kind": "Prop", "player": "Jahmyr Gibbs", "team": "DET", "market": "Rushing Yards", "side": "Over",
              "line": 69.5, "earned": 0.61, "use": "🎯 Single only"},
             {"kind": "Prop", "player": "Sam LaPorta", "team": "DET", "market": "Receptions", "side": "Over",
              "line": 3.5, "earned": 0.66, "use": "⚪ No edge"},
             {"kind": "Prop", "player": "D'Andre Swift", "team": "CHI", "market": "Rushing Yards", "side": "Under",
              "line": 55.5, "chance": 0.58, "use": "🎟️ Parlay + Single"},
             {"kind": "Game", "player": None, "team": "CHI"}]
    got = TV.standouts(props)
    assert [(x["team"], x["text"]) for x in got] == [("DET", "Gibbs Rush Yds O 69.5"), ("CHI", "Swift Rush Yds U 55.5")]
    html = TV.game_tile_html({"game": "Chicago Bears @ Detroit Lions", "sport": "NFL", "time": "1:00 PM"}, props)
    assert "Gibbs Rush Yds O 69.5" in html and "61%" in html


def test_tile_without_props_is_unchanged():
    w = {"game": "A @ B", "sport": "NBA", "time": "7:00 PM"}
    assert TV.game_tile_html(w) == TV.game_tile_html(w, [])
    assert "⭐" not in TV.game_tile_html(w)
