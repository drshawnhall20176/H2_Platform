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


def test_settle_bet_result_pitcher_hits_allowed():
    # Regression guard for a real reported bug: "Pitcher Hits Allowed" bets were stuck showing
    # "game is Final but couldn't determine a real result" even for a genuinely completed game --
    # MARKET_STAT had no entry for this market AND the underlying p_h stat wasn't even being
    # computed by parse_boxscore_results at all. Both pieces needed fixing together; this
    # confirms the mapping side now resolves correctly in both directions.
    assert R.settle_bet_result("Pitcher Hits Allowed", "Over", 4.5, {"p_h": 6}) == "win"
    assert R.settle_bet_result("Pitcher Hits Allowed", "Over", 4.5, {"p_h": 3}) == "loss"
    assert R.settle_bet_result("Pitcher Hits Allowed", "Under", 4.5, {"p_h": 3}) == "win"
    print("✓ Pitcher Hits Allowed now grades correctly, reproducing and confirming the fix for "
         "the real reported Cal Quantrill bet")


def test_settle_bet_result_pitcher_earned_runs():
    # Regression guard for the SECOND real instance of this exact bug class: 4 real "Pitcher
    # Earned Runs" bets stuck as "game is Final but couldn't determine a real result," for the
    # identical reason -- no MARKET_STAT entry, AND p_er wasn't computed by parse_boxscore_
    # results at all, same as p_h before it.
    assert R.settle_bet_result("Pitcher Earned Runs", "Over", 2.5, {"p_er": 4}) == "win"
    assert R.settle_bet_result("Pitcher Earned Runs", "Over", 1.5, {"p_er": 1}) == "loss"
    assert R.settle_bet_result("Pitcher Earned Runs", "Under", 1.5, {"p_er": 1}) == "win"
    print("✓ Pitcher Earned Runs now grades correctly, reproducing and confirming the fix for "
         "the real reported Littell/Jones/Gusto bets")


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


# ----------------------------------------------------------------- settle_team_total_result
def test_settle_team_total_result_win_and_loss():
    assert R.settle_team_total_result("Over", 1.5, 3.0) == "win"
    assert R.settle_team_total_result("Over", 1.5, 1.0) == "loss"
    assert R.settle_team_total_result("Under", 1.5, 1.0) == "win"
    assert R.settle_team_total_result("Under", 1.5, 3.0) == "loss"
    print("✓ settle_team_total_result correctly compares real team runs against the logged line, both sides")


def test_settle_team_total_result_push_on_a_real_whole_number_line():
    # Same real distinction settle_bet_result's own push test makes: a genuine sportsbook total
    # line can be a whole number, and an exact tie is a real push, not a loss for either side.
    assert R.settle_team_total_result("Over", 2, 2.0) == "push"
    assert R.settle_team_total_result("Under", 2, 2.0) == "push"
    print("✓ settle_team_total_result correctly identifies a real push on a whole-number line, for either side")


def test_settle_team_total_result_none_for_missing_line_or_runs():
    assert R.settle_team_total_result("Over", None, 3.0) is None
    assert R.settle_team_total_result("Over", 1.5, None) is None
    print("✓ settle_team_total_result returns None (an honest 'can't determine') for a missing line or missing real runs")


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

# ----------------------------------------------------------------- fit_player_calibration / apply_player_calibration_correction
def test_fit_player_calibration_below_min_n_excludes_the_player():
    plays = [_graded("Thin Sample Guy", 1, 0.5, i % 2 == 0) for i in range(10)]   # 10 < PLAYER_CALIBRATION_MIN_N (20)
    result = R.fit_player_calibration(plays)
    assert 1 not in result
    print("✓ fit_player_calibration excludes a player with fewer than 20 real settled plays entirely")


def test_fit_player_calibration_recovers_a_known_injected_bias():
    # Real, exact, hand-verifiable construction: a player the model rates at 0.55 average, but
    # who has genuinely only hit 8 of 20 real times (0.40 actual) -- a real, deliberate +0.15 gap
    # (the model has been overrating him), at exactly the real floor (n=20, weight=0.5).
    plays = [_graded("Schwarber-like Guy", 99, 0.55, i < 8) for i in range(20)]
    result = R.fit_player_calibration(plays)
    rec = result[99]
    assert rec["n"] == 20
    assert abs(rec["raw_gap"] - 0.15) < 1e-9   # 0.55 - 0.40 = 0.15, exact
    assert abs(rec["weight"] - 0.5) < 1e-9     # exactly at the floor -> half strength, same real structure as market-level
    assert abs(rec["shrunk_gap"] - 0.075) < 1e-9   # 0.15 * 0.5
    print(f"✓ fit_player_calibration recovers a real, exact +0.15 gap for an overrated player at exactly the floor (shrunk to {rec['shrunk_gap']})")


def test_fit_player_calibration_negative_gap_for_an_underrated_player():
    # The mirror image: a player the model rates at 0.30 average, who's actually hit 18 of 20
    # real times (0.90 actual) -- a real, deliberate -0.60 gap (the model has been underrating him).
    plays = [_graded("Underrated Guy", 42, 0.30, i < 18) for i in range(20)]
    result = R.fit_player_calibration(plays)
    rec = result[42]
    assert abs(rec["raw_gap"] - (-0.60)) < 1e-9
    assert rec["shrunk_gap"] < 0, "an underrated player must show a real negative shrunk_gap"
    print("✓ fit_player_calibration correctly shows a real negative gap for a player the model has been underrating")


def test_fit_player_calibration_shrinks_more_at_a_higher_real_n():
    # Real, direct proof of the shrinkage structure itself: the SAME real +0.15 gap, but at a
    # much larger real n, must apply at MORE of its own real strength, not the same 50% every time.
    thin = [_graded("Same Player", 7, 0.55, i < 8) for i in range(20)]     # n=20 -> weight=0.5
    thick = [_graded("Same Player", 7, 0.55, i < 40) for i in range(100)]  # n=100 -> weight=100/120=0.833
    thin_rec = R.fit_player_calibration(thin)[7]
    thick_rec = R.fit_player_calibration(thick)[7]
    assert thick_rec["weight"] > thin_rec["weight"]
    assert abs(thick_rec["weight"] - round(100 / 120, 3)) < 1e-9   # weight is rounded to 3 decimals by the function itself
    print(f"✓ fit_player_calibration applies more of its own real strength as real n grows (n=20: {thin_rec['weight']}, n=100: {thick_rec['weight']})")


def test_fit_player_calibration_pools_across_markets_for_one_player():
    # Same real pooling player_calibration itself already does -- one player's own real gap
    # spans every market they've been graded in, not computed separately per market.
    plays = ([_graded("Multi-Market Guy", 5, 0.6, True, market="Batter HR") for _ in range(10)] +
            [_graded("Multi-Market Guy", 5, 0.6, False, market="Batter Total Hits") for _ in range(10)])
    result = R.fit_player_calibration(plays)
    assert result[5]["n"] == 20   # both markets' real plays pooled into one real player-level count
    print("✓ fit_player_calibration pools a player's real plays across every market, same as player_calibration itself")


