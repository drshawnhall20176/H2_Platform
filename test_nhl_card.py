import nhl_card as NC


def _team(ha, abbr, name, goalie=None, status="expected", recs=("15-7-1", "9-4-0", "6-3-1")):
    t = {"homeAway": ha, "team": {"abbreviation": abbr, "displayName": name},
         "records": [{"name": "overall", "summary": recs[0]}, {"name": "Home", "summary": recs[1]},
                     {"name": "Road", "summary": recs[2]}]}
    if goalie:
        t["probables"] = [{"name": "probableStartingGoalie", "athlete": {"displayName": goalie},
                           "status": {"type": status}}]
    return t


TODAY = {"events": [{"competitions": [{"competitors": [_team("home", "BOS", "Boston Bruins", "Jeremy Swayman"),
                                                       _team("away", "WPG", "Winnipeg Jets", "Stuart Skinner",
                                                             "confirmed")]}]}]}
YDAY = {"events": [{"competitions": [{"competitors": [_team("home", "MIN", "Minnesota Wild"),
                                                      _team("away", "WPG", "Winnipeg Jets")]}]}]}


def test_parse_reads_goalies_records_and_splits():
    g = NC.parse(TODAY)[0]
    assert g["home"]["goalie"] == "Jeremy Swayman" and g["home"]["goalie_status"] == "expected"
    assert g["away"]["goalie_status"] == "confirmed"
    assert g["home"]["split"] == "9-4-0" and g["away"]["split"] == "6-3-1" and g["home"]["record"] == "15-7-1"
    assert NC.parse({}) == [] and NC.parse(None) == []


def test_find_and_back_to_back():
    games = NC.parse(TODAY)
    assert NC.find(games, "Jets", "Bruins") is games[0] and NC.find(games, "WPG", "BOS") is games[0]
    assert NC.find(games, "Jets", "Wild") is None
    assert "WPG" in NC.teams_played(YDAY) and "BOS" not in NC.teams_played(YDAY)


def test_point_share_is_among_tonights_points_props():
    rows = [{"market": "Points", "team": "WPG", "player": "Kyle Connor", "projection": 1.2},
            {"market": "Points", "team": "WPG", "player": "Mark Scheifele", "projection": 0.8},
            {"market": "Shots on Goal", "team": "WPG", "player": "Kyle Connor", "projection": 3.5},
            {"market": "Points", "team": "WPG", "player": "Gabriel Vilardi", "projection": 0.6},
            {"market": "Points", "team": "WPG", "player": "Josh Morrissey", "projection": 0.4},
            {"market": "Points", "team": "BOS", "player": "David Pastrnak", "projection": 1.3}]
    got = NC.point_share(rows, "Winnipeg Jets", "WPG")
    assert [(p["name"], round(p["share"], 2)) for p in got] == [("Kyle Connor", 0.4), ("Mark Scheifele", 0.27),
                                                                ("Gabriel Vilardi", 0.2), ("Josh Morrissey", 0.13)]
    assert NC.point_share(rows, "Boston Bruins", "BOS") == []            # one player is no team picture
    assert NC.point_share([], "Winnipeg Jets") == []


def test_side_html_never_guesses_a_goalie():
    g = NC.parse(TODAY)[0]
    html = NC.side_html(g["away"], "road", True, [])
    assert "Stuart Skinner" in html and "✓ confirmed" in html and "back-to-back" in html and "road 6-3-1" in html
    none = NC.side_html({"name": "X", "goalie": ""}, "home", False, [])
    assert "Not announced yet" in none and "back-to-back" not in none
