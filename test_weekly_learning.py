"""Nov 15: NFL and college football learn on their short seasons -- every read rescaled to today's factor, held out by
game, two slates."""
import random

import calibration as CAL
import postgame as PG


def test_rescale_round_trips():
    p_then = CAL.honest(0.70, 0.5)                      # shown 0.60 under a 0.5 factor
    assert abs(CAL.rescale(p_then, 0.5, 1.0) - 0.70) < 1e-9
    assert abs(CAL.rescale(p_then, 0.5, 0.3) - CAL.honest(0.70, 0.3)) < 1e-9
    assert CAL.factor_at([("2026-11-09T12:58", 0.85)], "2026-11-08T23:59") == 1.0
    assert CAL.factor_at([("2026-11-09T12:58", 0.85)], "2026-11-15T13:00") == 0.85


def _rows(n_games, per_game, dates, p=0.75, true=0.6, seed=1):
    rnd = random.Random(seed)
    out = []
    for d in dates:
        for g in range(n_games):
            for _ in range(per_game):
                out.append({"date": d, "game": f"g{g}", "p": p, "y": 1 if rnd.random() < true else 0})
    return out


def test_weekly_holdout_uses_games_not_days():
    rows = _rows(14, 30, ["2026-11-09", "2026-11-10"])          # two NFL slates, overconfident 75% -> 60%
    daily = CAL.held_out_side(rows)
    weekly = CAL.held_out_side(rows, weekly=True)
    assert weekly["splits"] == 5 and weekly["passed"] >= 4 and weekly["rel"] < 0.8
    assert daily["splits"] <= 1                                  # a day-by-day split can't get going on two slates


def test_holds_up_by_game():
    rows = []
    for g in range(6):
        for k in range(8):
            rows.append({"slate_date": "2026-11-09", "game": f"g{g}", "projection": 50.0, "actual": 60.0 + k % 3})
    assert PG.holds_up(rows, 1.1, by_game=True)
    assert not PG.holds_up(rows, 1.1)                           # one slate: no slate-by-slate check possible
