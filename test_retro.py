"""
test_retro.py — offline tests for retrospective grading (no network).

    python test_retro.py    # or: pytest test_retro.py
"""

import mlb_engine as E
import retro as R


def test_grade_play():
    a = {"hr": 1, "tb": 5, "hits": 2, "so": 1, "hrr": 4}
    assert R.grade_play("Batter HR", "Over", 0.5, a) is True
    assert R.grade_play("Batter Total Bases", "Over", 1.5, a) is True
    assert R.grade_play("Batter Total Hits", "Under", 0.5, a) is False    # had 2 hits
    assert R.grade_play("Batter Hits+Runs+RBIs", "Over", 1.5, a) is True   # 4 > 1.5
    assert R.grade_play("Batter Hits+Runs+RBIs", "Under", 1.5, a) is False
    p = {"p_k": 4, "p_outs": 18, "p_bb": 2}
    assert R.grade_play("Pitcher Strikeouts", "Over", 5.5, p) is False     # only 4 K
    assert R.grade_play("Pitcher Strikeouts", "Under", 5.5, p) is True
    # no relevant stat -> ungraded
    assert R.grade_play("Batter HR", "Over", 0.5, {"p_k": 6}) is None
    assert R.grade_play("Batter HR", "Over", 0.5, None) is None


# ----------------------------------------------------------------- settle_bet_result
def test_settle_bet_result_win_and_loss():
    a = {"hr": 1, "tb": 5, "hits": 2, "so": 1, "hrr": 4}
    assert R.settle_bet_result("Batter HR", "Over", 0.5, a) == "win"
    assert R.settle_bet_result("Batter Total Hits", "Under", 0.5, a) == "loss"   # had 2 hits
    print("✓ settle_bet_result correctly returns real 'win'/'loss' strings for a normal, non-tied result")


def test_settle_bet_result_push_on_a_real_whole_number_line():
    # The real, important difference from grade_play: a genuine sportsbook line can be a whole
    # number (not this platform's own always-.5 lines), and an exact tie is a real push, not a
    # loss for either side.
    a = {"tb": 1}
    assert R.settle_bet_result("Batter Total Bases", "Over", 1, a) == "push"
    assert R.settle_bet_result("Batter Total Bases", "Under", 1, a) == "push"
    print("✓ settle_bet_result correctly identifies a real push on a whole-number line, for either side")


def test_settle_bet_result_void_when_player_has_no_stat_at_all():
    # The game is (by the caller's own responsibility) confirmed Final, but this player recorded
    # nothing for this stat category at all -- a real scratch/DNP, the standard real sportsbook
    # treatment is VOID, not a loss.
    assert R.settle_bet_result("Batter HR", "Over", 0.5, {"p_k": 6}) == "void"
    assert R.settle_bet_result("Batter HR", "Over", 0.5, None) == "void"
    assert R.settle_bet_result("Batter HR", "Over", 0.5, {}) == "void"
    print("✓ settle_bet_result returns 'void' (not silently a loss) when the player recorded nothing for this stat category")


def test_settle_bet_result_none_for_unknown_market_or_missing_line():
    assert R.settle_bet_result("Some Made Up Market", "Over", 0.5, {"hr": 1}) is None
    assert R.settle_bet_result("Batter HR", "Over", None, {"hr": 1}) is None
    print("✓ settle_bet_result returns None (an honest 'can't determine') for an unrecognized market or a missing line")


def test_settle_bet_result_hand_verified_full_vocabulary():
    # All four real result values, one hand-verified case each, in a single test for a clean
    # read of the full real vocabulary this function actually produces.
    assert R.settle_bet_result("Pitcher Strikeouts", "Over", 5.5, {"p_k": 8}) == "win"
    assert R.settle_bet_result("Pitcher Strikeouts", "Over", 5.5, {"p_k": 3}) == "loss"
    assert R.settle_bet_result("Pitcher Strikeouts", "Over", 6, {"p_k": 6}) == "push"
    assert R.settle_bet_result("Pitcher Strikeouts", "Over", 5.5, {"hr": 1}) == "void"
    print("✓ settle_bet_result's full real vocabulary (win/loss/push/void) hand-verified in one pass")