def test_apply_player_calibration_correction_passthrough_when_none():
    assert R.apply_player_calibration_correction(0.45, None) == 0.45
    print("✓ apply_player_calibration_correction passes raw_prob straight through when no real player-specific correction exists yet")


def test_apply_player_calibration_correction_subtracts_a_positive_gap():
    correction = {"player": "X", "n": 20, "weight": 0.5, "raw_gap": 0.15, "shrunk_gap": 0.075}
    result = R.apply_player_calibration_correction(0.55, correction)
    assert abs(result - 0.475) < 1e-9   # 0.55 - 0.075
    print("✓ apply_player_calibration_correction correctly subtracts a real positive (overrated) gap, pulling the number down")


def test_apply_player_calibration_correction_adds_a_negative_gap():
    correction = {"player": "Y", "n": 20, "weight": 0.5, "raw_gap": -0.30, "shrunk_gap": -0.15}
    result = R.apply_player_calibration_correction(0.30, correction)
    assert abs(result - 0.45) < 1e-9   # 0.30 - (-0.15) = 0.45
    print("✓ apply_player_calibration_correction correctly adds when the real gap is negative (underrated), pushing the number up")


def test_apply_player_calibration_correction_clamps_to_the_real_valid_range():
    extreme = {"player": "Z", "n": 20, "weight": 1.0, "raw_gap": 0.9, "shrunk_gap": 0.9}
    assert R.apply_player_calibration_correction(0.10, extreme) >= 0.01   # would otherwise go negative
    print("✓ apply_player_calibration_correction clamps to [0.01, 0.99], same real floor/ceiling as every other probability")



# ----------------------------------------------------------------- fit_market_calibration / apply_calibration_correction
def test_fit_market_calibration_below_min_n_returns_none():
    plays = [_graded(f"P{i}", i, 0.5, i % 2 == 0) for i in range(50)]   # 50 < CALIBRATION_MIN_N (100)
    assert R.fit_market_calibration(plays) is None
    print("✓ fit_market_calibration returns None (an honest 'not enough real evidence yet') below CALIBRATION_MIN_N")


def _bucketed_calibration_plays(n_p_values=20, samples_per_p=10, bias=0.0, market="Batter HR"):
    """Real, EXACT synthetic construction for calibration-fit tests -- no randomness, no modulo-
    correlation artifacts. n_p_values distinct ModelProb values, evenly spaced 0.10-0.90; at each
    one, exactly round(samples_per_p * true_rate) of the samples are real hits, where true_rate =
    min(p + bias, 0.95). bias=0.0 means "already perfectly calibrated"; bias=0.10 means "the real
    hit rate deliberately runs 10 points hotter than the model says" -- an exact, hand-verifiable
    ground truth the fit's own recovered numbers can be checked against."""
    plays = []
    pid = 0
    for j in range(n_p_values):
        p = 0.10 + 0.8 * j / (n_p_values - 1)
        true_rate = min(p + bias, 0.95)
        n_hits = round(samples_per_p * true_rate)
        for k in range(samples_per_p):
            plays.append(_graded(f"P{pid}", pid, round(p, 4), k < n_hits, market=market))
            pid += 1
    return plays


def test_fit_market_calibration_recovers_a_known_injected_real_bias():
    # Real, exact construction (see _bucketed_calibration_plays' own docstring) so the recovered
    # numbers are hand-verifiable: the real hit rate is DELIBERATELY p + 0.10 (clamped at 0.95)
    # at every one of 20 distinct ModelProb values -- a genuine, systematic +10-point
    # underconfidence. The fit must recover a real, positive intercept close to that real bias,
    # not just run without crashing.
    plays = _bucketed_calibration_plays(n_p_values=20, samples_per_p=10, bias=0.10)
    fit = R.fit_market_calibration(plays)
    assert fit is not None and fit["n"] == 200
    assert 0.05 < fit["raw_intercept"] < 0.15, f"expected the raw fit to recover close to the real +0.10 bias, got {fit['raw_intercept']}"
    assert 0.8 < fit["raw_slope"] < 1.3   # a real slope near 1 -- the bias here is a flat shift, not a scaling error
    print(f"✓ fit_market_calibration recovers a real, deliberately injected +0.10 calibration bias (raw_intercept={fit['raw_intercept']})")


def test_fit_market_calibration_shrinks_toward_identity_at_the_floor():
    # At exactly CALIBRATION_MIN_N (100) real plays, the shrinkage weight must be 0.5 -- HALF the
    # fitted correction's own strength, per this function's own documented n/(n+prior) formula
    # with prior=100. Proven directly, not just asserted from the formula being present.
    plays = _bucketed_calibration_plays(n_p_values=20, samples_per_p=5, bias=0.10)
    fit = R.fit_market_calibration(plays)
    assert fit is not None and fit["n"] == 100
    assert abs(fit["weight"] - 0.5) < 0.001
    # the REAL (shrunk) intercept should be exactly half the RAW (unshrunk) one at this exact n
    assert abs(fit["intercept"] - fit["raw_intercept"] * 0.5) < 0.01
    print(f"✓ at exactly CALIBRATION_MIN_N, the fitted correction is shrunk to half its own raw strength (weight={fit['weight']})")


def test_fit_market_calibration_well_calibrated_data_yields_near_identity():
    # When the model is ALREADY well-calibrated (real hit rate matches real ModelProb exactly, no
    # systematic gap), the fit should recover something close to slope=1, intercept=0 -- i.e.
    # correctly conclude "no real correction needed" rather than inventing one from noise.
    plays = _bucketed_calibration_plays(n_p_values=20, samples_per_p=15, bias=0.0)
    fit = R.fit_market_calibration(plays)
    assert fit is not None
    assert abs(fit["raw_intercept"]) < 0.05
    assert abs(fit["raw_slope"] - 1.0) < 0.15
    print(f"✓ fit_market_calibration correctly recovers a near-identity correction when the model is already well-calibrated (raw_intercept={fit['raw_intercept']})")


def test_fit_market_calibration_excludes_unsettled_plays_from_n():
    settled = _bucketed_calibration_plays(n_p_values=15, samples_per_p=10, bias=0.0)   # 150 real, spread across real ModelProb values
    unsettled = [_graded(f"U{i}", 1000 + i, 0.5, None) for i in range(500)]            # Hit=None, plenty of them
    fit = R.fit_market_calibration(settled + unsettled)
    assert fit is not None and fit["n"] == 150   # only the real settled plays counted, not the 500 unsettled ones
    print("✓ fit_market_calibration counts only real settled plays (Hit is not None) toward n, ignoring unsettled ones entirely")


def test_apply_calibration_correction_passthrough_when_correction_is_none():
    assert R.apply_calibration_correction(0.42, None) == 0.42
    print("✓ apply_calibration_correction passes raw_prob straight through unchanged when no real correction exists yet")


