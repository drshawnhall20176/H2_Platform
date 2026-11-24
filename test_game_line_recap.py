import game_line_recap as GLR


def _rows():
    return [
        {"game": "A @ B", "final": "A 60 – B 70", "money": True, "money_pick": "B -3.5", "money_price": -110,
         "money_result": "win", "best": "B -3.5", "best_price": -110, "best_result": "win",
         "winner": "B", "price": -150, "winner_result": "win",
         "_full": {"home": "B", "away": "A", "home_spread": -3.5, "model_margin": 4.0}},
        {"game": "C @ D", "final": "C 80 – D 70", "best": "D -9.5", "best_price": -110, "best_result": "loss",
         "winner": "D", "price": -400, "winner_result": "loss",
         "_full": {"home": "D", "away": "C", "home_spread": -9.5, "model_margin": 3.0}},
    ]


def test_grade_day_groups_money_agree_pick_and_winner():
    g = GLR.grade_day("NCAAMB", "2026-11-23", rows=_rows())
    assert (g["money"]["w"], g["money"]["l"]) == (1, 0)
    assert (g["agree"]["w"], g["agree"]["l"]) == (1, 0)        # only the within-2-points game
    assert (g["pick"]["w"], g["pick"]["l"]) == (1, 1)
    assert (g["winner"]["w"], g["winner"]["l"]) == (1, 1)
    assert round(g["winner"]["units"], 2) == round(100 / 150 - 1, 2)


def test_recap_waits_for_finals_and_reads_plainly():
    rows = _rows()
    txt = GLR.recap_text("NCAAMB", "2026-11-23", grade=lambda lg, d: GLR.grade_day(lg, d, rows=rows))
    assert "game lines recap" in txt and "💰 Money picks 1–0" in txt and "Pick column 1–1" in txt
    rows2 = _rows() + [dict(_rows()[1], final=None), dict(_rows()[1], final=None)]
    assert GLR.recap_text("NCAAMB", "2026-11-23", grade=lambda lg, d: GLR.grade_day(lg, d, rows=rows2)) == ""


def test_window_totals_the_days():
    rows = _rows()
    w = GLR.window("NCAAMB", "2026-11-23", days=3, grade=lambda lg, d: GLR.grade_day(lg, d, rows=rows))
    assert len(w) == 4 and w[-1]["Date"] == "Last 3 days" and w[-1]["Pick column"].startswith("3–3")

