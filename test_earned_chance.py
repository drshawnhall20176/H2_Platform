"""Nov 21: earned chances (props_money.earned) and same-line CLV (betlog.clv_pct)."""
import betlog as B
import props_money as PM

W = {"NBA": {"_all": [0.0, 1.0, 0.3, 1000], "_all|model": [0.0, 1.0, 0.4, 1000]}}


def test_earned_with_a_price_is_books_plus_part_of_the_disagreement():
    e = PM.earned("NBA", "Points", "Over", 0.70, 0.52, w_by=W)
    assert 0.52 < e < 0.60
    u = PM.earned("NBA", "Points", "Under", 0.70, 0.52, w_by=W)          # the side's own chances
    assert 0.52 < u < 0.60


def test_earned_without_a_price_pulls_toward_half():
    e = PM.earned("NBA", "Points", "Over", 0.70, None, w_by=W, day="2026-11-21")       # v2
    assert 0.5 < e < 0.62
    assert PM.earned("NBA", "Points", "Over", 0.70, None, w_by=W, day="2026-11-22") == 0.5   # v3: no credit yet


def test_no_fit_no_earned():
    assert PM.earned("NHL", "Points", "Over", 0.7, 0.5, w_by=W, day="2026-11-21") is None
    assert abs(PM.earned("NHL", "Points", "Over", 0.7, 0.45, w_by=W, day="2026-11-22") - 0.45) < 1e-9    # v3: books


def test_clv_leaves_out_a_different_lines_close():
    assert B.clv_pct(-791, -123) is None            # 89% -> 55%: not the same line
    assert B.clv_pct(195, -265) is None
    assert B.clv_pct(-110, -120) is not None and B.clv_pct(-110, -120) > 0


def test_a_priced_pick_without_a_priced_fit_uses_the_model_fit():
    w = {"NCAAMB": {"_all|model": [0.0, 1.0, 0.4, 900]}}
    assert PM.earned("NCAAMB", "Points", "Under", 0.70, 0.55, w_by=w, day="2026-11-21") is not None
    assert abs(PM.earned("NCAAMB", "Points", "Under", 0.70, 0.55, w_by=w, day="2026-11-22") - 0.45) < 1e-9   # v3: books


def test_the_second_stage_lowers_a_high_earned_chance_from_nov_22():
    w = dict(W, _post={"priced": [0.0, 1.0, 0.3, 500]})
    v1 = PM.earned("NBA", "Points", "Over", 0.85, 0.55, w_by=w, post=False)
    v2 = PM.earned("NBA", "Points", "Over", 0.85, 0.55, w_by=w, day="2026-11-22")
    assert v2 < v1 and v2 > 0.5
    assert PM.earned("NBA", "Points", "Over", 0.85, 0.55, w_by=w, day="2026-11-21") == v1


def test_fit_post_needs_enough_shown_picks(monkeypatch):
    monkeypatch.setattr(PM, "shown", lambda sp, r: True)
    g = {"NBA": [{"actual": 12, "p_model": 0.7, "line": 10.5, "p_market": 0.5, "book": "fanduel", "market": "Points"}]
             * 250 + [{"actual": 8, "p_model": 0.7, "line": 10.5, "p_market": 0.5, "book": "fanduel",
                       "market": "Points"}] * 250}
    post = PM.fit_post(g, W)
    assert "priced" in post and post["priced"][3] == 500


def test_v3_a_priced_play_without_the_other_side_uses_its_own_implied_chance():
    """Nov 22: a one-sided price isn't a pick'em line."""
    p = {"Market": "Points", "Side": "Under", "ModelProb": 0.7, "RealPrice": -150, "MarketProb": None}
    e = PM.play_earned("NHL", p, w_by={})
    assert abs(e - 0.6) < 1e-9                                     # -150 implies 60% (no fit: the books' chance)
    assert PM.play_earned("NHL", dict(p, Pickem=True, RealPrice=None), w_by={}) == 0.5
