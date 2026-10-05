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


def test_catalog_is_book_specific_and_weekday_aware():
    dk = {p["id"] for p in PR.catalog_for("NFL", book="draftkings", date_str="2026-10-05")}     # Monday
    assert dk == {"dk_king_of_the_end_zone", "dk_mnf_sgp_no_sweat", "dk_50_boost_gameday"}
    dk_sun = {p["id"] for p in PR.catalog_for("NFL", book="draftkings", date_str="2026-10-04")}  # Sunday
    assert "dk_mnf_sgp_no_sweat" not in dk_sun and "dk_king_of_the_end_zone" in dk_sun
    fd_thu = {p["id"] for p in PR.catalog_for("NFL", book="fanduel", date_str="2026-10-08")}
    assert "fd_td_jackpot" in fd_thu
    assert "fd_td_jackpot" not in {p["id"] for p in PR.catalog_for("NFL", book="fanduel", date_str="2026-10-05")}
    assert PR.catalog_for("NFL", book="hardrockbet", date_str="2026-10-05") == []   # nothing on file, honestly
    assert all(p["kind"] in PR.KINDS and p["source"] and p["note"] for p in PR.PROMO_CATALOG)


def test_custom_promo_validates_and_is_included():
    c = PR.make_custom_promo("hardrockbet", "TD Boost", "NFL", "anytime_td", "bet")
    assert c in PR.catalog_for("NFL", [c]) and c not in PR.catalog_for("MLB", [c])
    assert c in PR.catalog_for("NFL", [c], book="hardrockbet") and c not in PR.catalog_for("NFL", [c], book="fanduel")
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
    b = PR.promo_blurb(PR.PROMO_CATALOG[0], "DraftKings")
    assert "DraftKings — King of the End Zone" in b and "LONGEST" in b and "yards per touch" in b


def _gp(name, market, conv, prob=.6, side="Over", line=24.5, **kw):
    return {"Player": name, "Team": "ATL", "Market": market, "Side": side, "Line": line, "ModelProb": prob,
            "Conviction": conv, "Fair": -120, **kw}


def test_sgp_takes_one_play_per_player_by_conviction_and_skips_longshot_td_markets():
    plays = [_gp("A", "Pass Yds", 2.0), _gp("A", "Pass Attempts", 1.9), _gp("B", "Rec Yds", 1.5),
             _gp("C", "First TD Scorer", 9.0, prob=.05), _gp("D", "Receptions", 1.2)]
    picks = PR.promo_picks(plays, {"kind": "sgp"}, n=3)
    assert [x["play"]["Player"] for x in picks] == ["A", "B", "D"]
    assert [x["play"]["Market"] for x in picks][0] == "Pass Yds"
    assert all(x["kind"] == "sgp" for x in picks)


def test_boost_prefers_priced_plays_then_ev_then_conviction():
    unpriced_hi = _gp("U", "Pass Yds", 3.0)                                       # best conviction, no price
    priced_lo_ev = _gp("P1", "Receptions", 1.2, PriceSource="book", RealPrice=-110, EV=2.0)
    priced_hi_ev = _gp("P2", "Rec Yds", 1.1, PriceSource="book", RealPrice=120, EV=6.5)
    picks = PR.promo_picks([unpriced_hi, priced_lo_ev, priced_hi_ev], {"kind": "boost"}, n=3)
    assert [x["play"]["Player"] for x in picks] == ["P2", "P1", "U"]


def test_pick_line_for_boost_names_market_line_price_and_ev():
    p = _gp("P2", "Rec Yds", 1.1, PriceSource="book", RealPrice=120, RealPriceBook="FanDuel", EV=6.5)
    s = PR.pick_line({"play": p, "kind": "boost", "tag": ""})
    assert "Rec Yds Over 24.5" in s and "+120 at FanDuel" in s and "+6.5% EV" in s and "popular" not in s


def test_first_last_td_pool_uses_first_td_plays():
    plays = [_play("a", .1, market="First TD Scorer"), _play("b", .5)]
    assert [x["play"]["Player"] for x in PR.promo_picks(plays, {"kind": "first_last_td"})] == ["a"]


def test_boost_prefers_a_real_price_even_without_ev_over_a_higher_conviction_unpriced_play():
    unpriced = _gp("U", "Pass Yds", 3.0)
    priced = _gp("R", "Receptions", 1.0, PriceSource="book", RealPrice=-115)
    assert [x["play"]["Player"] for x in PR.promo_picks([unpriced, priced], {"kind": "boost"}, n=2)] == ["R", "U"]
