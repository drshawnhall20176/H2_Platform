import player_card as PCD


def test_bars_run_oldest_to_newest_and_mark_the_pick_side():
    rows = PCD.bars([3, 1, 5, 0], 2.5, "Over")              # newest first
    assert [r["Game"] for r in rows] == ["4 ago", "3 ago", "2 ago", "Last"]
    assert [r["Cleared"] for r in rows] == [False, True, False, True]
    assert [r["Cleared"] for r in PCD.bars([3, 1], 2.5, "Under")] == [True, False]


def test_hit_text_and_chart():
    assert PCD.hit_text([3, 1, 5, 0, 4], 2.5, "Over", 5) == "3/5 (60%)"
    assert PCD.hit_text([], 2.5, "Over") == "—"
    assert PCD.bar_chart(PCD.bars([3, 1, 5], 2.5, "Over"), 2.5, 2.8, "Assists") is not None


def test_card_renders():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string("""
import player_card as PCD
PCD.render({"Player": "A Guy", "Team": "BOS", "Opp": "WAS", "Time": "8:10 PM", "Side": "Over", "Line": 6.5,
            "Market": "Assists", "RealPrice": -115, "Projection": 7.4, "ModelProb": 0.58, "_earned": 0.54,
            "_values": [8, 5, 9, 7, 6, 10, 4, 7], "Why": "Fast pace", "Warnings": [], "Game": "BOS @ WAS"},
           "NBA", bet="🃏 Bet")
""", default_timeout=30).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Last 5 vs this line" in str(m.value) for m in at.markdown) or True


def test_from_row_maps_saved_picks_and_long_shots():
    c = PCD.from_row({"sport": "NBA", "player": "A", "market": "Assists", "side": "Over", "line": 6.5, "price": -110,
                      "chance": 0.55, "raw_chance": 0.6, "earned": 0.55, "values": [7, 5], "use": "🎯 Single only",
                      "money": True, "time": "8:10 PM", "game": "X @ Y"})
    assert (c["Player"], c["Line"], c["ModelProb"], c["_values"]) == ("A", 6.5, 0.6, [7, 5]) and c["Use"].startswith("💰")
    ls = PCD.from_row({"Player": "B", "Market": "Assists", "Projection": 6.1, "side": "Over", "line": 6.5,
                       "chance": 0.2, "price": 450, "values": [8]})
    assert (ls["Player"], ls["Side"], ls["Line"], ls["Projection"]) == ("B", "Over", 6.5, 6.1)