def test_apply_calibration_correction_passthrough_when_prob_is_none():
    fit = {"slope": 1.2, "intercept": 0.1}
    assert R.apply_calibration_correction(None, fit) is None
    print("✓ apply_calibration_correction passes a missing raw_prob straight through as None, never fabricating a number")


def test_apply_calibration_correction_applies_the_real_linear_transform():
    fit = {"slope": 1.0, "intercept": 0.05}
    assert abs(R.apply_calibration_correction(0.30, fit) - 0.35) < 1e-9
    print("✓ apply_calibration_correction applies the exact stored slope/intercept transform")


def test_apply_calibration_correction_clamps_to_the_real_valid_range():
    extreme = {"slope": 3.0, "intercept": 0.5}   # a deliberately extreme, unrealistic correction
    assert R.apply_calibration_correction(0.90, extreme) <= 0.99   # would otherwise exceed 1.0
    assert R.apply_calibration_correction(0.01, {"slope": 1.0, "intercept": -0.5}) >= 0.01   # would otherwise go negative
    print("✓ apply_calibration_correction clamps to [0.01, 0.99] — a correction can nudge a number, never claim false certainty")


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


# ----------------------------------------------------------------- rank_within_market / catch_rate_by_rank
def _play(player, pid, model_prob, market="Batter HR"):
    return {"Player": player, "PlayerId": pid, "Market": market, "Side": "Over", "ModelProb": model_prob}


# ----------------------------------------------------------------- l5_l10_hit_rate
def _game(hr=0, total_bases=0, hits=0, strikeouts=0, hrr=None):
    return {"hr": hr, "total_bases": total_bases, "hits": hits, "strikeouts": strikeouts,
           "hrr": hrr if hrr is not None else hits}


def test_l5_l10_hit_rate_uses_the_real_end_of_the_list_as_most_recent():
    # get_hitter_recent_games' own real order is ASCENDING (oldest first) -- the most recent 5
    # real games are the LAST 5 in the list, not the first 5. Exact, hand-verifiable construction:
    # the first 5 games (oldest) never clear the HR line; the last 5 (most recent) always do.
    games = [_game(hr=0) for _ in range(5)] + [_game(hr=1) for _ in range(5)]
    l5, l10 = R.l5_l10_hit_rate(games, "Batter HR", 0.5)
    assert l5 == 1.0    # the real most-recent 5 (all HR=1) clear a 0.5 line every time
    assert l10 == 0.5   # all 10 real games: 5 clear, 5 don't
    print("✓ l5_l10_hit_rate correctly reads the real most-recent games from the END of the ascending-order list")


def test_l5_l10_hit_rate_is_market_and_line_aware_not_a_fixed_shortcut():
    # THE real point of this function, not Dinger Engine's own fixed ">=1 hit" shortcut: the
    # SAME 10 real games read completely differently depending on which market/line is actually
    # being checked.
    games = [_game(total_bases=1) for _ in range(5)] + [_game(total_bases=3) for _ in range(5)]
    l5_tb15, _ = R.l5_l10_hit_rate(games, "Batter Total Bases", 1.5)   # needs >1.5 total bases
    assert l5_tb15 == 1.0   # the real most-recent 5 games all had 3 total bases, clearing 1.5
    l5_tb35, _ = R.l5_l10_hit_rate(games, "Batter Total Bases", 3.5)   # needs >3.5 -- none clear
    assert l5_tb35 == 0.0
    print("✓ l5_l10_hit_rate is genuinely market/line-aware — the same real games read differently at different lines")


def test_l5_l10_hit_rate_none_with_fewer_than_5_real_games():
    games = [_game(hr=1) for _ in range(3)]
    l5, l10 = R.l5_l10_hit_rate(games, "Batter HR", 0.5)
    assert l5 is None and l10 is None
    print("✓ l5_l10_hit_rate is honestly None (not a padded average) with fewer than 5 real games")


def test_l5_l10_hit_rate_l5_real_but_l10_none_with_seven_real_games():
    games = [_game(hr=1) for _ in range(7)]
    l5, l10 = R.l5_l10_hit_rate(games, "Batter HR", 0.5)
    assert l5 == 1.0
    assert l10 is None
    print("✓ l5_l10_hit_rate computes L5 correctly even when L10 honestly can't yet, with 7 real games")


def test_l5_l10_hit_rate_none_for_a_market_with_no_real_stat_key():
    games = [_game(hr=1) for _ in range(10)]
    l5, l10 = R.l5_l10_hit_rate(games, "Pitcher Strikeouts", 5.5)   # pitcher market -- no batter-side equivalent
    assert l5 is None and l10 is None
    print("✓ l5_l10_hit_rate returns honest None for a market it doesn't cover (pitcher markets), never guesses")


def test_l5_l10_hit_rate_none_with_no_real_games_at_all():
    l5, l10 = R.l5_l10_hit_rate([], "Batter HR", 0.5)
    assert l5 is None and l10 is None
    print("✓ l5_l10_hit_rate handles zero real games gracefully, no crash")


def test_rank_within_market_ranks_by_modelprob_descending():
    plays = [_play("A", 1, 0.30), _play("B", 2, 0.55), _play("C", 3, 0.42)]
    ranks = R.rank_within_market(plays)
    assert ranks[2] == (1, 3)   # highest ModelProb (0.55) -> real rank 1 of 3
    assert ranks[3] == (2, 3)
    assert ranks[1] == (3, 3)   # lowest ModelProb -> real rank 3 of 3
    print("✓ rank_within_market ranks by ModelProb descending, same convention market_report already uses")


def test_rank_within_market_ranks_each_market_independently():
    plays = [_play("A", 1, 0.80, market="Batter HR"), _play("B", 2, 0.20, market="Batter HR"),
            _play("C", 3, 0.10, market="Pitcher Strikeouts")]   # only real play in ITS OWN market
    ranks = R.rank_within_market(plays)
    assert ranks[3] == (1, 1)   # rank 1 of 1 within its own market, despite the lowest raw ModelProb overall
    print("✓ rank_within_market ranks each real market separately, not pooled across markets")


def test_catch_rate_by_rank_below_min_n_bucket_has_honest_none_not_absence():
    # A REAL, CONFIRMED FIX, not the original design: the original version silently DROPPED a
    # thin bucket entirely, indistinguishable from a bucket with truly zero real plays. Confirmed
    # directly from a real report: Rank 1/2/3 are structurally a ONE-PER-DAY-PER-MARKET event, so
    # a real 10-day scoped window can never produce more than 10 real Rank-1 plays -- permanently
    # below a min_n=20 floor no matter how much real backfill happens, which meant a scoped chart
    # showed one giant bar and nothing else. Every real bucket now always appears, with its own
    # real n; hit_rate is None (not a fabricated number) when n < min_n.
    graded = [dict(_graded(f"P{i}", i, 0.5, i % 2 == 0), Rank=1) for i in range(5)]   # only 5, below min_n=20
    result = R.catch_rate_by_rank(graded)
    assert len(result) == 6, "all 6 real RANK_BUCKETS must always appear, not just the ones that clear the floor"
    r1 = next(b for b in result if b["bucket"] == "Rank 1")
    assert r1["n"] == 5 and r1["hit_rate"] is None, "a real, thin bucket reports its own real n, honestly None for hit_rate"
    empty = next(b for b in result if b["bucket"] == "Rank 2")
    assert empty["n"] == 0 and empty["hit_rate"] is None, "a bucket with truly zero real plays also reports honestly"
    print("✓ catch_rate_by_rank always returns all 6 real buckets, with an honest None (not a fabricated number "
         "or silent absence) for any bucket below its real min_n floor")