# ----------------------------------------------------------------- settle_moneyline_result
def test_settle_moneyline_result_win_and_loss():
    assert R.settle_moneyline_result("New York Yankees", "New York Yankees", "Boston Red Sox", 5, 3) == "win"
    assert R.settle_moneyline_result("Boston Red Sox", "New York Yankees", "Boston Red Sox", 5, 3) == "loss"
    print("✓ settle_moneyline_result correctly compares the logged team against the real final score")


def test_settle_moneyline_result_none_on_missing_or_tied_scores():
    assert R.settle_moneyline_result("New York Yankees", "New York Yankees", "Boston Red Sox", None, 3) is None
    assert R.settle_moneyline_result("New York Yankees", "New York Yankees", "Boston Red Sox", 4, 4) is None
    print("✓ settle_moneyline_result returns None (never a guess) for missing or genuinely tied scores")


def test_settle_moneyline_result_none_when_side_matches_neither_real_team():
    assert R.settle_moneyline_result("Chicago Cubs", "New York Yankees", "Boston Red Sox", 5, 3) is None
    print("✓ settle_moneyline_result returns None when the logged side doesn't match either real team — a genuine data mismatch, not resolved either way")


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


# ----------------------------------------------------------------- player_calibration
def _graded(player, pid, model_prob, hit, market="Batter Total Hits"):
    return {"Player": player, "PlayerId": pid, "Market": market, "Side": "Over",
           "ModelProb": model_prob, "Hit": hit}


def test_player_calibration_hand_verified_gap_and_sort_order():
    plays = (
        # Player A: model said 60% four times, actually hit 0/4 -- clearly overrated (gap +0.6)
        [_graded("A", 1, 0.6, False) for _ in range(4)]
        # Player B: model said 50% four times, actually hit 2/4 -- perfectly calibrated (gap 0.0)
        + [_graded("B", 2, 0.5, hit) for hit in (True, True, False, False)]
        # Player C: model said 30% four times, actually hit 4/4 -- clearly underrated (gap -0.7)
        + [_graded("C", 3, 0.3, True) for _ in range(4)]
    )
    result = R.player_calibration(plays, min_plays=4)
    assert [r["player"] for r in result] == ["A", "B", "C"]   # most overrated first
    assert result[0]["gap"] == 0.6 and result[0]["n"] == 4
    assert result[1]["gap"] == 0.0
    assert result[2]["gap"] == -0.7
    print("✓ player_calibration hand-verifies the exact gap for over-, correctly-, and under-rated players, sorted most-overrated first")


def test_player_calibration_excludes_below_min_plays():
    plays = [_graded("Thin Sample", 9, 0.7, False) for _ in range(3)]
    assert R.player_calibration(plays, min_plays=8) == []
    assert len(R.player_calibration(plays, min_plays=3)) == 1   # same data clears a lower floor
    print("✓ player_calibration excludes a player below min_plays entirely, rather than showing a misleadingly precise small-sample number")


def test_player_calibration_pools_across_markets_for_same_player():
    plays = [
        _graded("Multi", 5, 0.4, False, market="Batter HR"),
        _graded("Multi", 5, 0.6, True, market="Batter HR"),
        _graded("Multi", 5, 0.2, False, market="Batter Total Bases"),
        _graded("Multi", 5, 0.8, True, market="Batter Total Bases"),
    ]
    result = R.player_calibration(plays, min_plays=4)
    assert len(result) == 1   # one pooled entry, not split per market
    assert result[0]["n"] == 4
    assert result[0]["avg_model_prob"] == 0.5   # (0.4+0.6+0.2+0.8)/4
    assert result[0]["actual_hit_rate"] == 0.5   # 2/4 hit
    assert result[0]["gap"] == 0.0
    print("✓ player_calibration pools a player's plays across every market into one entry, matching how the real 'ban list' pattern itself works")


def test_player_calibration_excludes_unsettled_plays():
    plays = [_graded("Settled", 6, 0.5, True), _graded("Settled", 6, 0.5, False),
            _graded("Settled", 6, 0.5, None)]   # unsettled -- Hit is None
    result = R.player_calibration(plays, min_plays=2)
    assert result[0]["n"] == 2   # the unsettled play never counted
    print("✓ player_calibration excludes unsettled plays (Hit is None) from a player's own count")


