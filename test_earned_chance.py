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
    e = PM.earned("NBA", "Points", "Over", 0.70, None, w_by=W)
    assert 0.5 < e < 0.62


def test_no_fit_no_earned():
    assert PM.earned("NHL", "Points", "Over", 0.7, 0.5, w_by=W) is None


def test_clv_leaves_out_a_different_lines_close():
    assert B.clv_pct(-791, -123) is None            # 89% -> 55%: not the same line
    assert B.clv_pct(195, -265) is None
    assert B.clv_pct(-110, -120) is not None and B.clv_pct(-110, -120) > 0


def test_a_priced_pick_without_a_priced_fit_uses_the_model_fit():
    w = {"NCAAMB": {"_all|model": [0.0, 1.0, 0.4, 900]}}
    assert PM.earned("NCAAMB", "Points", "Under", 0.70, 0.55, w_by=w) is not None


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