def test_catch_rate_by_rank_computes_the_real_hit_rate_per_bucket():
    # Real, exact, hand-verifiable construction: rank 1 plays hit 80% of the time (16/20), rank 2
    # plays hit 40% of the time (8/20) -- two real, genuinely different buckets.
    r1 = [dict(_graded(f"R1_{i}", i, 0.6, i < 16), Rank=1) for i in range(20)]
    r2 = [dict(_graded(f"R2_{i}", 100 + i, 0.5, i < 8), Rank=2) for i in range(20)]
    result = R.catch_rate_by_rank(r1 + r2, min_n=20)
    by_bucket = {b["bucket"]: b for b in result}
    assert by_bucket["Rank 1"]["n"] == 20 and by_bucket["Rank 1"]["hit_rate"] == 0.8
    assert by_bucket["Rank 2"]["n"] == 20 and by_bucket["Rank 2"]["hit_rate"] == 0.4
    print("✓ catch_rate_by_rank computes the exact real hit rate per rank bucket (Rank 1: 0.8, Rank 2: 0.4)")


def test_catch_rate_by_rank_pools_the_real_tail_bands():
    # Ranks 6-10 is a real, pooled band, not five separate individual-rank buckets.
    plays = []
    for rank in range(6, 11):
        for i in range(4):   # 5 ranks * 4 = 20 total real plays in this one pooled band
            plays.append(dict(_graded(f"R{rank}_{i}", rank * 10 + i, 0.4, i < 2), Rank=rank))
    result = R.catch_rate_by_rank(plays, min_n=20)
    by_bucket = {b["bucket"]: b for b in result}
    assert by_bucket["Ranks 6-10"]["n"] == 20 and by_bucket["Ranks 6-10"]["hit_rate"] == 0.5
    assert by_bucket["Rank 1"]["n"] == 0   # a real, honestly-empty bucket, still present in the output
    print("✓ catch_rate_by_rank correctly pools the real tail bands (Ranks 6-10) into one bucket")


def test_catch_rate_by_rank_excludes_plays_with_no_real_rank():
    graded = [dict(_graded(f"P{i}", i, 0.5, True)) for i in range(30)]   # NO Rank key at all -- e.g. logged before this feature existed
    result = R.catch_rate_by_rank(graded, min_n=20)
    assert all(b["n"] == 0 and b["hit_rate"] is None for b in result), (
        "plays with no real Rank must be excluded from every real bucket's own count, never treated as rank-less zeros")
    print("✓ catch_rate_by_rank excludes real plays with no rank data from every bucket, rather than guessing")


def test_catch_rate_by_rank_narrows_to_one_market_when_asked():
    hr = [dict(_graded(f"HR{i}", i, 0.5, True, market="Batter HR"), Rank=1) for i in range(20)]
    ks = [dict(_graded(f"K{i}", 100 + i, 0.5, False, market="Pitcher Strikeouts"), Rank=1) for i in range(20)]
    result = R.catch_rate_by_rank(hr + ks, market="Batter HR", min_n=20)
    by_bucket = {b["bucket"]: b for b in result}
    assert by_bucket["Rank 1"]["hit_rate"] == 1.0   # only the real HR plays counted
    print("✓ catch_rate_by_rank correctly narrows to one real market when asked")


def test_catch_rate_by_conviction_tier_catches_the_real_reported_pattern():
    # ADDED DIRECTLY ON REQUEST, a real, confirmed fix for a real, repeated community
    # frustration: "research is shit i was gunna pick bobby witt Jr and josh bell both hit but
    # research said helllll no." Real, exact, hand-verifiable construction: the model's own real
    # passes (Conviction < 1.2x, below the real grading floor) hit 70% of the time (14/20) --
    # meaningfully close to its own top tier (Conviction >= 1.75x), which hits 80% (16/20). This
    # is exactly the honest evidence this function exists to surface either way.
    top = [dict(_graded(f"T{i}", i, 0.6, i < 16), Conviction=1.9) for i in range(20)]
    passed = [dict(_graded(f"P{i}", 100 + i, 0.5, i < 14), Conviction=0.9) for i in range(20)]
    result = R.catch_rate_by_conviction_tier(top + passed, min_n=20)
    by_tier = {b["tier"]: b for b in result}
    assert len(result) == 4, "all 4 real CONVICTION_TIER_BUCKETS must always appear"
    top_tier = next(b for t, b in by_tier.items() if t.startswith("≥1.75"))
    pass_tier = next(b for t, b in by_tier.items() if t.startswith("<1.2"))
    assert top_tier["n"] == 20 and top_tier["hit_rate"] == 0.8
    assert pass_tier["n"] == 20 and pass_tier["hit_rate"] == 0.7
    print("✓ catch_rate_by_conviction_tier correctly surfaces how often the model's own real passes actually hit, alongside its top tier")


def test_catch_rate_by_conviction_tier_below_min_n_bucket_has_honest_none_not_absence():
    # Same real, deliberate honesty catch_rate_by_rank's own equivalent test already locks in --
    # a real, thin tier must still appear, with its own real n, honestly None for hit_rate.
    graded = [dict(_graded(f"P{i}", i, 0.5, i % 2 == 0), Conviction=2.0) for i in range(5)]   # only 5, below min_n=20
    result = R.catch_rate_by_conviction_tier(graded)
    assert len(result) == 4
    top_tier = next(b for b in result if b["tier"].startswith("≥1.75"))
    assert top_tier["n"] == 5 and top_tier["hit_rate"] is None
    empty_tier = next(b for b in result if b["tier"].startswith("1.4"))
    assert empty_tier["n"] == 0 and empty_tier["hit_rate"] is None
    print("✓ catch_rate_by_conviction_tier always returns all 4 real tiers, with an honest None for any tier below its real min_n floor")


def test_catch_rate_by_conviction_tier_excludes_plays_with_no_real_conviction():
    graded = [dict(_graded(f"P{i}", i, 0.5, True)) for i in range(30)]   # NO Conviction key at all
    result = R.catch_rate_by_conviction_tier(graded, min_n=20)
    assert all(b["n"] == 0 and b["hit_rate"] is None for b in result), (
        "plays with no real Conviction must be excluded from every real tier's own count, never guessed into a tier")
    print("✓ catch_rate_by_conviction_tier excludes real plays with no conviction data from every tier, rather than guessing")


