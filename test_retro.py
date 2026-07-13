"""
test_retro.py — offline tests for retrospective grading (no network).

    python test_retro.py    # or: pytest test_retro.py
"""

import mlb_engine as E
import retro as R


def test_grade_play():
    a = {"hr": 1, "tb": 5, "hits": 2, "so": 1}
    assert R.grade_play("Batter HR", "Over", 0.5, a) is True
    assert R.grade_play("Batter Total Bases", "Over", 1.5, a) is True
    assert R.grade_play("Batter Total Hits", "Under", 0.5, a) is False    # had 2 hits
    p = {"p_k": 4, "p_outs": 18, "p_bb": 2}
    assert R.grade_play("Pitcher Strikeouts", "Over", 5.5, p) is False     # only 4 K
    assert R.grade_play("Pitcher Strikeouts", "Under", 5.5, p) is True
    # no relevant stat -> ungraded
    assert R.grade_play("Batter HR", "Over", 0.5, {"p_k": 6}) is None
    assert R.grade_play("Batter HR", "Over", 0.5, None) is None


def test_grade_slate_summary():
    plays = [
        dict(Player="A", PlayerId=1, Market="Batter HR", Side="Over", Line=0.5, ModelProb=0.24, Conviction=2.2),
        dict(Player="B", PlayerId=2, Market="Batter HR", Side="Over", Line=0.5, ModelProb=0.18, Conviction=1.6),
        dict(Player="C", PlayerId=3, Market="Pitcher Strikeouts", Side="Over", Line=5.5, ModelProb=0.7, Conviction=1.4),
        dict(Player="D", PlayerId=4, Market="Batter HR", Side="Over", Line=0.5, ModelProb=0.2, Conviction=1.8),
    ]
    results = {1: {"hr": 0}, 2: {"hr": 1}, 3: {"p_k": 8}}  # D has no result -> ungraded
    graded, summary = R.grade_slate(plays, results)
    assert summary["total"] == 4 and summary["graded"] == 3   # D ungraded
    assert summary["hits"] == 2                                # B homered, C fanned 8
    assert abs(summary["hit_rate"] - 0.667) < 0.001     # rounded to 3 decimals


def test_homer_report_catches_and_misses():
    plays = [
        dict(Player="Top", PlayerId=1, Market="Batter HR", Side="Over", Line=0.5, ModelProb=0.25, Conviction=2.3),
        dict(Player="Mid", PlayerId=2, Market="Batter HR", Side="Over", Line=0.5, ModelProb=0.15, Conviction=1.4),
        dict(Player="Low", PlayerId=3, Market="Batter HR", Side="Over", Line=0.5, ModelProb=0.04, Conviction=0.4),
    ]
    results = {2: {"hr": 1}, 3: {"hr": 1}, 99: {"hr": 1}}   # Mid + Low homered; 99 unprojected
    rep = R.homer_report(plays, results, top_n=2)
    caught_names = [c["Player"] for c in rep["caught"]]
    missed_names = [m["Player"] for m in rep["missed"]]
    assert "Mid" in caught_names      # rank 2, within top-2 cutoff
    assert "Low" in missed_names      # rank 3, below cutoff
    assert rep["unprojected"] == 1    # player 99


def test_boxscore_parsing():
    box = {"teams": {"home": {"players": {
        "ID1": {"person": {"id": 1, "fullName": "Slugger"},
                "stats": {"batting": {"hits": 2, "doubles": 1, "triples": 0, "homeRuns": 1, "strikeOuts": 1}}}}},
        "away": {"players": {
            "ID2": {"person": {"id": 2, "fullName": "Ace"},
                    "stats": {"pitching": {"strikeOuts": 8, "baseOnBalls": 2, "inningsPitched": "6.2"}}}}}}}
    res = E._parse_boxscore_results(box)
    assert res[1]["hr"] == 1 and res[1]["tb"] == 6      # double(2)+HR(4)=6
    assert res[2]["p_k"] == 8 and res[2]["p_outs"] == 20  # 6.2 IP -> 20 outs


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}"); passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
