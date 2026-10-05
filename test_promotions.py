import pytest
import promotions as PR


def _play(name, prob, rec_yds=0, rec=0, rush_yds=0, car=0, market="Anytime TD", **kw):
    log = [{"receiving_yards": rec_yds, "receptions": rec, "rushing_yards": rush_yds, "carries": car}] * 4
    return {"Player": name, "Team": "ATL", "Market": market, "ModelProb": prob, "_game_log": log,
            "Fair": 150, **kw}


def test_catalog_has_king_of_the_end_zone_for_nfl_only():
    ids = [p["id"] for p in PR.catalog_for("NFL")]
    assert "dk_king_of_the_end_zone" in ids
    assert PR.catalog_for("MLB") == []


def test_custom_promo_validates_and_is_included():
    c = PR.make_custom_promo("FanDuel", "TD Boost", "NFL", "anytime_td", "bet")
    assert c in PR.catalog_for("NFL", [c]) and c not in PR.catalog_for("MLB", [c])
    with pytest.raises(ValueError):
        PR.make_custom_promo("", "x", "NFL", "info")
    with pytest.raises(ValueError):
        PR.make_custom_promo("a", "x", "NFL", "nonsense")


def test_explosiveness_needs_touches():
    assert PR.explosiveness(_play("a", .3, rec_yds=30, rec=2)) == 15.0   # 4 games x 2 touches
    assert PR.explosiveness({"_game_log": []}) is None
    assert PR.explosiveness(_play("a", .3, rec_yds=5, rec=0, car=0)) is None


def test_longest_td_prefers_explosive_over_slightly_likelier_goal_line_back():
    promo = PR.PROMO_CATALOG[0]
    goal_line = _play("Bruiser", 0.46, rush_yds=8, car=4)           # 2.0 yds/touch
    deep = _play("Burner", 0.40, rec_yds=60, rec=4)                  # 15 yds/touch -> capped boost
    picks = PR.promo_picks([goal_line, deep], promo, n=2)
    assert [x["play"]["Player"] for x in picks] == ["Burner", "Bruiser"]


def test_picks_only_use_matching_market_and_respect_n():
    promo = PR.PROMO_CATALOG[0]
    plays = [_play("a", .5), _play("b", .4, market="Pass Yds"), _play("c", .3), _play("d", .2)]
    picks = PR.promo_picks(plays, promo, n=2)
    assert all(x["play"]["Market"] == "Anytime TD" for x in picks) and len(picks) == 2
    assert PR.promo_picks(plays, promo, n=0) == []


def test_chalk_tag_marks_top_three_by_probability():
    promo = PR.PROMO_CATALOG[0]
    plays = [_play(c, p, rec_yds=20, rec=4) for c, p in zip("abcde", (.5, .45, .4, .3, .2))]
    tags = {x["play"]["Player"]: x["tag"] for x in PR.promo_picks(plays, promo, n=5)}
    assert tags == {"a": "chalk", "b": "chalk", "c": "chalk", "d": "leverage", "e": "leverage"}


def test_first_td_uses_first_td_market_and_info_promo_has_no_picks():
    first = {"kind": "first_td", "book": "X", "name": "Y"}
    plays = [_play("a", .1, market="First TD Scorer"), _play("b", .5)]
    assert [x["play"]["Player"] for x in PR.promo_picks(plays, first)] == ["a"]
    assert PR.promo_picks(plays, {"kind": "info"}) == []
    assert PR.promo_picks([], first) == []


def test_pick_line_shows_real_price_else_fair_and_tags():
    pick = {"play": _play("Z", .31, RealPrice=240, RealPriceBook="DraftKings", PriceSource="book"),
            "tag": "leverage", "ypt": 9.5}
    s = PR.pick_line(pick)
    assert "+240 at DraftKings" in s and "9.5 yds/touch" in s and "less obvious" in s
    pick["play"]["PriceSource"] = "model_fair"
    assert "fair ~+150" in PR.pick_line(pick)
    assert "popular" in PR.pick_line({**pick, "tag": "chalk"})


def test_promo_blurb_names_book_and_ranking_rule():
    b = PR.promo_blurb(PR.PROMO_CATALOG[0])
    assert "DraftKings — King of the End Zone" in b and "LONGEST" in b and "yards per touch" in b