def test_catch_rate_by_conviction_tier_narrows_to_one_market_when_asked():
    hr = [dict(_graded(f"HR{i}", i, 0.5, True, market="Batter HR"), Conviction=2.0) for i in range(20)]
    ks = [dict(_graded(f"K{i}", 100 + i, 0.5, False, market="Pitcher Strikeouts"), Conviction=2.0) for i in range(20)]
    result = R.catch_rate_by_conviction_tier(hr + ks, market="Batter HR", min_n=20)
    top_tier = next(b for b in result if b["tier"].startswith("≥1.75"))
    assert top_tier["hit_rate"] == 1.0   # only the real HR plays counted
    print("✓ catch_rate_by_conviction_tier correctly narrows to one real market when asked")


def test_catch_rate_by_conviction_tier_boundaries_are_lo_inclusive_hi_exclusive():
    # A real, direct boundary check, matching grade_slate's own real "lo <= conviction < hi"
    # convention exactly -- a play sitting exactly on a real boundary (1.2, 1.4, 1.75) must land
    # in the tier that boundary value STARTS, never the one it ends, and never both or neither.
    plays = [
        dict(_graded("A", 1, 0.5, True), Conviction=1.2),    # exactly on the 1.2 boundary -> "1.2-1.4" tier
        dict(_graded("B", 2, 0.5, True), Conviction=1.4),    # exactly on the 1.4 boundary -> "1.4-1.75" tier
        dict(_graded("C", 3, 0.5, True), Conviction=1.75),   # exactly on the 1.75 boundary -> top tier
    ]
    result = R.catch_rate_by_conviction_tier(plays, min_n=1)
    by_tier = {b["tier"]: b["n"] for b in result}
    lean_tier = next(t for t in by_tier if t.startswith("1.2"))
    strong_tier = next(t for t in by_tier if t.startswith("1.4"))
    top_tier = next(t for t in by_tier if t.startswith("≥1.75"))
    assert by_tier[lean_tier] == 1 and by_tier[strong_tier] == 1 and by_tier[top_tier] == 1
    print("✓ catch_rate_by_conviction_tier's own boundaries are correctly lo-inclusive/hi-exclusive, matching grade_slate's own real convention exactly")


# ----------------------------------------------------------------- catch_rate_by_blowout_margin
def test_catch_rate_by_blowout_margin_catches_the_real_reported_pattern():
    # ADDED DIRECTLY ON REQUEST, the real validation half of a real, two-part fix for a real,
    # repeated community pain point: "blowouts causing failed parlays" / "players forget how to
    # play after halftime." Real, exact, hand-verifiable construction: competitive games (real
    # margin < 10) hit 65% of the time (13/20), blowout games (real margin >= 10) hit only 35%
    # of the time (7/20) -- exactly the real pattern this function exists to check for.
    competitive = [dict(_graded(f"C{i}", i, 0.5, i < 13), GameMargin=6.0) for i in range(20)]
    blowout = [dict(_graded(f"B{i}", 100 + i, 0.5, i < 7), GameMargin=18.0) for i in range(20)]
    result = R.catch_rate_by_blowout_margin(competitive + blowout, min_n=20)
    by_bucket = {b["bucket"]: b for b in result}
    assert len(result) == 2
    comp_bucket = next(v for k, v in by_bucket.items() if k.startswith("Competitive"))
    blow_bucket = next(v for k, v in by_bucket.items() if k.startswith("Blowout"))
    assert comp_bucket["n"] == 20 and comp_bucket["hit_rate"] == 0.65
    assert blow_bucket["n"] == 20 and blow_bucket["hit_rate"] == 0.35
    print("✓ catch_rate_by_blowout_margin correctly surfaces the real reported pattern -- lower real hit rate in real blowout games")


def test_catch_rate_by_blowout_margin_threshold_is_genuinely_adjustable():
    # A real, direct check that threshold is a genuine, live parameter, not a decorative one --
    # the SAME real plays must land in different real buckets depending on the real threshold
    # passed, proving a caller can actually test whether 10.0 is the right real number.
    plays = [dict(_graded(f"P{i}", i, 0.5, True), GameMargin=12.0) for i in range(20)]
    at_10 = R.catch_rate_by_blowout_margin(plays, threshold=10.0, min_n=20)
    at_15 = R.catch_rate_by_blowout_margin(plays, threshold=15.0, min_n=20)
    blow_at_10 = next(b for b in at_10 if b["bucket"].startswith("Blowout"))
    blow_at_15 = next(b for b in at_15 if b["bucket"].startswith("Blowout"))
    assert blow_at_10["n"] == 20   # margin 12 clears a 10.0 real threshold -> counted as blowout
    assert blow_at_15["n"] == 0    # the SAME real margin 12 does NOT clear a 15.0 real threshold
    print("✓ catch_rate_by_blowout_margin's threshold is a genuine, live parameter -- the same real plays land differently at different real thresholds")


def test_catch_rate_by_blowout_margin_below_min_n_bucket_has_honest_none_not_absence():
    # Same real, deliberate honesty catch_rate_by_rank/catch_rate_by_conviction_tier already
    # establish -- a real, thin bucket must still appear, with its own real n, honestly None.
    plays = [dict(_graded(f"P{i}", i, 0.5, True), GameMargin=15.0) for i in range(5)]   # only 5, below min_n=20
    result = R.catch_rate_by_blowout_margin(plays)
    assert len(result) == 2
    blow_bucket = next(b for b in result if b["bucket"].startswith("Blowout"))
    assert blow_bucket["n"] == 5 and blow_bucket["hit_rate"] is None
    comp_bucket = next(b for b in result if b["bucket"].startswith("Competitive"))
    assert comp_bucket["n"] == 0 and comp_bucket["hit_rate"] is None
    print("✓ catch_rate_by_blowout_margin always returns both real buckets, with an honest None for any bucket below its real min_n floor")


def test_catch_rate_by_blowout_margin_excludes_plays_with_no_real_game_margin():
    # A real play from a sport with no get_game_margin capability yet, or a game not yet
    # reviewed through Retrospective's own grading flow, must be excluded, never guessed into
    # either real bucket.
    plays = [dict(_graded(f"P{i}", i, 0.5, True)) for i in range(30)]   # NO GameMargin key at all
    result = R.catch_rate_by_blowout_margin(plays, min_n=20)
    assert all(b["n"] == 0 and b["hit_rate"] is None for b in result), (
        "plays with no real GameMargin must be excluded from every real bucket's own count, never guessed")
    print("✓ catch_rate_by_blowout_margin excludes real plays with no game-margin data from every bucket, rather than guessing")


def test_catch_rate_by_blowout_margin_narrows_to_one_market_when_asked():
    pts = [dict(_graded(f"P{i}", i, 0.5, True, market="Points"), GameMargin=18.0) for i in range(20)]
    reb = [dict(_graded(f"R{i}", 100 + i, 0.5, False, market="Rebounds"), GameMargin=18.0) for i in range(20)]
    result = R.catch_rate_by_blowout_margin(pts + reb, market="Points", min_n=20)
    blow_bucket = next(b for b in result if b["bucket"].startswith("Blowout"))
    assert blow_bucket["hit_rate"] == 1.0   # only the real Points plays counted
    print("✓ catch_rate_by_blowout_margin correctly narrows to one real market when asked")


