"""Nov 21: automatic shut-off (shutoff.py)."""
import shutoff as SO


def test_a_market_losing_beyond_luck_is_off():
    units = [0.9] * 60 + [-1.0] * 100                          # 160 picks, about -25% per $1
    assert SO.verdict(units, [])["state"] == "off"


def test_a_small_or_winning_sample_stays_on():
    assert SO.verdict([0.9] * 40 + [-1.0] * 40, [])["state"] == "ok"
    assert SO.verdict([0.95] * 90 + [-1.0] * 70, [])["state"] == "ok"


def test_losing_to_the_close_is_off_and_a_mid_loss_is_watch():
    assert SO.verdict([0.9] * 60 + [-1.0] * 60, ["lost"] * 70 + ["beat"] * 40)["state"] == "off"
    assert SO.verdict([0.9] * 40 + [-1.0] * 45, [])["state"] == "watch"


def test_off_applies_from_its_start_day_only():
    st = {"since": {"NHL|Points|lock": "2026-11-21"}}
    assert SO.is_off("NHL", "Points", "lock", "2026-11-21", st)
    assert not SO.is_off("NHL", "Points", "lock", "2026-11-20", st)
    assert not SO.is_off("NBA", "Points", "lock", "2026-11-21", st)


def test_refit_scores_props_and_games_and_keeps_the_first_off_day():
    saved = {}
    graded = [{"result": "miss", "price": -110, "market": "Points", "chance": 0.7, "cushion": 3, "book": "fanduel",
               "side": "Over"}] * 3
    from datetime import datetime, timezone
    rec = SO.refit("2026-11-21", now=datetime(2026, 11, 21, 12, tzinfo=timezone.utc), save=lambda k, v: saved.__setitem__(k, v), grade=lambda sp: graded,
                   games=[{"sport": "NCAAMB", "money": True, "money_result": "loss", "money_price": -110,
                           "money_market": "Spread"}] * 200)
    assert rec["groups"]["NCAAMB|Spread|games"]["state"] == "off"
    assert rec["since"]["NCAAMB|Spread|games"] == "2026-11-21"


def test_the_money_live_test_is_not_switched_off_mid_test():
    st = {"since": {"NHL|Points|money": "2026-11-21"}}
    assert not SO.is_off("NHL", "Points", "money", "2026-11-22", st)
    assert SO.is_off("NHL", "Points", "money", "2026-11-24", st)