def test_player_calibration_excludes_plays_missing_player_id():
    plays = [_graded("No ID", None, 0.5, True), _graded("No ID", None, 0.5, False)]
    assert R.player_calibration(plays, min_plays=1) == []
    print("✓ player_calibration skips plays with no PlayerId rather than grouping them together or crashing")


def test_player_calibration_empty_input_returns_empty_list():
    assert R.player_calibration([]) == []


# ----------------------------------------------------------------- _pearson_r
def test_pearson_r_perfect_positive_correlation():
    xs = [1, 2, 3, 4, 5]
    ys = [2, 4, 6, 8, 10]   # exactly ys = 2*xs
    assert abs(R._pearson_r(xs, ys) - 1.0) < 1e-9
    print("✓ _pearson_r correctly finds r=1.0 for a perfectly linear positive relationship")


def test_pearson_r_perfect_negative_correlation():
    xs = [1, 2, 3, 4, 5]
    ys = [10, 8, 6, 4, 2]   # exactly ys = 12 - 2*xs
    assert abs(R._pearson_r(xs, ys) - (-1.0)) < 1e-9
    print("✓ _pearson_r correctly finds r=-1.0 for a perfectly linear negative relationship")


def test_pearson_r_no_correlation():
    xs = [1, 2, 3, 4]
    ys = [5, 5, 5, 5]   # ys is constant -> undefined, not 0.0
    assert R._pearson_r(xs, ys) is None
    print("✓ _pearson_r reports undefined (None), not a fabricated 0.0, when one series has zero variance")


def test_pearson_r_hand_verified_partial_correlation():
    # Hand-verified: mean_x=3, mean_y=3.6, cov=sum((x-3)(y-3.6))=7.0, var_x=10, var_y=5.2,
    # r = 7.0 / sqrt(10*5.2) = 7.0/sqrt(52) = 0.97072...
    xs = [1, 2, 3, 4, 5]
    ys = [2, 3, 4, 4, 5]
    r = R._pearson_r(xs, ys)
    assert abs(r - 0.9707) < 0.001


def test_pearson_r_too_few_points():
    assert R._pearson_r([1], [1]) is None
    assert R._pearson_r([], []) is None


# ----------------------------------------------------------------- slate_chalk_correlation
def _chalk_point(date, fip, hit_rate):
    return {"date": date, "avg_starter_fip": fip, "hit_rate": hit_rate}


def test_slate_chalk_correlation_below_min_days_returns_no_number():
    points = [_chalk_point(f"2026-07-{d:02d}", 3.5, 0.5) for d in range(1, 5)]   # only 4 days
    result = R.slate_chalk_correlation(points, min_days=10)
    assert result["correlation"] is None
    assert result["n_days"] == 4
    assert "at least 10" in result["note"]
    print("✓ slate_chalk_correlation refuses to report a precise-looking r from too few days")


def test_slate_chalk_correlation_hand_verified_negative_relationship():
    # Lower avg_starter_fip (tougher pitching) paired with HIGHER hit_rate at every point --
    # exactly the direction the real hypothesis predicts, and real enough to detect.
    points = [
        _chalk_point("2026-07-01", 3.00, 0.68),
        _chalk_point("2026-07-02", 3.20, 0.64),
        _chalk_point("2026-07-03", 3.40, 0.60),
        _chalk_point("2026-07-04", 3.60, 0.58),
        _chalk_point("2026-07-05", 3.80, 0.55),
        _chalk_point("2026-07-06", 4.00, 0.52),
        _chalk_point("2026-07-07", 4.20, 0.50),
        _chalk_point("2026-07-08", 4.40, 0.47),
        _chalk_point("2026-07-09", 4.60, 0.44),
        _chalk_point("2026-07-10", 4.80, 0.40),
    ]
    result = R.slate_chalk_correlation(points, min_days=10)
    assert result["n_days"] == 10
    assert result["correlation"] < -0.9   # a strong, real negative relationship
    print("✓ slate_chalk_correlation correctly detects a strong negative relationship when the underlying data has one")