def test_catch_rate_by_blowout_margin_boundary_is_lo_inclusive_hi_exclusive():
    # A real, direct boundary check -- a game sitting EXACTLY on the real threshold must land in
    # the Blowout bucket (which the threshold value STARTS), never Competitive.
    plays = [dict(_graded(f"P{i}", i, 0.5, True), GameMargin=10.0) for i in range(20)]   # exactly on the default 10.0 threshold
    result = R.catch_rate_by_blowout_margin(plays, threshold=10.0, min_n=20)
    blow_bucket = next(b for b in result if b["bucket"].startswith("Blowout"))
    comp_bucket = next(b for b in result if b["bucket"].startswith("Competitive"))
    assert blow_bucket["n"] == 20 and comp_bucket["n"] == 0
    print("✓ catch_rate_by_blowout_margin's own threshold boundary is correctly lo-inclusive for Blowout, matching every other bucketed function's convention")


def test_catch_rate_by_blowout_margin_real_exact_tie_counts_as_competitive():
    # A real, exact-tie game (margin 0.0, before overtime) must count as genuinely competitive,
    # not be silently excluded the way "no real data" would be -- 0.0 is a real, valid margin.
    plays = [dict(_graded(f"P{i}", i, 0.5, True), GameMargin=0.0) for i in range(20)]
    result = R.catch_rate_by_blowout_margin(plays, min_n=20)
    comp_bucket = next(b for b in result if b["bucket"].startswith("Competitive"))
    assert comp_bucket["n"] == 20 and comp_bucket["hit_rate"] == 1.0
    print("✓ catch_rate_by_blowout_margin correctly counts a real, exact-tie game as competitive, not confused with missing data")


# ----------------------------------------------------------------- catch_rate_by_team_role_in_blowout
def test_catch_rate_by_team_role_in_blowout_uses_the_real_reported_example():
    # EXTENDED DIRECTLY ON REQUEST, using the EXACT real, live example a real user reported: LV
    # Aces 66 @ NY Liberty 99, a real 33-point final. Real, exact, hand-verifiable construction:
    # losing-side players (Aces, TeamMargin=-33) hit 30% (6/20); winning-side players (Liberty,
    # TeamMargin=+33) hit 55% (11/20) -- a real, different rate for each real side, exactly the
    # real distinction one combined GameMargin bucket couldn't have shown.
    losing_side = [dict(_graded(f"Aces{i}", i, 0.5, i < 6), TeamMargin=-33.0) for i in range(20)]
    winning_side = [dict(_graded(f"Lib{i}", 100 + i, 0.5, i < 11), TeamMargin=33.0) for i in range(20)]
    result = R.catch_rate_by_team_role_in_blowout(losing_side + winning_side, min_n=20)
    assert len(result) == 3, "all three real buckets must always appear"
    by_bucket = {b["bucket"]: b for b in result}
    losing = next(v for k, v in by_bucket.items() if k.startswith("Blowout — losing"))
    winning = next(v for k, v in by_bucket.items() if k.startswith("Blowout — winning"))
    assert losing["n"] == 20 and losing["hit_rate"] == 0.30
    assert winning["n"] == 20 and winning["hit_rate"] == 0.55
    print("✓ catch_rate_by_team_role_in_blowout correctly separates real losing-side vs. real winning-side hit rates, using the real reported LV/NY example")


def test_catch_rate_by_team_role_in_blowout_signs_are_genuinely_opposite_not_confused():
    # A real, direct check that a real losing-side play and a real winning-side play from the
    # SAME real game land in genuinely different real buckets, never the same one.
    plays = [
        dict(_graded("Loser", 1, 0.5, True), TeamMargin=-33.0),
        dict(_graded("Winner", 2, 0.5, True), TeamMargin=33.0),
    ]
    result = R.catch_rate_by_team_role_in_blowout(plays, min_n=1)
    by_bucket = {b["bucket"]: b["n"] for b in result}
    losing_n = next(n for k, n in by_bucket.items() if k.startswith("Blowout — losing"))
    winning_n = next(n for k, n in by_bucket.items() if k.startswith("Blowout — winning"))
    assert losing_n == 1 and winning_n == 1
    print("✓ catch_rate_by_team_role_in_blowout correctly keeps a real losing-side play and a real winning-side play in genuinely different buckets")


def test_catch_rate_by_team_role_in_blowout_competitive_bucket_for_close_games():
    plays = [dict(_graded(f"P{i}", i, 0.5, True), TeamMargin=3.0) for i in range(20)]
    result = R.catch_rate_by_team_role_in_blowout(plays, threshold=10.0, min_n=20)
    comp = next(b for b in result if b["bucket"].startswith("Competitive"))
    losing = next(b for b in result if b["bucket"].startswith("Blowout — losing"))
    winning = next(b for b in result if b["bucket"].startswith("Blowout — winning"))
    assert comp["n"] == 20 and losing["n"] == 0 and winning["n"] == 0
    print("✓ catch_rate_by_team_role_in_blowout correctly counts a close, real 3-point margin as competitive, not either blowout bucket")


def test_catch_rate_by_team_role_in_blowout_boundaries_are_symmetric_and_inclusive():
    # A real, direct boundary check -- a real margin sitting EXACTLY on the real threshold
    # (either sign) must land in its own real blowout bucket, never Competitive.
    plays = [
        dict(_graded("AtLosingEdge", 1, 0.5, True), TeamMargin=-10.0),   # exactly -threshold
        dict(_graded("AtWinningEdge", 2, 0.5, True), TeamMargin=10.0),   # exactly +threshold
    ]
    result = R.catch_rate_by_team_role_in_blowout(plays, threshold=10.0, min_n=1)
    by_bucket = {b["bucket"]: b["n"] for b in result}
    losing_n = next(n for k, n in by_bucket.items() if k.startswith("Blowout — losing"))
    winning_n = next(n for k, n in by_bucket.items() if k.startswith("Blowout — winning"))
    comp_n = next(n for k, n in by_bucket.items() if k.startswith("Competitive"))
    assert losing_n == 1 and winning_n == 1 and comp_n == 0
    print("✓ catch_rate_by_team_role_in_blowout's own boundaries are symmetric and inclusive on both real sides")


def test_catch_rate_by_team_role_in_blowout_threshold_is_genuinely_adjustable():
    plays = [dict(_graded(f"P{i}", i, 0.5, True), TeamMargin=-12.0) for i in range(20)]
    at_10 = R.catch_rate_by_team_role_in_blowout(plays, threshold=10.0, min_n=20)
    at_15 = R.catch_rate_by_team_role_in_blowout(plays, threshold=15.0, min_n=20)
    losing_at_10 = next(b for b in at_10 if b["bucket"].startswith("Blowout — losing"))["n"]
    losing_at_15 = next(b for b in at_15 if b["bucket"].startswith("Blowout — losing"))["n"]
    assert losing_at_10 == 20   # -12 clears a real 10.0 threshold -> counted as a real blowout
    assert losing_at_15 == 0    # the SAME real -12 does NOT clear a real 15.0 threshold
    print("✓ catch_rate_by_team_role_in_blowout's threshold is a genuine, live parameter, same as catch_rate_by_blowout_margin's own")


