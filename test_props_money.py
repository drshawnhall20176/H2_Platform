"""Nov 20: the props Money Score (props_money.py)."""
import math
import random

import props_money as PMS


def test_rows_from_graded_keep_priced_sportsbook_reads_over_oriented():
    g = [{"actual": 25, "line": 20.5, "p_model": 0.6, "p_market": 0.5, "over_price": -110, "under_price": -110,
          "market": "Points", "book": "draftkings"},
         {"actual": 20.5, "line": 20.5, "p_model": 0.6, "p_market": 0.5, "over_price": -110, "under_price": -110,
          "market": "Points"},                                          # not a half line: 20.5 actual can't happen, skip
         {"actual": 25, "line": 20.5, "p_model": 0.6, "p_market": 0.5, "over_price": None, "under_price": -110},
         {"actual": 25, "line": 20.5, "p_model": 0.6, "p_market": 0.5, "over_price": -110, "under_price": -110,
          "book": "prizepicks"}]
    rows = PMS.rows_from_graded(g)
    assert len(rows) == 1 and rows[0]["y"] == 1.0 and rows[0]["market"] == "Points"


def test_fit_and_score_by_side():
    rng = random.Random(3)
    rows = []
    for _ in range(1500):                    # truth: the model's disagreement is worth half
        pm, pmod = rng.uniform(0.35, 0.65), rng.uniform(0.3, 0.7)
        lt = math.log(pm / (1 - pm)) + 0.5 * (math.log(pmod / (1 - pmod)) - math.log(pm / (1 - pm)))
        rows.append({"market": "Points", "pm": pm, "pmod": pmod, "y": float(rng.random() < 1 / (1 + math.exp(-lt)))})
    c = PMS.fit_sport(rows)
    assert "_all" in c and "Points" in c and 0.25 < c["Points"][2] < 0.75
    w = {"NBA": c}
    over = PMS.score("NBA", "Points", "Over", 0.62, 0.50, 100, w_by=w)
    under = PMS.score("NBA", "Points", "Under", 0.38, 0.50, 100, w_by=w)      # the same read, other side
    assert over > 0.05 and under < 0 and abs((over + 1) / 2 + (under + 1) / 2 - 1) < 1e-9
    assert PMS.score("NBA", "Points", "Over", 0.62, 0.5, None, w_by=w) is None
    assert PMS.score("NHL", "Points", "Over", 0.62, 0.5, 100, w_by=w) is None
    assert PMS.play_score("NBA", {"Market": "Rebounds", "Side": "Over", "ModelRaw": 0.62, "MarketProb": 0.5,
                                  "RealPrice": 100}, w_by=w) is not None      # the sport-wide fit
    assert PMS.play_score("NBA", {"Pickem": True}, w_by=w) is None
