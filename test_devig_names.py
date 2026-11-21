"""Nov 21: de-vigged moneylines match a school name to the feed's school + mascot when only one team fits."""
import odds_api as O

ML = {"Utah State Aggies": {"fanduel": -150}, "Air Force Falcons": {"fanduel": 130},
      "Texas Longhorns": {"fanduel": -200}, "Texas Tech Red Raiders": {"fanduel": 170}}


def test_school_names_match_the_feeds_full_names():
    r = O.real_moneyline_devig(ML, "Utah State", "Air Force")
    assert r and 0.5 < r[0] < 0.6 and r[1] == "fanduel"


def test_an_ambiguous_school_stays_unmatched():
    assert O.real_moneyline_devig(ML, "Texas", "Air Force") is None
