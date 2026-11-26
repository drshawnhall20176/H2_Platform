"""Nov 26: the soccer card's goals line from the model's expected goals."""
import game_card as GC


def test_soccer_goals_poisson():
    g = GC.soccer_goals({"home": 1.8, "away": 1.4})
    assert round(g["total"], 1) == 3.2
    assert 0.61 < g["o25"] < 0.63                           # 1.8 + 1.4 goals expected -> about 62% over 2.5
    assert g["o15"] > g["o25"] > g["o35"]
    assert 0.60 < g["btts"] < 0.66
    assert GC.soccer_goals(None) is None and GC.soccer_goals({"home": "x", "away": 1}) is None


def test_soccer_card_shows_the_goals_line():
    html = GC.soccer_html({"label": "MLS", "home": "Columbus Crew", "away": "Inter Miami", "xg": {"home": 1.8, "away": 1.4},
                           "results": []})
    assert "3.2 goals expected" in html and "Over 2.5" in html and "Both teams score" in html