def test_catch_rate_by_team_role_in_blowout_below_min_n_bucket_has_honest_none():
    plays = [dict(_graded(f"P{i}", i, 0.5, True), TeamMargin=-33.0) for i in range(5)]   # only 5, below min_n=20
    result = R.catch_rate_by_team_role_in_blowout(plays)
    losing = next(b for b in result if b["bucket"].startswith("Blowout — losing"))
    assert losing["n"] == 5 and losing["hit_rate"] is None
    print("✓ catch_rate_by_team_role_in_blowout returns an honest None for a real bucket below its own min_n floor")


def test_catch_rate_by_team_role_in_blowout_excludes_plays_with_no_real_team_margin():
    plays = [dict(_graded(f"P{i}", i, 0.5, True)) for i in range(30)]   # NO TeamMargin key at all
    result = R.catch_rate_by_team_role_in_blowout(plays, min_n=20)
    assert all(b["n"] == 0 and b["hit_rate"] is None for b in result), (
        "real plays with no real TeamMargin must be excluded from every real bucket, never guessed")
    print("✓ catch_rate_by_team_role_in_blowout excludes real plays with no team-margin data from every bucket")


def test_catch_rate_by_team_role_in_blowout_narrows_to_one_market_when_asked():
    pts = [dict(_graded(f"P{i}", i, 0.5, True, market="Points"), TeamMargin=-33.0) for i in range(20)]
    reb = [dict(_graded(f"R{i}", 100 + i, 0.5, False, market="Rebounds"), TeamMargin=-33.0) for i in range(20)]
    result = R.catch_rate_by_team_role_in_blowout(pts + reb, market="Points", min_n=20)
    losing = next(b for b in result if b["bucket"].startswith("Blowout — losing"))
    assert losing["hit_rate"] == 1.0   # only the real Points plays counted
    print("✓ catch_rate_by_team_role_in_blowout correctly narrows to one real market when asked")


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


# ----------------------------------------------------------------- explain_miss
def test_explain_miss_none_row_means_not_projected():
    assert R.explain_miss(None, "Batter HR") == (
        "Not in a projected lineup (late change, call-up, or pinch-hit) — the model "
        "never saw this player.")
    print("✓ explain_miss handles a player the model never projected at all")


def test_explain_miss_pitcher_strikeouts_catchable_vs_variance():
    catchable = R.explain_miss({"_opp_k": 0.25, "Proj K": 6.0}, "Pitcher Strikeouts")
    assert catchable.startswith("Catchable")
    assert "25%" in catchable and "6.0" in catchable
    variance = R.explain_miss({"_opp_k": 0.18, "Proj K": 3.5}, "Pitcher Strikeouts")
    assert variance.startswith("Genuine over")
    assert catchable != variance
    print("✓ explain_miss correctly distinguishes catchable vs genuine-variance for Pitcher Strikeouts")


def test_explain_miss_batter_hr_unchanged_behavior():
    # Protects the pre-existing HR branch against regression from extending this function.
    catchable = R.explain_miss({"Due": 0.03, "Barrel%": 0.12, "ISO": 0.220, "HR": 15}, "Batter HR")
    assert catchable.startswith("Catchable") and "barrel" in catchable.lower()
    variance = R.explain_miss({"Due": 0.0, "ISO": 0.100, "HR": 3}, "Batter HR")
    assert variance.startswith("Genuine long shot")
    print("✓ explain_miss's original Batter HR behavior is unchanged")


def test_explain_miss_strikeouts_catchable_vs_variance():
    # Regression guard for the actual fix requested: real, distinguishing reasoning for a
    # Batter Strikeouts miss, using the batter's own real season K rate and the opposing
    # pitcher's own real allowed K rate -- the same numbers already surfacing in "Why" text.
    catchable = R.explain_miss({"_season_k_rate": 0.28, "_opp_k_allowed": 0.25}, "Batter Strikeouts")
    assert catchable.startswith("Catchable")
    assert "28%" in catchable and "25%" in catchable
    variance = R.explain_miss({"_season_k_rate": 0.10, "_opp_k_allowed": 0.15}, "Batter Strikeouts")
    assert variance.startswith("Genuine variance")
    assert "10%" in variance
    assert catchable != variance
    print("✓ explain_miss gives real, distinguishing reasoning for Batter Strikeouts misses")


def test_explain_miss_walks_catchable_vs_variance():
    catchable = R.explain_miss({"_season_bb_rate": 0.14, "_opp_bb_allowed": 0.10}, "Batter Walks")
    assert catchable.startswith("Catchable")
    assert "14%" in catchable
    variance = R.explain_miss({"_season_bb_rate": 0.04, "_opp_bb_allowed": 0.07}, "Batter Walks")
    assert variance.startswith("Genuine variance")
    assert catchable != variance
    print("✓ explain_miss gives real, distinguishing reasoning for Batter Walks misses")


def test_explain_miss_stolen_bases_catchable_vs_variance():
    catchable = R.explain_miss({"_season_sb": 15, "_season_pa_for_sb": 350}, "Batter Stolen Bases")
    assert catchable.startswith("Catchable")
    assert "15 SB" in catchable and "350 PA" in catchable
    variance = R.explain_miss({"_season_sb": 1, "_season_pa_for_sb": 300}, "Batter Stolen Bases")
    assert variance.startswith("Genuine variance")
    assert "1 SB" in variance
    assert catchable != variance
    print("✓ explain_miss gives real, distinguishing reasoning for Batter Stolen Bases misses")


def test_explain_miss_unhandled_market_is_honest_not_silently_wrong():
    # The actual safety fix found while extending this function: the old unconditional fallback
    # would have silently applied HR-specific reasoning (ISO, home run count) to ANY unmatched
    # market -- nonsensical for something like Batter RBIs. Confirms the real fix: an honest
    # "not built yet" message instead, and confirms it does NOT leak ISO/HR-style text.
    result = R.explain_miss({"ISO": 0.089, "HR": 2}, "Batter RBIs")
    assert "not built" in result.lower() or "not wired" in result.lower() or "market yet" in result.lower()
    assert "ISO" not in result and "HR" not in result and "power" not in result.lower()
    print("✓ explain_miss gives an honest 'not built yet' message for an unhandled market, "
         "never silently wrong HR-style reasoning")


def test_explain_miss_every_market_stat_key_covers_returns_something_honest():
    # Broader sweep: every market retro.py actually grades should get either a real, specific
    # explanation or the honest fallback -- never an exception, never silently wrong text.
    for market in R.MARKET_STAT:
        result = R.explain_miss({}, market)
        assert isinstance(result, str) and len(result) > 0
    print("✓ explain_miss returns a real string for every market MARKET_STAT covers, no exceptions")


