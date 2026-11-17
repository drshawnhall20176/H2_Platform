"""Nov 17: the books' promotions show themselves on the days they run."""
from datetime import date

import promos as P


def test_king_of_the_court_on_nba_tuesdays_only():
    tue, wed = date(2026, 11, 17), date(2026, 11, 18)
    ids = [p["id"] for p in P.on_today(tue, ["NBA"], custom=[], banners_only=True)]
    assert ids == ["dk_kotc"]
    assert P.on_today(wed, ["NBA"], custom=[], banners_only=True) == []
    assert P.on_today(tue, ["NFL"], custom=[], banners_only=True) == []          # no NBA tonight
    assert P.on_today(date(2026, 7, 7), ["NBA"], custom=[], banners_only=True) == []   # out of season


def test_custom_one_day_promo():
    c = [{"id": "x", "book": "FanDuel", "name": "Boost", "sports": ["NFL"], "days": [], "dates": ["2026-11-20"],
          "window": None, "banner": True, "rules": "r"}]
    assert [p["id"] for p in P.on_today(date(2026, 11, 20), ["NFL"], custom=c, banners_only=True)] == ["x"]
    assert P.on_today(date(2026, 11, 21), ["NFL"], custom=c, banners_only=True) == []
    assert P.schedule_text(c[0]) == "2026-11-20" and P.schedule_text(P.SEED[0]) == "Tue"
    assert P.schedule_text(P.SEED[1]) == "every day in season"


def test_promotions_page_renders():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("views/59_Promotions.py", default_timeout=60).run()
    assert not at.exception, [str(e.value)[:200] for e in at.exception]
    assert any("Every promotion we track" in m.value for m in at.markdown)
