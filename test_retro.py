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


def test_market_report_matches_homer_report_for_mlb():
    # market_report must reproduce homer_report's exact behavior for the market it generalizes.
    plays = [
        dict(Player="Top", PlayerId=1, Market="Batter HR", Side="Over", Line=0.5, ModelProb=0.25, Conviction=2.3),
        dict(Player="Mid", PlayerId=2, Market="Batter HR", Side="Over", Line=0.5, ModelProb=0.15, Conviction=1.4),
        dict(Player="Low", PlayerId=3, Market="Batter HR", Side="Over", Line=0.5, ModelProb=0.04, Conviction=0.4),
    ]
    results = {2: {"hr": 1}, 3: {"hr": 1}, 99: {"hr": 1}}
    rep = R.market_report(plays, results, "Batter HR", top_n=2, default_line=0.5)
    assert [c["Player"] for c in rep["caught"]] == ["Mid"]
    assert [m["Player"] for m in rep["missed"]] == ["Low"]
    assert rep["unprojected"] == 1
    print("✓ market_report reproduces homer_report's exact behavior for Batter HR")


def test_market_report_works_for_wnba_markets():
    plays = [
        dict(Player="Star", PlayerId=1, Market="Points", Side="Over", Line=15.5, ModelProb=0.72, Conviction=1.44),
        dict(Player="Role Player", PlayerId=2, Market="Points", Side="Over", Line=8.5, ModelProb=0.55, Conviction=1.1),
    ]
    results = {1: {"pts": 24}, 2: {"pts": 6}, 55: {"pts": 30}}   # Star cleared, Role Player didn't, 55 unprojected
    rep = R.market_report(plays, results, "Points", top_n=5, default_line=10.5)
    caught_names = [c["Player"] for c in rep["caught"]]
    assert "Star" in caught_names
    assert "Role Player" not in caught_names   # 6 < 8.5, didn't clear its own line
    assert rep["unprojected"] == 1             # player 55 scored 30 (> default_line) but wasn't projected
    print("✓ market_report works identically for WNBA markets via MARKET_STAT")


def test_market_report_works_for_nfl_markets():
    # NFL's display names are entirely different from basketball's ("Pass Yards" vs "Points"),
    # so unlike WNBA/NBA/NCAAMB sharing one set of MARKET_STAT entries, NFL needed its own — this
    # is the regression guard for the bug found live: Retrospective crashed with an AttributeError
    # before nfl_engine.get_player_results existed at all, and even after adding it, grading would
    # have silently produced zero graded plays without these MARKET_STAT entries too.
    plays = [
        dict(Player="Star QB", PlayerId="p1", Market="Pass Yards", Side="Over", Line=224.5,
            ModelProb=0.65, Conviction=1.3),
        dict(Player="Backup QB", PlayerId="p2", Market="Pass Yards", Side="Over", Line=180.5,
            ModelProb=0.55, Conviction=1.1),
    ]
    results = {"p1": {"passing_yards": 285.0}, "p2": {"passing_yards": 150.0}}
    rep = R.market_report(plays, results, "Pass Yards", top_n=5, default_line=200.0)
    caught_names = [c["Player"] for c in rep["caught"]]
    assert "Star QB" in caught_names
    assert "Backup QB" not in caught_names   # 150 < 180.5, didn't clear its own line
    print("✓ market_report works for NFL's Pass Yards market via MARKET_STAT")


def test_market_stat_covers_every_nfl_display_market():
    # Confirms all four of nfl_projections._MARKET_SPEC's display names have a MARKET_STAT entry
    # — a market present in one but not the other is exactly the silent-zero-graded-plays bug
    # this whole fix was about, so this locks the pairing in explicitly rather than relying on
    # each individual market_report test to happen to cover all four.
    import nfl_projections as NP
    nfl_display_names = {disp for _mkey, _col, disp in NP.market_list()}
    assert nfl_display_names <= set(R.MARKET_STAT.keys()), (
        f"missing from MARKET_STAT: {nfl_display_names - set(R.MARKET_STAT.keys())}")
    print("✓ every NFL display market has a MARKET_STAT entry, no silent grading gaps")


def test_market_report_unknown_market_returns_empty_shape():
    rep = R.market_report([], {}, "Not A Real Market")
    assert rep == {"caught": [], "missed": [], "unprojected": 0, "cutoff": 0, "total_ranked": 0}


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


# ----------------------------------------------------------------- trading_dates_ending_yesterday
def test_trading_dates_ending_yesterday_hand_verified():
    result = R.trading_dates_ending_yesterday(3, as_of="2026-07-21")
    assert result == ["2026-07-18", "2026-07-19", "2026-07-20"]
    print("✓ trading_dates_ending_yesterday returns the correct, hand-verified dates in chronological order")


def test_trading_dates_ending_yesterday_single_day():
    assert R.trading_dates_ending_yesterday(1, as_of="2026-07-21") == ["2026-07-20"]
    print("✓ trading_dates_ending_yesterday correctly handles n_days=1")


def test_trading_dates_ending_yesterday_zero_is_empty_not_an_error():
    assert R.trading_dates_ending_yesterday(0, as_of="2026-07-21") == []
    assert R.trading_dates_ending_yesterday(-3, as_of="2026-07-21") == []
    print("✓ trading_dates_ending_yesterday returns an honest empty list for n_days<=0, not a crash")


def test_trading_dates_ending_yesterday_crosses_month_boundary():
    result = R.trading_dates_ending_yesterday(7, as_of="2026-08-01")
    assert result == ["2026-07-25", "2026-07-26", "2026-07-27", "2026-07-28",
                      "2026-07-29", "2026-07-30", "2026-07-31"]
    print("✓ trading_dates_ending_yesterday correctly crosses a real month boundary")


def test_trading_dates_ending_yesterday_never_includes_today():
    result = R.trading_dates_ending_yesterday(5, as_of="2026-07-21")
    assert "2026-07-21" not in result   # today's slate isn't settled yet, must never be included
    assert result[-1] == "2026-07-20"   # most recent entry is yesterday
    print("✓ trading_dates_ending_yesterday never includes today's date, only fully-settled prior nights")
