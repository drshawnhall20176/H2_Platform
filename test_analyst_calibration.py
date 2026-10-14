"""analyst_calibration.py — a correction is fitted on older calls and only trusted if it beats the stated chance on newer ones."""
import random

import analyst_calibration as C
import analyst_tools as AT


def rows(n_days=60, per=12, shift=0.12, seed=1):
    random.seed(seed)
    out = []
    for d in range(n_days):
        for i in range(per):
            p = random.uniform(0.45, 0.85)
            t = min(0.95, max(0.05, p - shift))
            out.append({"date": f"2026-{1 + d // 28:02d}-{d % 28 + 1:02d}", "logged_at": str(i), "model_prob": p,
                        "hit": 1 if random.random() < t else 0})
    return out


def test_there_is_nothing_to_fit_without_graded_calls():
    assert C.fit([]) is None and C.evaluate([])["status"] == "not_enough"
    assert C.fit([{"model_prob": 0.6, "hit": None, "date": "d"}]) is None            # an open or void call is not evidence
    assert C.apply(None, 0.6) == 0.6 and C.apply({"a": 1, "b": 0}, None) is None


def test_no_correction_is_the_identity_and_overconfidence_is_pulled_down():
    assert abs(C.apply({"a": 1.0, "b": 0.0}, 0.63) - 0.63) < 1e-9
    m = C.fit(rows())
    assert C.apply(m, 0.7) < 0.7 - 0.05 and C.apply(m, 0.5) < 0.5                       # said 70%, really nearer 58%
    assert 0.01 <= C.apply(m, 0.999) <= 0.99


def test_data_that_is_calibrated_is_left_nearly_alone():
    m = C.fit(rows(shift=0.0, n_days=120))
    assert abs(C.apply(m, 0.65) - 0.65) < 0.05


def test_small_samples_are_not_tested_or_trusted():
    ev = C.evaluate(rows(n_days=5, per=6))
    assert ev["status"] == "not_enough" and ev["helps"] is False and C.corrected_for_sport(rows(n_days=5, per=6)) is None


def test_the_test_set_is_the_newest_whole_days_and_never_overlaps_the_fit():
    data = rows()
    ev = C.evaluate(data)
    assert ev["status"] == "ok" and ev["n_train"] + ev["n_test"] == len(data) and ev["n_test"] >= 0.3 * len(data)
    newest = sorted({r["date"] for r in data})[-1]
    train_days = {r["date"] for r in sorted(data, key=lambda r: (r["date"], r["logged_at"]))[:ev["n_train"]]}
    assert newest not in train_days and max(train_days) < min(d for d in {r["date"] for r in data} if d not in train_days)


def test_a_correction_is_offered_only_when_it_beat_the_stated_chance_on_unseen_calls():
    wins = sum(C.evaluate(rows(seed=s))["helps"] for s in range(10))
    assert wins >= 8                                                                     # real overconfidence is detected
    ev = C.evaluate(rows())
    assert ev["brier_adj"] < ev["brier_raw"] and C.corrected_for_sport(rows()) == ev["model"]
    false_alarms = sum(C.evaluate(rows(shift=0.0, seed=s))["helps"] for s in range(10))
    assert false_alarms <= 3                                                             # calibrated data rarely earns a correction


def test_the_correction_must_clear_a_minimum_improvement(monkeypatch):
    monkeypatch.setattr(C, "MIN_IMPROVEMENT", 10.0)
    assert C.evaluate(rows())["helps"] is False and C.corrected_for_sport(rows()) is None


def test_examples_show_what_a_few_stated_chances_become():
    m = C.fit(rows())
    ex = C.examples(m)
    assert set(ex) == {0.5, 0.6, 0.7, 0.8} and ex[0.8] < 0.8 and C.examples(None) == {}


def r(sport, date, hit=None, settled=None, market="Points"):
    return {"sport": sport, "date": date, "hit": hit, "settled_at": settled, "market": market, "model_prob": 0.6}


def test_grading_status_separates_graded_void_waiting_and_not_yet_played():
    rs = [r("NFL", "2026-10-01", hit=1), r("NFL", "2026-10-01", hit=0), r("NFL", "2026-10-02", settled="x"),
          r("NFL", "2026-10-03"), r("NFL", "2026-10-04"), r("NFL", "2026-10-10"), r("NCAAF", "2026-09-05")]
    st = {x["sport"]: x for x in AT.grading_status(rs, "2026-10-10")}
    nfl = st["NFL"]
    assert (nfl["locked"], nfl["graded"], nfl["void"], nfl["waiting"], nfl["open_today"]) == (6, 2, 1, 2, 1)
    assert nfl["waiting_days"] == 2 and nfl["oldest_waiting"] == "2026-10-03"
    assert st["NCAAF"]["waiting"] == 1 and st["NCAAF"]["oldest_waiting"] == "2026-09-05" and list(st) == ["NCAAF", "NFL"]


def test_market_board_counts_only_graded_calls_biggest_market_first():
    rs = [r("NFL", "d", hit=1, market="A"), r("NFL", "d", hit=0, market="B"), r("NFL", "d", hit=1, market="B"),
          r("NFL", "d", hit=None, market="A")]
    b = AT.market_board(rs)
    assert [(x["market"], x["n"]) for x in b] == [("B", 2), ("A", 1)] and b[0]["hit_rate"] == 0.5


def test_a_tiny_or_one_sided_sample_cannot_swing_the_correction_wildly():
    wins = [{"date": "d", "logged_at": str(i), "model_prob": p, "hit": 1} for i, p in enumerate((0.5, 0.6, 0.7, 0.8, 0.9))]
    m = C.fit(wins)                                                                      # every call hit: unregularized, the curve runs away
    assert abs(m["a"]) < 5 and abs(m["b"]) < 5 and C.apply(m, 0.6) < 0.95
