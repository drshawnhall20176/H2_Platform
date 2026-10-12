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


def _pp(name, prob, rec_yds, rec, tgt, tds=0, n=3, game="ATL @ NO"):
    log = [{"receiving_yards": rec_yds, "receptions": rec, "targets": tgt, "carries": 0, "rushing_yards": 0,
            "receiving_tds": tds, "rushing_tds": 0}] * n
    return {"Player": name, "Team": "ATL", "Market": "Anytime TD", "ModelProb": prob, "Game": game,
            "Position": "WR", "_game_log": log, "Fair": 250}


def test_find_players_matches_every_word_ignoring_case_and_punctuation():
    pool = [_pp("Michael Penix Jr.", .3, 0, 0, 0), _pp("Drake London", .3, 60, 4, 6), _pp("Drake Maye", .2, 0, 0, 0)]
    assert [p["Player"] for p in PR.find_players("drake", pool)] == ["Drake Maye", "Drake London"] or \
        {p["Player"] for p in PR.find_players("drake", pool)} == {"Drake London", "Drake Maye"}
    assert [p["Player"] for p in PR.find_players("PENIX jr", pool)] == ["Michael Penix Jr."]
    assert [p["Player"] for p in PR.find_players("drake maye", pool)] == ["Drake Maye"]      # every word must match
    assert PR.find_players("", pool) == [] and PR.find_players("nobody here", pool) == []
    assert PR.find_players("drake", [{**pool[1], "Market": "First TD Scorer"}]) == []      # anytime plays only


def test_player_profile_ranks_within_game_and_flags_small_sample_and_scoreless():
    pool = [_pp("Burner", .286, 65, 4, 6), _pp("Chalk", .571, 40, 3, 4, tds=1), _pp("Mid", .429, 50, 5, 7, tds=1),
            _pp("Dotson", .286, 11, 2, 3), _pp("Other", .286, 6, 2, 4)]
    top = PR.player_profile(pool[0], pool)
    weak = PR.player_profile(pool[3], pool, first_td_plays=[{"Player": "Dotson", "Market": "First TD Scorer", "ModelProb": .03}])
    assert top["verdict"] in ("Strong fit", "Reasonable fit") and top["rank"] < weak["rank"]
    assert weak["verdict"] == "Weak fit" and weak["pool_size"] == 5 and weak["first_td_prob"] == .03
    assert any("Only 3 game(s)" in n for n in weak["notes"]) and any("No TD yet" in n for n in weak["notes"])
    assert any("less explosive" in n for n in weak["notes"]) and any("more explosive" in n for n in top["notes"])
    assert weak["targets_pg"] == 3 and weak["td_games"] == 0
    lines = PR.profile_lines(weak)
    assert "Weak fit for King of the End Zone" in lines[0] and "#4 of 5" in lines[0] and "~3% to score first" in lines[1]


def test_player_profile_with_too_few_touches_says_so():
    p = _pp("Ghost", .286, 0, 0, 0)
    pf = PR.player_profile(p, [p])
    assert pf["ypt"] is None and any("Too few touches" in n for n in pf["notes"])


def test_explosiveness_factor_keeps_separating_big_play_receivers_instead_of_capping_early():
    assert PR._factor(None) == 1.0
    assert PR._factor(8.0) == 1.0 and PR._factor(2.0) == 0.4 and PR._factor(30.0) == 2.0
    assert PR._factor(11.5) < PR._factor(13.9) < PR._factor(16.4)          # a Vele < Olave < London ordering


def test_longest_td_lets_a_scoreless_deep_threat_overtake_a_likelier_possession_receiver():
    deep = _play("Deep", 0.286, rec_yds=65, rec=4)                       # 16 yds/touch, no TD yet
    slot = _play("Slot", 0.40, rec_yds=24, rec=4)                         # 6 yds/touch
    picks = PR.promo_picks([deep, slot], PR.PROMO_CATALOG[0], n=2)
    assert [x["play"]["Player"] for x in picks] == ["Deep", "Slot"]


def test_qbs_and_unreadable_players_are_penalised_not_given_a_free_pass_in_the_longest_td_ranking():
    qb = {**_pp("Qb", .40, 0, 0, 0), "Position": "QB"}
    unknown = _pp("Unknown", .30, 0, 0, 0)                                  # no touches -> ypt None
    wr = _pp("Wr", .286, 40, 4, 6)                                           # 10 yds/touch
    order = [x["play"]["Player"] for x in PR.promo_picks([qb, unknown, wr], PR.PROMO_CATALOG[0], n=3)]
    assert order == ["Wr", "Unknown", "Qb"]                                  # .286*1.25=.36 > .30*.8=.24 > .40*.5=.20
    assert PR._factor_for({"Position": "QB"}, 20.0) == PR._QB_FACTOR and PR._factor_for({}, None) == PR._UNKNOWN_FACTOR
    sneak_qb = {**_pp("Sneak Qb", .90, 0, 0, 0), "Position": "QB"}            # very likely to score, but on sneaks
    assert PR._QB_FACTOR == 0.2
    assert [x["play"]["Player"] for x in PR.promo_picks([sneak_qb, wr], PR.PROMO_CATALOG[0], n=2)] == ["Wr", "Sneak Qb"]


def test_profile_compares_explosiveness_with_the_player_s_own_position_group():
    rb = {**_pp("Back", .5, 30, 6, 6), "Position": "RB"}                     # 5 yds/touch
    wr1, wr2 = _pp("Wr1", .3, 60, 4, 6), _pp("Wr2", .3, 20, 4, 6)             # 15 and 5
    pf = PR.player_profile(wr2, [rb, wr1, wr2])
    assert any("less explosive than most" in n for n in pf["notes"])           # 5 vs the WR median of 10, not vs the back
    assert any("receivers and tight ends" in n for n in pf["notes"])
    assert not any("backs" in n for n in pf["notes"])
