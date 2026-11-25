import todays_best as TB


def test_move_cell_is_a_short_arrow_with_the_points():
    assert TB.move_cell({"spread_move": "📈 our way", "spread_move_why": "Yale Bulldogs +7 → +6"}) == "🟢 ▲ 1 pt"
    assert TB.move_cell({"spread_move": "📉 against", "spread_move_why": "Lindenwood Lions +9 → +10.5"}) == "🔴 ▼ 1.5 pts"
    assert TB.move_cell({"spread_move": "📈 our way"}) == "🟢 ▲"
    assert TB.move_cell({}) == "" and TB.move_detail({}) == ""
    assert TB.move_detail({"spread_move_why": "Duke -5 → -7"}) == "Duke -5 → -7"


def test_spread_move_feeds_the_cell():
    mv = TB.spread_move({"open_line": 5, "line": 7, "model_margin": 9, "home": "Duke", "away": "X"}, "NCAAMB")
    assert TB.move_cell(mv) == "🟢 ▲ 2 pts" and TB.move_detail(mv) == "Duke -5 → -7"