# ----------------------------------------------------------------- explain_team_environment
def test_explain_team_environment_catches_the_real_reported_pattern():
    # ADDED DIRECTLY ON REQUEST, a real, confirmed fix for a real, repeated community
    # frustration: "it's not even the main players... it's all the other people hitting."
    # Simulates exactly that real shape: the missed player's own real Line was 1.5 hits, he got
    # 0 -- but two real teammates on the same real team, same real game, same real market
    # combined for 4 real hits against their own real, lower 1.0 lines, so the team's real
    # combined output (4) genuinely cleared the real combined expectation (3.5). Actual is
    # reused directly from each play, the exact same field grade_slate already attaches and a
    # person already sees on screen -- not a separately-passed results dict.
    missed = {"PlayerId": 1, "Team": "Red Sox", "Game": "Yankees @ Red Sox",
             "Market": "Batter Total Hits", "Line": 1.5, "Hit": False, "Actual": 0}
    teammate_a = {"PlayerId": 2, "Team": "Red Sox", "Game": "Yankees @ Red Sox",
                 "Market": "Batter Total Hits", "Line": 1.0, "Hit": True, "Actual": 2}
    teammate_b = {"PlayerId": 3, "Team": "Red Sox", "Game": "Yankees @ Red Sox",
                 "Market": "Batter Total Hits", "Line": 1.0, "Hit": True, "Actual": 2}
    slate_plays = [missed, teammate_a, teammate_b]

    result = R.explain_team_environment(missed, slate_plays)
    assert result is not None
    assert result["expected_team_total"] == 3.5   # 1.5 + 1.0 + 1.0
    assert result["actual_team_total"] == 4.0      # 0 + 2 + 2
    assert result["environment_matched"] is True
    assert result["n_teammates"] == 3
    print("✓ explain_team_environment correctly identifies the real 'wrong player, right environment' pattern")


def test_explain_team_environment_honest_when_environment_also_missed():
    # The genuine opposite case: the team as a whole was also cold, not just the missed player
    # -- environment_matched must honestly be False, not defaulted to True.
    missed = {"PlayerId": 1, "Team": "Marlins", "Game": "Marlins @ Braves",
             "Market": "Batter Total Hits", "Line": 1.5, "Hit": False, "Actual": 0}
    teammate = {"PlayerId": 2, "Team": "Marlins", "Game": "Marlins @ Braves",
               "Market": "Batter Total Hits", "Line": 1.0, "Hit": False, "Actual": 0}
    slate_plays = [missed, teammate]

    result = R.explain_team_environment(missed, slate_plays)
    assert result is not None
    assert result["expected_team_total"] == 2.5
    assert result["actual_team_total"] == 0.0
    assert result["environment_matched"] is False
    print("✓ explain_team_environment honestly reports a genuinely cold team environment, not a false positive")


def test_explain_team_environment_none_when_not_a_real_miss():
    # A play that hit, or hasn't graded at all (Hit is None), has nothing to diagnose here --
    # this is a MISS-specific diagnostic, not a general team-total calculator.
    hit_play = {"PlayerId": 1, "Team": "Cubs", "Game": "Cubs @ Cardinals",
               "Market": "Batter Total Hits", "Line": 1.5, "Hit": True, "Actual": 2}
    assert R.explain_team_environment(hit_play, [hit_play]) is None

    ungraded_play = {**hit_play, "Hit": None, "Actual": None}
    assert R.explain_team_environment(ungraded_play, [ungraded_play]) is None
    print("✓ explain_team_environment correctly returns None for a real hit or an ungraded play, not a fabricated diagnosis")


def test_explain_team_environment_none_for_a_market_with_no_real_stat_mapping():
    # A moneyline/fight-winner pick has no real MARKET_STAT entry to sum real results from --
    # an honest None, not a crash or a fabricated zero.
    missed = {"PlayerId": None, "Team": "Yankees", "Game": "Yankees @ Red Sox",
             "Market": "Moneyline", "Line": None, "Hit": False, "Actual": None}
    assert R.explain_team_environment(missed, [missed]) is None
    print("✓ explain_team_environment honestly returns None for a market with no real actual-stat mapping")


def test_explain_team_environment_none_when_game_not_final_yet():
    # No real actual result exists anywhere in the group yet -- an honest None, not a
    # fabricated 0-vs-0 "environment matched" false positive.
    missed = {"PlayerId": 1, "Team": "Astros", "Game": "Astros @ Rangers",
             "Market": "Batter Total Hits", "Line": 1.5, "Hit": False, "Actual": None}
    result = R.explain_team_environment(missed, [missed])   # no real Actual anywhere yet
    assert result is None
    print("✓ explain_team_environment honestly returns None rather than a false 'environment matched' when no real result exists yet")


def test_explain_team_environment_does_not_leak_across_different_teams_or_games():
    # A real, direct check that the grouping is genuinely scoped -- a play from a DIFFERENT
    # real team, or the SAME team on a different real date/game, must never be pulled into the
    # comparison just because the market name matches.
    missed = {"PlayerId": 1, "Team": "Mets", "Game": "Mets @ Phillies",
             "Market": "Batter Total Hits", "Line": 1.5, "Hit": False, "Actual": 0}
    different_team = {"PlayerId": 2, "Team": "Phillies", "Game": "Mets @ Phillies",
                      "Market": "Batter Total Hits", "Line": 1.0, "Hit": True, "Actual": 3}
    different_game = {"PlayerId": 3, "Team": "Mets", "Game": "Mets @ Braves",
                      "Market": "Batter Total Hits", "Line": 1.0, "Hit": True, "Actual": 3}
    slate_plays = [missed, different_team, different_game]

    result = R.explain_team_environment(missed, slate_plays)
    assert result["n_teammates"] == 1   # only the missed player themselves -- no real teammates this game
    assert result["expected_team_total"] == 1.5
    assert result["actual_team_total"] == 0.0
    print("✓ explain_team_environment correctly scopes the real comparison to the same team AND same game, never leaking across either")


def test_explain_team_environment_reuses_grade_slates_own_actual_not_a_separate_recompute():
    # A REAL, DIRECT CHECK of the actual design decision this function makes: it must read the
    # real "Actual" field grade_slate already attached to each play, not silently re-derive its
    # own number some other way. A deliberately wrong/mismatched Actual on a teammate proves
    # this function trusts and uses exactly that value, not a value from anywhere else.
    missed = {"PlayerId": 1, "Team": "Padres", "Game": "Padres @ Giants",
             "Market": "Batter Total Hits", "Line": 1.5, "Hit": False, "Actual": 0}
    teammate = {"PlayerId": 2, "Team": "Padres", "Game": "Padres @ Giants",
               "Market": "Batter Total Hits", "Line": 1.0, "Hit": True, "Actual": 99}
    result = R.explain_team_environment(missed, [missed, teammate])
    assert result["actual_team_total"] == 99.0   # 0 + 99 -- confirms the real teammate's own real Actual was used directly
    print("✓ explain_team_environment genuinely reuses each play's own real, already-attached Actual field, not a separate recompute")