def test_slate_chalk_correlation_no_real_relationship():
    # hit_rate constant regardless of avg_starter_fip -> no real relationship, honestly None.
    points = [_chalk_point(f"2026-07-{d:02d}", 3.0 + d * 0.1, 0.55) for d in range(1, 11)]
    result = R.slate_chalk_correlation(points, min_days=10)
    assert result["correlation"] is None
    assert "undefined" in result["note"]


def test_slate_chalk_correlation_exactly_at_min_days_boundary():
    points = [_chalk_point(f"2026-07-{d:02d}", 3.0 + d * 0.05, 0.60 - d * 0.01) for d in range(1, 11)]
    result = R.slate_chalk_correlation(points, min_days=10)
    assert result["n_days"] == 10 and result["correlation"] is not None
    print("✓ slate_chalk_correlation reports a real number once min_days is exactly met, not just strictly exceeded")


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
                "stats": {"batting": {"hits": 2, "doubles": 1, "triples": 0, "homeRuns": 1,
                                      "strikeOuts": 1, "runs": 2, "rbi": 3}}}}},
        "away": {"players": {
            "ID2": {"person": {"id": 2, "fullName": "Ace"},
                    "stats": {"pitching": {"strikeOuts": 8, "baseOnBalls": 2, "inningsPitched": "6.2"}}}}}}}
    res = E.parse_boxscore_results(box)
    assert res[1]["hr"] == 1 and res[1]["tb"] == 6      # double(2)+HR(4)=6
    assert res[1]["hrr"] == 7                            # 2 hits + 2 runs + 3 rbi = 7
    assert res[2]["p_k"] == 8 and res[2]["p_outs"] == 20  # 6.2 IP -> 20 outs


def test_boxscore_parsing_hrr_missing_runs_rbi_defaults_to_zero():
    # A boxscore entry with a batting line but no runs/rbi keys at all (rare, but real API
    # responses aren't guaranteed to include every field) should default those two components
    # to 0 rather than crashing or leaving "hrr" unset entirely.
    box = {"teams": {"home": {"players": {
        "ID1": {"person": {"id": 1, "fullName": "Bench Bat"},
                "stats": {"batting": {"hits": 1, "doubles": 0, "triples": 0, "homeRuns": 0}}}}},
        "away": {"players": {}}}}
    res = E.parse_boxscore_results(box)
    assert res[1]["hrr"] == 1   # 1 hit + 0 runs + 0 rbi


def test_market_report_works_for_hits_runs_rbis():
    # Regression guard, same shape as the NFL Pass Yards test above: Batter Hits+Runs+RBIs plays
    # were being built and shown on the board (projections.build_best_bets) but had no MARKET_STAT
    # entry, so grade_play always returned None for them -- they silently never settled anywhere
    # results get graded (Retrospective, Model Dashboard's "tool's own picks" section), the exact
    # same silent-zero-graded-plays failure mode the NFL fix above already guards against.
    plays = [
        dict(Player="Big Night", PlayerId=1, Market="Batter Hits+Runs+RBIs", Side="Over", Line=1.5,
            ModelProb=0.4, Conviction=1.3),
        dict(Player="Quiet Night", PlayerId=2, Market="Batter Hits+Runs+RBIs", Side="Over", Line=1.5,
            ModelProb=0.35, Conviction=1.1),
    ]
    results = {1: {"hrr": 4}, 2: {"hrr": 1}, 55: {"hrr": 5}}
    rep = R.market_report(plays, results, "Batter Hits+Runs+RBIs", top_n=5, default_line=1.5)
    caught_names = [c["Player"] for c in rep["caught"]]
    assert "Big Night" in caught_names          # 4 > 1.5, cleared
    assert "Quiet Night" not in caught_names    # 1 < 1.5, didn't clear its own line
    assert rep["unprojected"] == 1              # player 55 (5 > 1.5) but wasn't projected
    print("✓ market_report (and grade_play/MARKET_STAT underneath it) works for Batter Hits+Runs+RBIs")


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
