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
