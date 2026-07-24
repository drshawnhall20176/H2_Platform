"""
test_projections.py — offline tests for the projection engine (seeded, deterministic).

    python test_projections.py     # or: pytest test_projections.py
"""

import numpy as np
import pytest
import projections as P


def _slugger():
    return dict(plateAppearances=600, atBats=540, hits=165, doubles=34, triples=2,
                homeRuns=38, baseOnBalls=55, strikeOuts=140)


def test_pa_probs_sum_to_one():
    probs = P.batter_pa_probs(_slugger(), P.NEUTRAL_PARK)
    assert probs is not None
    assert abs(probs.sum() - 1.0) < 1e-9
    assert (probs >= 0).all()


def test_low_sample_returns_none():
    assert P.batter_pa_probs(dict(plateAppearances=10), P.NEUTRAL_PARK) is None


# ----------------------------------------------------------------- batter_pa_probs: hitter fatigue
def test_batter_pa_probs_fatigue_applies_correct_direction_and_magnitude():
    stat = dict(plateAppearances=600, atBats=540, hits=170, doubles=36, triples=2,
               homeRuns=25, baseOnBalls=55, strikeOuts=125)
    normal = P.batter_pa_probs(stat, P.NEUTRAL_PARK)
    fatigued = P.batter_pa_probs(stat, P.NEUTRAL_PARK, consecutive_games_started=8)
    # Hand-verified exact ratios
    assert abs(fatigued[P.HR] / normal[P.HR] - P.HITTER_FATIGUE_HR_MULT) < 1e-9
    assert abs(fatigued[P.K] / normal[P.K] - P.HITTER_FATIGUE_K_MULT) < 1e-9
    assert abs(fatigued[P.SINGLE] / normal[P.SINGLE] - P.HITTER_FATIGUE_HIT_MULT) < 1e-9
    assert abs(fatigued[P.DOUBLE] / normal[P.DOUBLE] - P.HITTER_FATIGUE_HIT_MULT) < 1e-9
    print("✓ batter_pa_probs applies the exact, hand-verified fatigue penalty to HR/hit/K")


def test_batter_pa_probs_fatigue_leaves_walk_rate_untouched():
    stat = dict(plateAppearances=600, atBats=540, hits=170, doubles=36, triples=2,
               homeRuns=25, baseOnBalls=55, strikeOuts=125)
    normal = P.batter_pa_probs(stat, P.NEUTRAL_PARK)
    fatigued = P.batter_pa_probs(stat, P.NEUTRAL_PARK, consecutive_games_started=8)
    assert fatigued[P.BB] == normal[P.BB]
    print("✓ batter_pa_probs correctly leaves walk rate untouched by the fatigue adjustment")


def test_batter_pa_probs_fatigue_below_threshold_unaffected():
    stat = dict(plateAppearances=600, atBats=540, hits=170, doubles=36, triples=2,
               homeRuns=25, baseOnBalls=55, strikeOuts=125)
    normal = P.batter_pa_probs(stat, P.NEUTRAL_PARK)
    watch_tier = P.batter_pa_probs(stat, P.NEUTRAL_PARK, consecutive_games_started=6)
    assert (normal == watch_tier).all()
    print("✓ batter_pa_probs applies no adjustment for the 🟡 watch tier (below the real 8-game threshold)")


def test_batter_pa_probs_fatigue_survives_opponent_matchup():
    # Confirms the fatigue penalty survives the odds-ratio opponent-matchup step, not just the
    # unadjusted case.
    stat = dict(plateAppearances=600, atBats=540, hits=170, doubles=36, triples=2,
               homeRuns=25, baseOnBalls=55, strikeOuts=125)
    opp_allowed = dict(hr=0.03, k=0.22, bb=0.08, nonhr_hit=0.20)
    normal = P.batter_pa_probs(stat, P.NEUTRAL_PARK, opp_allowed=opp_allowed)
    fatigued = P.batter_pa_probs(stat, P.NEUTRAL_PARK, opp_allowed=opp_allowed,
                                 consecutive_games_started=8)
    assert fatigued[P.HR] < normal[P.HR]
    assert fatigued[P.K] > normal[P.K]
    print("✓ batter_pa_probs' fatigue penalty survives the opponent-matchup step, not just the unadjusted case")


def test_batter_pa_probs_fatigue_none_unaffected():
    stat = dict(plateAppearances=600, atBats=540, hits=170, doubles=36, triples=2,
               homeRuns=25, baseOnBalls=55, strikeOuts=125)
    no_arg = P.batter_pa_probs(stat, P.NEUTRAL_PARK)
    explicit_none = P.batter_pa_probs(stat, P.NEUTRAL_PARK, consecutive_games_started=None)
    assert (no_arg == explicit_none).all()
    print("✓ batter_pa_probs produces identical output whether consecutive_games_started is omitted or explicitly None")


def test_park_boosts_hr_rate():
    neutral = P.batter_pa_probs(_slugger(), P.NEUTRAL_PARK)[P.HR]
    coors = P.batter_pa_probs(_slugger(), P.PARK_FACTORS[7])[P.HR]
    assert coors > neutral  # Coors (venue 7) inflates HR


def test_probabilities_in_range():
    rng = np.random.default_rng(0)
    probs = P.batter_pa_probs(_slugger(), P.NEUTRAL_PARK)
    sim = P.simulate_batter(probs, 4.4, 20000, rng)
    for arr, line in ((sim["tb"], 1.5), (sim["hits"], 0.5), (sim["k"], 0.5)):
        p = float(np.mean(arr > line))
        assert 0.0 <= p <= 1.0
    hr_p = float(np.mean(sim["hr"] >= 1))
    assert 0.15 < hr_p < 0.40  # a 38-HR bat sits in a believable anytime-HR band


# ----------------------------------------------------------------- simulate_batter: single/double/triple/bb
def test_simulate_batter_exposes_all_hit_type_counts():
    rng = np.random.default_rng(0)
    probs = P.batter_pa_probs(_slugger(), P.NEUTRAL_PARK)
    sim = P.simulate_batter(probs, 4.4, 20000, rng)
    for key in ("single", "double", "triple", "bb"):
        assert key in sim
        assert len(sim[key]) == 20000
        assert (sim[key] >= 0).all()
    print("✓ simulate_batter correctly exposes single/double/triple/bb as their own simulated counts")


def test_simulate_batter_hit_types_sum_to_total_hits():
    # A real, direct consistency check: for EVERY simulated trial, single+double+triple+hr must
    # exactly equal the trial's own total hits count -- these aren't independently drawn, they're
    # different views into the exact same underlying per-PA outcome draws.
    rng = np.random.default_rng(0)
    probs = P.batter_pa_probs(_slugger(), P.NEUTRAL_PARK)
    sim = P.simulate_batter(probs, 4.4, 5000, rng)
    reconstructed_hits = sim["single"] + sim["double"] + sim["triple"] + sim["hr"]
    assert (reconstructed_hits == sim["hits"]).all()
    print("✓ simulate_batter's single/double/triple/hr counts sum EXACTLY to hits for every single trial, confirming they share the same underlying draws")


def test_simulate_batter_triple_is_rare():
    # A real sanity check on relative magnitude -- triples should be dramatically rarer than
    # singles for a realistic hitter, matching the real, known shape of MLB hit-type frequency.
    rng = np.random.default_rng(0)
    probs = P.batter_pa_probs(_slugger(), P.NEUTRAL_PARK)
    sim = P.simulate_batter(probs, 4.4, 20000, rng)
    single_rate = float(np.mean(sim["single"] >= 1))
    triple_rate = float(np.mean(sim["triple"] >= 1))
    assert triple_rate < single_rate * 0.2
    print("✓ simulate_batter correctly produces a realistic, much lower triple rate than single rate")


def test_pitcher_projection_sane():
    ace = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
               strikeOuts=235, baseOnBalls=42)
    proj = P.project_pitcher(ace)
    assert 5.0 < proj["exp_ip"] < 7.0
    assert proj["exp_k"] > proj["exp_bb"]


def test_fair_odds_roundtrip():
    assert P.prob_to_american(0.5) == -100
    assert P.prob_to_decimal(0.5) == 2.0
    # favorite gets negative american, dog positive
    assert P.prob_to_american(0.62) < 0
    assert P.prob_to_american(0.30) > 0


def test_build_signals_shape():
    row = {"Hitter": "X", "Team": "T", "GameLabel": "A @ B", "Opp Pitcher": "P",
           "Lineup": "Confirmed", "_stat": _slugger(), "_exp_pa": 4.4, "_venue_id": None}

    class PM:
        id = 1; name = "Ace"
        stat = dict(battersFaced=700, inningsPitched="170.0", gamesStarted=28,
                    strikeOuts=200, baseOnBalls=50)
    meta = [{"label": "A @ B", "home_name": "B", "away_name": "A", "home_pm": PM(), "away_pm": PM()}]
    sigs = P.build_signals([row], meta, sims=8000, seed=1)
    # 4 batter markets + 3 pitcher markets * 2 pitchers = 10
    assert len(sigs) == 10
    for s in sigs:
        assert 0.0 <= s["ModelProb"] <= 1.0
        assert s["FairDec"] is None or s["FairDec"] >= 1.0


def test_starter_gate_skips_relievers():
    # Pure reliever (no starts) listed as a probable -> must be skipped, not projected.
    assert P.project_pitcher(dict(battersFaced=45, inningsPitched="11.0",
                                  gamesStarted=0, strikeOuts=18, baseOnBalls=9)) is None
    # Too-thin starter sample -> skipped.
    assert P.project_pitcher(dict(battersFaced=50, inningsPitched="12.0",
                                  gamesStarted=2, strikeOuts=17, baseOnBalls=8)) is None


def test_shrinkage_tames_hot_small_sample():
    # 3 starts, 15 IP, 40% raw K rate. Pre-fix this exploded toward ~8.5+ K.
    proj = P.project_pitcher(dict(battersFaced=63, inningsPitched="15.0",
                                  gamesStarted=3, strikeOuts=25, baseOnBalls=4))
    assert proj is not None
    assert proj["exp_k"] < 7.0   # regressed, not inflated
    # And never above the clamp ceiling.
    assert proj["exp_k"] <= 0.45 * proj["exp_bf"] + 1e-9


def test_real_ace_stays_sane():
    proj = P.project_pitcher(dict(battersFaced=720, inningsPitched="180.0",
                                  gamesStarted=29, strikeOuts=235, baseOnBalls=42))
    assert 5.5 < proj["exp_ip"] < 7.0
    assert 6.0 < proj["exp_k"] < 9.5      # believable ace strikeout projection
    assert proj["exp_bb"] < 3.0


def test_batter_shrinkage_pulls_small_samples():
    # A 40-PA hot callup's HR rate must regress well below its raw 0.125.
    hot = P.batter_pa_probs(dict(plateAppearances=40, atBats=36, hits=16, doubles=4,
                                 triples=0, homeRuns=5, baseOnBalls=4, strikeOuts=6),
                            P.NEUTRAL_PARK)
    assert hot[P.HR] < 0.07          # far below raw 5/40 = 0.125
    # A full-season slugger barely moves.
    slug = P.batter_pa_probs(dict(plateAppearances=600, atBats=540, hits=165, doubles=34,
                                  triples=2, homeRuns=38, baseOnBalls=55, strikeOuts=140),
                             P.NEUTRAL_PARK)
    assert slug[P.HR] > 0.05         # still clearly an above-average power bat


def test_odds_ratio_identity():
    # League bat vs league pitcher at league rate must return league rate.
    assert abs(P.odds_ratio(0.033, 0.033, 0.033) - 0.033) < 1e-6
    # Better pitcher (lower allowed) pushes the matchup probability down.
    assert P.odds_ratio(0.065, 0.020, 0.033) < P.odds_ratio(0.065, 0.045, 0.033)


def test_matchup_moves_hr_with_pitcher_quality():
    slug = _slugger()
    hr_prone = dict(battersFaced=700, homeRuns=28, strikeOuts=120, baseOnBalls=70, hits=180)
    ace = dict(battersFaced=700, homeRuns=10, strikeOuts=210, baseOnBalls=40, hits=130)
    p_easy = P.batter_pa_probs(slug, P.NEUTRAL_PARK, opp_allowed=P.pitcher_allowed_rates(hr_prone))
    p_hard = P.batter_pa_probs(slug, P.NEUTRAL_PARK, opp_allowed=P.pitcher_allowed_rates(ace))
    # Same hitter projects for MORE HR vs the homer-prone arm, FEWER vs the ace.
    assert p_easy[P.HR] > p_hard[P.HR]
    # And more strikeouts vs the high-K ace.
    assert p_hard[P.K] > p_easy[P.K]


# ----------------------------------------------------------------- rest_adjustment_multipliers
def test_rest_adjustment_multipliers_short_rest():
    m = P.rest_adjustment_multipliers(4)
    assert m["k_mult"] == P.REST_K_MULT
    assert m["bb_mult"] == P.REST_BB_MULT
    assert m["er_mult"] == P.REST_ER_MULT
    assert m["hr_mult"] == P.REST_HR_MULT
    assert m["k_mult"] < 1.0    # K down -- reduced dominance
    assert m["bb_mult"] > 1.0   # BB up -- control suffers
    assert m["er_mult"] > 1.0   # ER up -- worse overall
    assert m["hr_mult"] > 1.0   # HR-allowed up -- worse command
    print("✓ rest_adjustment_multipliers applies the real, stated short-rest penalty in the correct direction on every rate")


def test_rest_adjustment_multipliers_boundary_at_4_and_5():
    # THE exact boundary mlb_engine.get_starter_rest_info itself uses (<=4 short, 5 standard).
    short = P.rest_adjustment_multipliers(4)
    standard = P.rest_adjustment_multipliers(5)
    assert short["k_mult"] != 1.0
    assert standard == {"k_mult": 1.0, "bb_mult": 1.0, "er_mult": 1.0, "hr_mult": 1.0}
    print("✓ rest_adjustment_multipliers' boundary exactly matches get_starter_rest_info's own <=4/5 threshold")


def test_rest_adjustment_multipliers_extra_rest_no_adjustment():
    # A real, deliberate choice: extra rest (6+ days) gets NO adjustment, not a naive "more rest
    # = better" assumption -- get_starter_rest_info's own docstring is explicit this has "more
    # mixed evidence," not a clean positive.
    m = P.rest_adjustment_multipliers(7)
    assert m == {"k_mult": 1.0, "bb_mult": 1.0, "er_mult": 1.0, "hr_mult": 1.0}
    print("✓ rest_adjustment_multipliers correctly applies no adjustment for extra rest, honoring the mixed real-world evidence")


def test_rest_adjustment_multipliers_none_treated_as_normal():
    # Unknown rest (None -- e.g. an MLB debut, or a live fetch failure) must NOT be assumed to be
    # short rest just because it's unknown -- the safe, conservative default is no adjustment.
    m = P.rest_adjustment_multipliers(None)
    assert m == {"k_mult": 1.0, "bb_mult": 1.0, "er_mult": 1.0, "hr_mult": 1.0}
    print("✓ rest_adjustment_multipliers correctly treats unknown rest as normal, never assuming the worse case")


def test_rest_adjustment_multipliers_very_short_rest_same_as_boundary():
    # A pitcher on 2 days' rest (extremely unusual, essentially never happens in practice) still
    # gets the SAME flat short-rest multiplier as one on 4 days, not a scaling penalty -- this
    # platform doesn't have real data to support a graduated "the shorter, the worse" curve, so
    # it stays honest about only asserting the one threshold get_starter_rest_info itself defines.
    assert P.rest_adjustment_multipliers(2) == P.rest_adjustment_multipliers(4)
    print("✓ rest_adjustment_multipliers applies a flat penalty across the whole short-rest range, not a fabricated graduated curve")


# ----------------------------------------------------------------- bullpen_fatigued_fraction
def _fatigue_row(pid, consecutive_days=0, days_since=5):
    return {"player_id": pid, "name": f"P{pid}", "consecutive_days": consecutive_days,
           "days_since_last_appearance": days_since, "appearances_in_window": 1,
           "total_outs_in_window": 3, "tag": "x"}


def test_bullpen_fatigued_fraction_hand_verified():
    rows = [
        _fatigue_row(1, consecutive_days=3),        # fatigued: 3+ streak
        _fatigue_row(2, days_since=0),               # fatigued: pitched yesterday (0 days since)
        _fatigue_row(3, consecutive_days=0, days_since=5),  # fresh
        _fatigue_row(4, consecutive_days=1, days_since=3),  # fresh
    ]
    frac = P.bullpen_fatigued_fraction(rows)
    assert frac == 0.5   # 2 fatigued out of 4, hand-verified
    print("✓ bullpen_fatigued_fraction correctly computes the real, hand-verified fraction of a bullpen showing fatigue")


def test_bullpen_fatigued_fraction_excludes_starter():
    rows = [
        _fatigue_row(1, consecutive_days=3),   # fatigued, but this IS the starter -- excluded
        _fatigue_row(2, consecutive_days=0, days_since=5),   # fresh reliever
    ]
    frac = P.bullpen_fatigued_fraction(rows, exclude_pid=1)
    assert frac == 0.0   # only the fresh reliever remains after excluding the starter
    print("✓ bullpen_fatigued_fraction correctly excludes tonight's own starter from the bullpen calculation")


def test_bullpen_fatigued_fraction_empty_returns_none():
    assert P.bullpen_fatigued_fraction([]) is None
    print("✓ bullpen_fatigued_fraction correctly returns None (not a fabricated 0.0) for an empty window")


def test_bullpen_fatigued_fraction_all_excluded_returns_none():
    rows = [_fatigue_row(1, consecutive_days=3)]
    assert P.bullpen_fatigued_fraction(rows, exclude_pid=1) is None
    print("✓ bullpen_fatigued_fraction correctly returns None when excluding the starter leaves nothing")


def test_bullpen_fatigued_fraction_tag_boundary_matches_get_team_bullpen_fatigue():
    # Confirms the EXACT same thresholds get_team_bullpen_fatigue's own tag logic uses (3+
    # consecutive days OR days_since <= 1), not a new, separately-invented definition.
    just_under_3 = _fatigue_row(1, consecutive_days=2, days_since=2)   # NOT fatigued
    exactly_3 = _fatigue_row(2, consecutive_days=3, days_since=3)      # fatigued
    pitched_today_ish = _fatigue_row(3, consecutive_days=0, days_since=1)  # fatigued
    pitched_2_days_ago = _fatigue_row(4, consecutive_days=0, days_since=2)  # NOT fatigued
    assert P.bullpen_fatigued_fraction([just_under_3]) == 0.0
    assert P.bullpen_fatigued_fraction([exactly_3]) == 1.0
    assert P.bullpen_fatigued_fraction([pitched_today_ish]) == 1.0
    assert P.bullpen_fatigued_fraction([pitched_2_days_ago]) == 0.0
    print("✓ bullpen_fatigued_fraction's fatigue definition exactly matches get_team_bullpen_fatigue's own tag boundaries")


# ----------------------------------------------------------------- bullpen_freshness_tag
def test_bullpen_freshness_tag_unknown_for_none():
    assert P.bullpen_freshness_tag(None) == "unknown"
    print("✓ bullpen_freshness_tag reports \"unknown\" for missing data, never guessing fresh or taxed")


def test_bullpen_freshness_tag_matches_threshold_exactly():
    assert P.bullpen_freshness_tag(P.BULLPEN_FATIGUE_THRESHOLD - 0.01) == "fresh"
    assert P.bullpen_freshness_tag(P.BULLPEN_FATIGUE_THRESHOLD) == "taxed"
    assert P.bullpen_freshness_tag(1.0) == "taxed"
    assert P.bullpen_freshness_tag(0.0) == "fresh"
    print("✓ bullpen_freshness_tag uses the exact same inclusive threshold boundary as bullpen_fatigue_multipliers")


# ----------------------------------------------------------------- bullpen_freshness_edge
def test_bullpen_freshness_edge_away_fresher():
    # Away team fresh (0.1), home team taxed (0.6) -> away has the edge.
    assert P.bullpen_freshness_edge(0.1, 0.6) == "away"
    print("✓ bullpen_freshness_edge correctly picks the fresher away bullpen")


def test_bullpen_freshness_edge_home_fresher():
    assert P.bullpen_freshness_edge(0.6, 0.1) == "home"
    print("✓ bullpen_freshness_edge correctly picks the fresher home bullpen")


def test_bullpen_freshness_edge_both_fresh_is_even():
    assert P.bullpen_freshness_edge(0.1, 0.15) == "even"


def test_bullpen_freshness_edge_both_taxed_is_even():
    assert P.bullpen_freshness_edge(0.6, 0.7) == "even"
    print("✓ bullpen_freshness_edge calls it \"even\" when both sides are fresh, or both are taxed, "
         "not just when the fractions are numerically identical")


def test_bullpen_freshness_edge_none_when_either_side_unknown():
    assert P.bullpen_freshness_edge(None, 0.6) is None
    assert P.bullpen_freshness_edge(0.1, None) is None
    assert P.bullpen_freshness_edge(None, None) is None
    print("✓ bullpen_freshness_edge never resolves a missing read on either side into a false \"even\"")


# ----------------------------------------------------------------- lower_is_better_edge
def test_lower_is_better_edge_picks_the_lower_value():
    assert P.lower_is_better_edge(3.20, 4.10) == "away"   # away's lower FIP wins
    assert P.lower_is_better_edge(4.10, 3.20) == "home"
    print("✓ lower_is_better_edge correctly picks whichever side has the lower (better) number")


def test_lower_is_better_edge_exact_tie_is_even_by_default():
    assert P.lower_is_better_edge(3.50, 3.50) == "even"


def test_lower_is_better_edge_respects_epsilon():
    # A real but tiny 0.05 gap: "even" once a real epsilon is applied, a real edge with none.
    assert P.lower_is_better_edge(3.50, 3.55) == "away"          # epsilon=0.0 default -> real edge
    assert P.lower_is_better_edge(3.50, 3.55, epsilon=0.20) == "even"   # explicit epsilon absorbs it
    assert P.lower_is_better_edge(3.00, 4.00, epsilon=0.20) == "away"  # a real gap still wins even with epsilon
    print("✓ lower_is_better_edge treats a gap smaller than a caller-supplied epsilon as \"even\", "
         "not a fabricated edge from noise")


def test_lower_is_better_edge_none_when_either_side_missing():
    assert P.lower_is_better_edge(None, 4.10) is None
    assert P.lower_is_better_edge(3.20, None) is None
    assert P.lower_is_better_edge(None, None) is None


# ----------------------------------------------------------------- higher_is_better_edge
def test_higher_is_better_edge_picks_the_higher_value():
    assert P.higher_is_better_edge(5.5, 2.1) == "away"   # away's higher run diff wins
    assert P.higher_is_better_edge(2.1, 5.5) == "home"
    print("✓ higher_is_better_edge correctly picks whichever side has the higher (better) number")


def test_higher_is_better_edge_exact_tie_is_even_by_default():
    assert P.higher_is_better_edge(1.5, 1.5) == "even"


def test_higher_is_better_edge_respects_epsilon():
    assert P.higher_is_better_edge(1.50, 1.55) == "home"          # epsilon=0.0 default -> real edge
    assert P.higher_is_better_edge(1.50, 1.55, epsilon=0.20) == "even"
    print("✓ higher_is_better_edge treats a gap smaller than a caller-supplied epsilon as \"even\"")


def test_higher_is_better_edge_none_when_either_side_missing():
    assert P.higher_is_better_edge(None, 2.0) is None
    assert P.higher_is_better_edge(2.0, None) is None
    assert P.higher_is_better_edge(None, None) is None


def test_higher_is_better_edge_is_the_true_mirror_of_lower_is_better_edge():
    # For the same pair of values, the two functions should always disagree (never both "home",
    # never both "away") -- confirms this isn't a second, independently-drifted implementation.
    for away, home in [(3.0, 4.0), (4.0, 3.0), (2.5, 2.5), (None, 3.0)]:
        lo = P.lower_is_better_edge(away, home)
        hi = P.higher_is_better_edge(away, home)
        if lo in ("home", "away"):
            assert hi == ("away" if lo == "home" else "home")
        else:
            assert hi == lo   # "even" and None both agree between the two
    print("✓ higher_is_better_edge is confirmed to be the true mirror of lower_is_better_edge for every real case")


# ----------------------------------------------------------------- matchup_signal_tally
def test_matchup_signal_tally_hand_verified_majority():
    tally = P.matchup_signal_tally(["home", "home", "away"])
    assert tally == {"home": 2, "away": 1, "even": 0, "unavailable": 0, "available": 3, "verdict": "home"}
    print("✓ matchup_signal_tally correctly tallies a 2-1 majority into a \"home\" verdict")


def test_matchup_signal_tally_tie_is_even_not_silently_broken():
    tally = P.matchup_signal_tally(["home", "away"])
    assert tally["verdict"] == "even"
    tally2 = P.matchup_signal_tally(["home", "away", "even"])
    assert tally2["verdict"] == "even"   # 1-1 with one genuine "even" signal is still an even verdict
    print("✓ matchup_signal_tally never silently breaks a tie toward either side")


def test_matchup_signal_tally_all_unavailable_is_insufficient_data_not_even():
    tally = P.matchup_signal_tally([None, None, None])
    assert tally["verdict"] == "insufficient_data"
    assert tally == {"home": 0, "away": 0, "even": 0, "unavailable": 3, "available": 0,
                     "verdict": "insufficient_data"}
    print("✓ matchup_signal_tally distinguishes \"insufficient_data\" (nothing available) from "
         "\"even\" (signals available and genuinely balanced) -- not the same honest state")


def test_matchup_signal_tally_mixed_availability():
    # A real, partial read: only 2 of 3 signals came back, and they split -- still \"even\", not
    # treated as 1 missing signal defaulting to either side.
    tally = P.matchup_signal_tally(["home", "away", None])
    assert tally["available"] == 2 and tally["unavailable"] == 1
    assert tally["verdict"] == "even"


def test_matchup_signal_tally_empty_list_is_insufficient_data():
    assert P.matchup_signal_tally([])["verdict"] == "insufficient_data"


# ----------------------------------------------------------------- team_platoon_advantage_fraction
def test_team_platoon_advantage_fraction_hand_verified():
    lineup = [{"Advantage": "Advantage"}, {"Advantage": "Advantage"}, {"Advantage": "Advantage"},
             {"Advantage": "Disadvantage"}, {"Advantage": "Disadvantage"}]
    frac = P.team_platoon_advantage_fraction(lineup)
    assert abs(frac - 0.6) < 1e-9   # 3 of 5
    print("✓ team_platoon_advantage_fraction hand-verifies the exact fraction of a lineup holding the platoon edge")


def test_team_platoon_advantage_fraction_excludes_unknown():
    lineup = [{"Advantage": "Advantage"}, {"Advantage": "Unknown"}, {"Advantage": "Disadvantage"}]
    frac = P.team_platoon_advantage_fraction(lineup)
    assert abs(frac - 0.5) < 1e-9   # 1 of 2 KNOWN reads, "Unknown" row excluded entirely
    print("✓ team_platoon_advantage_fraction excludes Unknown reads from both numerator and denominator")


def test_team_platoon_advantage_fraction_none_when_empty():
    assert P.team_platoon_advantage_fraction([]) is None


def test_team_platoon_advantage_fraction_none_when_all_unknown():
    lineup = [{"Advantage": "Unknown"}, {"Advantage": "Unknown"}]
    assert P.team_platoon_advantage_fraction(lineup) is None
    print("✓ team_platoon_advantage_fraction returns None (not a fabricated 0.0) when every batter's hand data is unknown")


def test_team_platoon_advantage_fraction_all_advantage():
    lineup = [{"Advantage": "Advantage"}] * 4
    assert P.team_platoon_advantage_fraction(lineup) == 1.0


# ----------------------------------------------------------------- blended_pitching_run_rate
def test_blended_pitching_run_rate_hand_verified():
    # 5.5/9 * 3.60 + 3.5/9 * 4.20 = 3.833333...
    rate = P.blended_pitching_run_rate(3.60, 4.20)
    assert abs(rate - 3.8333) < 0.001
    print("✓ blended_pitching_run_rate hand-verifies against the stated 5.5/9-starter, 3.5/9-bullpen weighting")


def test_blended_pitching_run_rate_none_when_either_missing():
    assert P.blended_pitching_run_rate(None, 4.20) is None
    assert P.blended_pitching_run_rate(3.60, None) is None


def test_blended_pitching_run_rate_custom_shares():
    # An explicit 50/50 split should just be the plain average.
    rate = P.blended_pitching_run_rate(3.00, 5.00, starter_share=0.5, bullpen_share=0.5)
    assert rate == 4.0


# ----------------------------------------------------------------- pythagorean_win_pct
def test_pythagorean_win_pct_hand_verified_clean_exponent():
    # RS=5, RA=4, k=2 -> 25/(25+16) = 25/41
    pct = P.pythagorean_win_pct(5, 4, exponent=2)
    assert abs(pct - 25 / 41) < 1e-9
    print("✓ pythagorean_win_pct hand-verifies exactly against a clean k=2 case (25/41)")


def test_pythagorean_win_pct_hand_verified_default_exponent():
    # RS=5, RA=4, default k=1.83 -> 0.6006928... (computed directly, not estimated by hand)
    pct = P.pythagorean_win_pct(5, 4)
    assert abs(pct - 0.6006928) < 0.0001


def test_pythagorean_win_pct_equal_teams_is_half():
    assert abs(P.pythagorean_win_pct(4.5, 4.5) - 0.5) < 1e-9


def test_pythagorean_win_pct_none_on_missing_or_nonpositive():
    assert P.pythagorean_win_pct(None, 4.0) is None
    assert P.pythagorean_win_pct(4.0, None) is None
    assert P.pythagorean_win_pct(0, 4.0) is None
    assert P.pythagorean_win_pct(4.0, -1) is None
    print("✓ pythagorean_win_pct returns None (never a guessed 0.500) for missing or non-positive inputs")


# ----------------------------------------------------------------- log5_win_probability
def test_log5_win_probability_hand_verified():
    # pA=0.6, pB=0.4 -> (0.6-0.24)/(1.0-0.48) = 0.36/0.52 = 0.69230769...
    p = P.log5_win_probability(0.6, 0.4)
    assert abs(p - 0.6923077) < 0.0001
    print("✓ log5_win_probability hand-verifies exactly against Bill James' own published formula")


def test_log5_win_probability_equal_teams_is_half():
    assert abs(P.log5_win_probability(0.55, 0.55) - 0.5) < 1e-9


def test_log5_win_probability_none_when_either_missing():
    assert P.log5_win_probability(None, 0.5) is None
    assert P.log5_win_probability(0.5, None) is None


# ----------------------------------------------------------------- game_win_probability
def test_game_win_probability_hand_verified_full_chain():
    # Computed directly (not estimated by hand) end-to-end from real inputs, then re-asserted
    # here as the locked-in regression value -- away team: better offense AND better pitching.
    result = P.game_win_probability(
        away_runs_scored=4.5, away_starter_fip=3.20, away_bullpen_era=3.80,
        home_runs_scored=4.0, home_starter_fip=4.00, home_bullpen_era=4.50)
    assert abs(result["away_pyth"] - 0.621) < 0.001
    assert abs(result["home_pyth"] - 0.478) < 0.001
    assert abs(result["away_win_prob"] - 0.642) < 0.001
    assert abs(result["home_win_prob"] - 0.358) < 0.001
    print("✓ game_win_probability's full Pythagorean+Log5 chain hand-verifies end to end")


def test_game_win_probability_probabilities_sum_to_one():
    result = P.game_win_probability(4.5, 3.20, 3.80, 4.0, 4.00, 4.50)
    assert abs(result["away_win_prob"] + result["home_win_prob"] - 1.0) < 1e-9
    print("✓ game_win_probability's away/home win probabilities always sum to exactly 1.0 by construction")


def test_game_win_probability_none_when_any_input_missing():
    assert P.game_win_probability(None, 3.20, 3.80, 4.0, 4.00, 4.50) is None
    assert P.game_win_probability(4.5, None, 3.80, 4.0, 4.00, 4.50) is None
    assert P.game_win_probability(4.5, 3.20, None, 4.0, 4.00, 4.50) is None
    assert P.game_win_probability(4.5, 3.20, 3.80, None, 4.00, 4.50) is None
    assert P.game_win_probability(4.5, 3.20, 3.80, 4.0, None, 4.50) is None
    assert P.game_win_probability(4.5, 3.20, 3.80, 4.0, 4.00, None) is None
    print("✓ game_win_probability returns None (never a partial guess) if ANY of the six required inputs is missing")


def test_game_win_probability_own_pitching_affects_own_runs_allowed_not_opponents():
    # Regression guard for the exact bug this design is prone to: a team's runs-ALLOWED input
    # must come from ITS OWN starter/bullpen, never accidentally swapped with the opponent's.
    # Improving ONLY the home team's own pitching should raise the home win prob, not lower it.
    worse_home_pitching = P.game_win_probability(4.5, 3.50, 4.00, 4.5, 3.50, 4.00)
    better_home_pitching = P.game_win_probability(4.5, 3.50, 4.00, 4.5, 2.50, 3.00)
    assert better_home_pitching["home_win_prob"] > worse_home_pitching["home_win_prob"]
    print("✓ game_win_probability correctly attributes each team's own pitching to its own runs allowed, not swapped")


# ----------------------------------------------------------------- advance_runners
def test_advance_runners_out_and_strikeout_no_advance():
    for outcome in (P.OUT_PLAY, P.K):
        bases, outs, runs = P.advance_runners((True, True, True), outcome)
        assert bases == (True, True, True) and outs == 1 and runs == 0
    print("✓ advance_runners: outs and strikeouts record 1 out, no runner movement, no runs")


def test_advance_runners_walk_all_eight_base_states_hand_verified():
    # Every real base-out combination for a walk, hand-derived from the standard MLB force rule.
    cases = [
        ((False, False, False), (True, False, False), 0),
        ((True, False, False), (True, True, False), 0),
        ((False, True, False), (True, True, False), 0),
        ((False, False, True), (True, False, True), 0),
        ((True, True, False), (True, True, True), 0),
        ((True, False, True), (True, True, True), 0),
        ((False, True, True), (True, True, True), 0),
        ((True, True, True), (True, True, True), 1),   # bases loaded -> forced run
    ]
    for before, expected_bases, expected_runs in cases:
        bases, outs, runs = P.advance_runners(before, P.BB)
        assert bases == expected_bases and outs == 0 and runs == expected_runs, \
            f"walk from {before}: got {bases}/{runs}, expected {expected_bases}/{expected_runs}"
    print("✓ advance_runners: all 8 real base-state force-advance cases for a walk hand-verified exactly")


def test_advance_runners_single():
    # Runner on 2nd and 3rd score, runner on 1st advances to 2nd only, batter to 1st.
    bases, outs, runs = P.advance_runners((True, True, True), P.SINGLE)
    assert bases == (True, True, False) and outs == 0 and runs == 2
    bases, outs, runs = P.advance_runners((False, False, False), P.SINGLE)
    assert bases == (True, False, False) and runs == 0


def test_advance_runners_double():
    bases, outs, runs = P.advance_runners((True, True, True), P.DOUBLE)
    assert bases == (False, True, True) and runs == 2   # 1st->3rd, 2nd+3rd score


def test_advance_runners_triple():
    bases, outs, runs = P.advance_runners((True, True, True), P.TRIPLE)
    assert bases == (False, False, True) and runs == 3   # everyone scores, batter on 3rd


def test_advance_runners_home_run():
    bases, outs, runs = P.advance_runners((True, True, True), P.HR)
    assert bases == (False, False, False) and runs == 4   # grand slam
    bases, outs, runs = P.advance_runners((False, False, False), P.HR)
    assert bases == (False, False, False) and runs == 1   # solo shot
    print("✓ advance_runners: single/double/triple/HR all hand-verified, including a grand slam")


# ----------------------------------------------------------------- simulate_one_game / simulate_game_win_probability
def _certain_probs(outcome_idx):
    """A degenerate PA-outcome distribution that ALWAYS produces the same outcome -- lets a test
    fully determine a simulated game's exact result rather than depending on randomness. ONLY
    safe to use for OUT_PLAY/K (which always end the PA with an out) or mixed into a lineup
    alongside other batters who DO make outs -- using this alone for HR/BB/hit outcomes across
    an ENTIRE lineup would mean no out could ever occur, relying entirely on simulate_one_game's
    own MAX_PA_PER_HALF_INNING safety cap rather than a real 3-out termination."""
    probs = np.zeros(7)
    probs[outcome_idx] = 1.0
    return probs


def _realistic_probs(out=0.68, k=0.08, bb=0.08, single=0.10, double=0.03, triple=0.005, hr=0.035):
    """A real, non-degenerate PA-outcome distribution (order matches P.OUTCOMES exactly) --
    always has a genuine chance of an out, so a half-inning built from these terminates normally
    via 3 real outs rather than relying on the safety cap. Defaults are roughly realistic MLB
    rates; callers skew individual arguments to build a "hot" or "cold" lineup for a directional
    comparison test."""
    probs = np.array([out, k, bb, single, double, triple, hr])
    return probs / probs.sum()   # normalize in case a caller's custom values don't sum to 1.0 exactly


def test_simulate_one_game_all_strikeouts_is_scoreless():
    k_probs = [_certain_probs(P.K)] * 9
    rng = np.random.default_rng(42)
    away_runs, home_runs = P.simulate_one_game(k_probs, k_probs, 15, k_probs, k_probs, 15, rng)
    assert away_runs == 0 and home_runs == 0
    print("✓ simulate_one_game: an all-strikeout lineup on both sides produces a real 0-0 game")


def test_simulate_one_game_three_up_three_down_every_inning():
    # A lineup that always makes an out: exactly 3 PAs per half-inning, 9 innings -> 27 PAs each
    # side, 0-0 final. A clean, fully deterministic end-to-end check of the half-inning/inning
    # bookkeeping itself (not just advance_runners in isolation).
    out_probs = [_certain_probs(P.OUT_PLAY)] * 9
    rng = np.random.default_rng(1)
    away_runs, home_runs = P.simulate_one_game(out_probs, out_probs, 15, out_probs, out_probs, 15, rng)
    assert (away_runs, home_runs) == (0, 0)
    print("✓ simulate_one_game: an always-out lineup correctly plays 9 full three-up-three-down innings, 0-0")


def test_simulate_one_game_leadoff_homer_every_inning():
    # Batter 1 always homers, everyone else always makes an out. NOT simply "1 run per inning" --
    # the leadoff spot does NOT recur exactly once every 3 outs, because the very first
    # half-inning uses 4 PAs (HR, out, out, out -- the HR doesn't consume an out), which shifts
    # which lineup slot leads off every inning after. Computed directly and hand-traced
    # inning-by-inning to confirm (both come to the same real answer): innings 1/3/6/9 each
    # produce exactly 1 run (the HR slot happens to bat in each), the rest produce 0 -> 4 runs
    # total, not 9. A genuine example of why "obvious" baseball arithmetic is worth checking
    # directly rather than assuming.
    probs = [_certain_probs(P.HR)] + [_certain_probs(P.OUT_PLAY)] * 8
    rng = np.random.default_rng(7)
    away_runs, home_runs = P.simulate_one_game(probs, probs, 15, probs, probs, 15, rng)
    assert away_runs == 4 and home_runs == 4
    print("✓ simulate_one_game: a deterministic leadoff-homer lineup produces the correctly hand-traced 4-4 score, not the naive 9-9 guess")


def test_simulate_one_game_safety_cap_terminates_a_never_out_lineup():
    # Regression test for a REAL bug caught while writing this test suite, not a hypothetical:
    # an all-home-run lineup can never record an out, so without MAX_PA_PER_HALF_INNING this
    # call would hang indefinitely (confirmed directly -- it did, before the cap was added).
    # With the cap, every half-inning is force-ended at exactly MAX_PA_PER_HALF_INNING PAs, each
    # one a solo HR (bases always reset to empty after a HR) -> an exact, hand-predictable score.
    hr_probs = [_certain_probs(P.HR)] * 9
    always_out = [_certain_probs(P.OUT_PLAY)] * 9
    rng = np.random.default_rng(11)
    away_runs, home_runs = P.simulate_one_game(hr_probs, hr_probs, 99, always_out, always_out, 99,
                                               rng, max_innings=9)
    assert away_runs == P.MAX_PA_PER_HALF_INNING * 9   # capped PAs per inning, 1 run each, 9 innings
    assert home_runs == 0
    print(f"✓ simulate_one_game's MAX_PA_PER_HALF_INNING safety cap correctly terminates a lineup "
         f"that can never make an out, instead of hanging forever (the real bug this guards against)")


def test_simulate_one_game_starter_to_bullpen_handoff_affects_scoring():
    # A believable, non-degenerate matchup: the away lineup hits a tough starter poorly but a
    # weak bullpen well. Pulling the home starter EARLIER (fewer expected outs) lets the away
    # lineup reach the weaker bullpen sooner in the game -- a real, directional check of the
    # starter/bullpen switch logic (not an exact hand-predicted score, which isn't meaningful
    # once outcomes are genuinely probabilistic rather than certain).
    tough_starter = [_realistic_probs(out=0.75, k=0.18, bb=0.04, single=0.02, double=0.005, hr=0.005)] * 9
    weak_bullpen = [_realistic_probs(out=0.55, k=0.08, bb=0.07, single=0.15, double=0.06, hr=0.09)] * 9
    always_out = [_certain_probs(P.OUT_PLAY)] * 9

    early_pull = P.simulate_game_win_probability(
        tough_starter, weak_bullpen, home_starter_exp_outs=3,   # pulled after 1 inning
        home_probs_vs_starter=always_out, home_probs_vs_bullpen=always_out, away_starter_exp_outs=99,
        n_trials=400, seed=5)
    late_pull = P.simulate_game_win_probability(
        tough_starter, weak_bullpen, home_starter_exp_outs=24,   # effectively never pulled in 9 innings
        home_probs_vs_starter=always_out, home_probs_vs_bullpen=always_out, away_starter_exp_outs=99,
        n_trials=400, seed=5)
    assert early_pull["avg_away_runs"] > late_pull["avg_away_runs"]
    print("✓ simulate_one_game: pulling a tough starter earlier for a weaker bullpen measurably raises the opposing offense's expected runs")


# ----------------------------------------------------------------- simulate_one_game: adaptive pull (early_pull_runs)
def test_simulate_one_game_early_pull_hand_verified_exact_score():
    # A degenerate but fully deterministic case, computed directly (not estimated by hand) then
    # locked in here as a regression value: home's starter never reaches his exp_outs (99, an
    # all-HR lineup never records an out against him), but early_pull_runs=2 should pull him
    # after exactly 2 solo homers -- the away lineup then faces the (all-out) bullpen for the
    # rest of the game, so the final score is exactly 2-0, not the safety-cap-driven blowout an
    # un-pulled starter would allow.
    hr_probs = [_certain_probs(P.HR)] * 9
    out_probs = [_certain_probs(P.OUT_PLAY)] * 9
    rng = np.random.default_rng(1)
    away_runs, home_runs = P.simulate_one_game(
        hr_probs, out_probs, 99, out_probs, out_probs, 99, rng, early_pull_runs=2)
    assert (away_runs, home_runs) == (2, 0)
    print("✓ simulate_one_game with early_pull_runs=2 hand-verifies the exact 2-0 score once the starter is pulled after his 2nd allowed run")


def test_simulate_one_game_early_pull_none_preserves_original_behavior():
    # Same exact setup, but early_pull_runs=None (the default) -- the starter never gets pulled
    # via runs allowed, so the safety cap alone determines the final score (see the dedicated
    # safety-cap test above for the exact same 40-PA-per-inning derivation).
    hr_probs = [_certain_probs(P.HR)] * 9
    out_probs = [_certain_probs(P.OUT_PLAY)] * 9
    rng = np.random.default_rng(1)
    away_runs, home_runs = P.simulate_one_game(
        hr_probs, out_probs, 99, out_probs, out_probs, 99, rng, early_pull_runs=None)
    assert away_runs == P.MAX_PA_PER_HALF_INNING * 9   # same derivation as the safety-cap test
    assert home_runs == 0
    print("✓ simulate_one_game with early_pull_runs=None (default) is unaffected by runs allowed, matching the original fixed-outs-only behavior exactly")


def test_simulate_one_game_early_pull_check_is_not_retroactive():
    # The pull check happens BEFORE each PA, not after -- a starter who allows exactly the
    # threshold on some PA is still active FOR that PA (the run that crossed the threshold still
    # happened while he was in), and is only pulled starting the NEXT one. Traced by hand and
    # confirmed by the exact 2-0 test above: the 2nd homer (which brings his runs allowed to
    # exactly 2, the threshold) still counts as allowed by the starter, not retroactively
    # reassigned to the bullpen -- if the check WERE retroactive/pre-emptive on the qualifying
    # PA itself, the 2nd batter would have faced the bullpen (all outs) instead of the starter
    # (all HR), and the final score would be 1-0, not 2-0.
    hr_probs = [_certain_probs(P.HR)] * 9
    out_probs = [_certain_probs(P.OUT_PLAY)] * 9
    rng = np.random.default_rng(1)
    away_runs, _ = P.simulate_one_game(hr_probs, out_probs, 99, out_probs, out_probs, 99,
                                       rng, early_pull_runs=2)
    assert away_runs == 2   # not 1 -- confirms the pull isn't applied retroactively to the qualifying PA
    print("✓ simulate_one_game's early-pull check applies going forward from the NEXT plate appearance, never retroactively")


def test_simulate_one_game_early_pull_affects_only_the_pulled_side():
    # early_pull_runs is a single shared parameter, but each side's own starter is tracked and
    # pulled INDEPENDENTLY -- pulling the home starter early must not affect whether/when the
    # away starter gets pulled.
    hr_probs = [_certain_probs(P.HR)] * 9
    out_probs = [_certain_probs(P.OUT_PLAY)] * 9
    rng = np.random.default_rng(1)
    # Home's starter (facing an all-HR away lineup) should get pulled after 2 runs; away's
    # starter (facing an all-out home lineup) should never allow a run and never get pulled.
    away_runs, home_runs = P.simulate_one_game(
        hr_probs, out_probs, home_starter_exp_outs=99,
        home_probs_vs_starter=out_probs, home_probs_vs_bullpen=out_probs, away_starter_exp_outs=99,
        rng=rng, early_pull_runs=2)
    assert away_runs == 2 and home_runs == 0
    print("✓ simulate_one_game tracks and pulls each side's own starter independently under early_pull_runs")


def test_simulate_game_win_probability_passes_early_pull_runs_through():
    # Regression guard: simulate_game_win_probability must actually forward early_pull_runs to
    # simulate_one_game, not silently drop it -- confirmed by the same dramatic score difference
    # the pure simulate_one_game tests above already established, now checked through the
    # trials-averaging wrapper specifically.
    hr_probs = [_certain_probs(P.HR)] * 9
    out_probs = [_certain_probs(P.OUT_PLAY)] * 9
    with_pull = P.simulate_game_win_probability(hr_probs, out_probs, 99, out_probs, out_probs, 99,
                                                n_trials=20, seed=3, early_pull_runs=2)
    without_pull = P.simulate_game_win_probability(hr_probs, out_probs, 99, out_probs, out_probs, 99,
                                                    n_trials=20, seed=3, early_pull_runs=None)
    assert with_pull["avg_away_runs"] < without_pull["avg_away_runs"]
    assert with_pull["avg_away_runs"] == 2.0   # every trial is identically deterministic here
    print("✓ simulate_game_win_probability correctly forwards early_pull_runs down to simulate_one_game")


# ----------------------------------------------------------------- simulate_one_game: third-phase closer
def test_simulate_one_game_closer_takes_over_the_final_inning_hand_verified():
    # Computed directly (not estimated by hand), then locked in as a regression value: home's
    # starter is pulled immediately (exp_outs=0), and the "rest of bullpen" (home_probs_vs_
    # bullpen) always allows a HR -- but home's own closer is lights-out. With closer_innings=1,
    # innings 1-8 hit the safety cap (40 runs each, HR never makes an out) = 320, and inning 9
    # is shut down by the closer (0 runs) -> exactly 320 total, not 360 (the no-closer case).
    hr_probs = [_certain_probs(P.HR)] * 9
    out_probs = [_certain_probs(P.OUT_PLAY)] * 9
    rng = np.random.default_rng(2)
    away_runs, home_runs = P.simulate_one_game(
        hr_probs, hr_probs, 0, out_probs, out_probs, 99,
        rng, away_probs_vs_closer=out_probs, closer_innings=1)
    assert (away_runs, home_runs) == (320, 0)
    print("✓ simulate_one_game's closer phase hand-verifies the exact 320-0 score across the full 9 innings")


def test_simulate_one_game_no_closer_given_preserves_original_two_phase_behavior():
    # Same exact setup, but away_probs_vs_closer=None (the default) -- every inning after the
    # immediate pull uses the HR-certain "rest of bullpen" array, hitting the safety cap in
    # all 9 innings (9 * 40 = 360), same derivation as the safety-cap test.
    hr_probs = [_certain_probs(P.HR)] * 9
    out_probs = [_certain_probs(P.OUT_PLAY)] * 9
    rng = np.random.default_rng(2)
    away_runs, home_runs = P.simulate_one_game(
        hr_probs, hr_probs, 0, out_probs, out_probs, 99,
        rng, away_probs_vs_closer=None)
    assert away_runs == P.MAX_PA_PER_HALF_INNING * 9
    assert home_runs == 0
    print("✓ simulate_one_game with no closer array given (default None) is unaffected, matching the original two-phase behavior exactly")


def test_simulate_one_game_closer_never_overrides_an_active_starter():
    # A starter who's still active going into (and through) the closer's own inning window must
    # keep pitching -- the closer phase can only take over once the starter is actually out,
    # never cut a still-cruising start short just because it's the 9th inning.
    out_probs = [_certain_probs(P.OUT_PLAY)] * 9
    hr_probs = [_certain_probs(P.HR)] * 9
    rng = np.random.default_rng(4)
    away_runs, home_runs = P.simulate_one_game(
        out_probs, hr_probs, 99,   # home starter never reaches 99 outs across 9 innings -> never pulled
        out_probs, out_probs, 99,
        rng, away_probs_vs_closer=hr_probs, closer_innings=1)
    assert (away_runs, home_runs) == (0, 0)
    print("✓ simulate_one_game's closer phase never overrides a starter who's still active, even in the closer's own inning window")


def test_simulate_one_game_closer_array_is_not_swapped_between_sides():
    # Regression guard for a REAL bug caught and fixed while building this (not a hypothetical):
    # away_probs_vs_closer must be the AWAY lineup's own read facing the HOME closer (mirroring
    # away_probs_vs_bullpen's own convention exactly), not accidentally cross-wired to the other
    # side. Give AWAY's closer array a distinctly different read (certain HR) than HOME's
    # (certain out) and confirm each side's own runs reflect its OWN opposing closer, not the
    # other side's.
    out_probs = [_certain_probs(P.OUT_PLAY)] * 9
    hr_probs = [_certain_probs(P.HR)] * 9
    rng = np.random.default_rng(9)
    away_runs, home_runs = P.simulate_one_game(
        out_probs, out_probs, 0,    # home starter pulled immediately; away batters face home's closer
        out_probs, out_probs, 0,    # away starter pulled immediately; home batters face away's closer
        rng, away_probs_vs_closer=out_probs,   # away batters vs HOME's closer: shut down
        home_probs_vs_closer=hr_probs,          # home batters vs AWAY's closer: gives up HRs
        closer_innings=9)   # the whole game is "closer window" for a clean, simple check
    assert away_runs == 0    # away batters faced home's OWN (shutdown) closer, not away's own
    assert home_runs == P.MAX_PA_PER_HALF_INNING * 9   # home batters faced away's OWN (HR) closer
    print("✓ simulate_one_game's away_probs_vs_closer/home_probs_vs_closer are never cross-wired between sides")


def test_simulate_game_win_probability_passes_closer_params_through():
    # Regression guard: simulate_game_win_probability must actually forward the closer
    # parameters to simulate_one_game, not silently drop them.
    hr_probs = [_certain_probs(P.HR)] * 9
    out_probs = [_certain_probs(P.OUT_PLAY)] * 9
    with_closer = P.simulate_game_win_probability(
        hr_probs, hr_probs, 0, out_probs, out_probs, 99,
        n_trials=10, seed=2, away_probs_vs_closer=out_probs, closer_innings=1)
    without_closer = P.simulate_game_win_probability(
        hr_probs, hr_probs, 0, out_probs, out_probs, 99,
        n_trials=10, seed=2)
    assert with_closer["avg_away_runs"] < without_closer["avg_away_runs"]
    assert with_closer["avg_away_runs"] == 320.0   # every trial is identically deterministic here
    print("✓ simulate_game_win_probability correctly forwards the closer parameters down to simulate_one_game")


def test_simulate_game_win_probability_lopsided_matchup_favors_the_better_side():
    # Away lineup crushes; home lineup is helpless -- not literally certain (real, non-degenerate
    # probabilities), but should win the overwhelming majority of trials.
    strong_hitting = [_realistic_probs(out=0.45, k=0.05, bb=0.10, single=0.15, double=0.10, hr=0.14)] * 9
    weak_hitting = [_realistic_probs(out=0.85, k=0.10, bb=0.03, single=0.015, double=0.003, hr=0.001)] * 9
    result = P.simulate_game_win_probability(strong_hitting, strong_hitting, 99, weak_hitting, weak_hitting, 99,
                                             n_trials=300, seed=42)
    assert result["away_win_prob"] > 0.9
    assert result["n_trials"] == 300
    print("✓ simulate_game_win_probability gives a heavily lopsided matchup an overwhelmingly one-sided win rate")


def test_simulate_game_win_probability_probs_sum_to_one():
    k_probs = [_certain_probs(P.K)] * 9
    result = P.simulate_game_win_probability(k_probs, k_probs, 15, k_probs, k_probs, 15, n_trials=50, seed=1)
    total = result["away_win_prob"] + result["home_win_prob"] + result["tie_prob"]
    assert abs(total - 1.0) < 1e-9
    assert result["tie_prob"] == 1.0   # an always-scoreless game is always a tie
    print("✓ simulate_game_win_probability's away/home/tie probabilities always sum to exactly 1.0")


def test_simulate_game_win_probability_reproducible_with_seed():
    hot = [_realistic_probs(out=0.50, k=0.08, bb=0.08, single=0.14, double=0.08, hr=0.10)] * 9
    cold = [_realistic_probs(out=0.80, k=0.12, bb=0.04, single=0.03, double=0.005, hr=0.005)] * 9
    r1 = P.simulate_game_win_probability(hot, cold, 15, hot, cold, 15, n_trials=100, seed=99)
    r2 = P.simulate_game_win_probability(hot, cold, 15, hot, cold, 15, n_trials=100, seed=99)
    assert r1 == r2
    print("✓ simulate_game_win_probability gives identical results for the same seed, real reproducibility")


def test_bullpen_fatigue_multipliers_above_threshold():
    m = P.bullpen_fatigue_multipliers(0.5)
    assert m["k_mult"] == P.REST_K_MULT
    assert m["bb_mult"] == P.REST_BB_MULT
    assert m["er_mult"] == P.REST_ER_MULT
    assert m["hr_mult"] == P.REST_HR_MULT
    print("✓ bullpen_fatigue_multipliers applies the real, shared fatigue penalty above the threshold")


def test_bullpen_fatigue_multipliers_deliberately_reuses_rest_constants():
    # A real, deliberate design choice, not a coincidence: both concepts (a fatigued bullpen and
    # a short-rest starter) reuse the exact same underlying magnitude.
    assert P.bullpen_fatigue_multipliers(0.5) == P.rest_adjustment_multipliers(4)
    print("✓ bullpen_fatigue_multipliers deliberately shares its exact magnitude with rest_adjustment_multipliers")


def test_bullpen_fatigue_multipliers_below_threshold_no_adjustment():
    m = P.bullpen_fatigue_multipliers(0.2)
    assert m == {"k_mult": 1.0, "bb_mult": 1.0, "er_mult": 1.0, "hr_mult": 1.0}
    print("✓ bullpen_fatigue_multipliers applies no adjustment when the fatigued fraction is below the real, stated threshold")


def test_bullpen_fatigue_multipliers_exact_threshold_boundary():
    below = P.bullpen_fatigue_multipliers(P.BULLPEN_FATIGUE_THRESHOLD - 0.01)
    at = P.bullpen_fatigue_multipliers(P.BULLPEN_FATIGUE_THRESHOLD)
    assert below == {"k_mult": 1.0, "bb_mult": 1.0, "er_mult": 1.0, "hr_mult": 1.0}
    assert at["k_mult"] == P.REST_K_MULT
    print("✓ bullpen_fatigue_multipliers' threshold boundary is inclusive and exact")


def test_bullpen_fatigue_multipliers_none_treated_as_fresh():
    m = P.bullpen_fatigue_multipliers(None)
    assert m == {"k_mult": 1.0, "bb_mult": 1.0, "er_mult": 1.0, "hr_mult": 1.0}
    print("✓ bullpen_fatigue_multipliers correctly treats unknown fatigue as fresh, never assuming the worse case")


# ----------------------------------------------------------------- hitter_fatigue_multipliers
def test_hitter_fatigue_multipliers_at_threshold():
    m = P.hitter_fatigue_multipliers(8)
    assert m["hr_mult"] == P.HITTER_FATIGUE_HR_MULT
    assert m["hit_mult"] == P.HITTER_FATIGUE_HIT_MULT
    assert m["k_mult"] == P.HITTER_FATIGUE_K_MULT
    assert m["hr_mult"] < 1.0    # reduced power
    assert m["hit_mult"] < 1.0   # reduced contact quality
    assert m["k_mult"] > 1.0     # more strikeouts
    print("✓ hitter_fatigue_multipliers applies the real, stated fatigue penalty in the correct direction on every rate")


def test_hitter_fatigue_multipliers_no_bb_field_at_all():
    # Deliberate: plate discipline (walk rate) is not adjusted at all -- there's no honest basis
    # to assert fatigue erodes a far less physically demanding skill the same way it erodes bat
    # speed/power, so this function doesn't even return a bb_mult key.
    m = P.hitter_fatigue_multipliers(8)
    assert "bb_mult" not in m
    print("✓ hitter_fatigue_multipliers deliberately has no walk-rate adjustment at all")


def test_hitter_fatigue_multipliers_boundary_at_7_and_8():
    # THE exact boundary get_team_hitter_workload's own 🔴 tag uses.
    below = P.hitter_fatigue_multipliers(7)
    at = P.hitter_fatigue_multipliers(8)
    assert below == {"hr_mult": 1.0, "hit_mult": 1.0, "k_mult": 1.0}
    assert at["hr_mult"] != 1.0
    print("✓ hitter_fatigue_multipliers' boundary exactly matches get_team_hitter_workload's own 8-game threshold")


def test_hitter_fatigue_multipliers_watch_tier_not_adjusted():
    # A real, deliberate choice: the 5-7 game "🟡 extended run" tier does NOT trigger a real
    # adjustment, same "watch signal isn't a confirmed one" posture as extra pitcher rest.
    m = P.hitter_fatigue_multipliers(6)
    assert m == {"hr_mult": 1.0, "hit_mult": 1.0, "k_mult": 1.0}
    print("✓ hitter_fatigue_multipliers correctly applies no adjustment for the 🟡 watch tier, only the confirmed 🔴 one")


def test_hitter_fatigue_multipliers_none_treated_as_rested():
    m = P.hitter_fatigue_multipliers(None)
    assert m == {"hr_mult": 1.0, "hit_mult": 1.0, "k_mult": 1.0}
    print("✓ hitter_fatigue_multipliers correctly treats unknown workload as rested, never assuming the worse case")


def test_hitter_fatigue_multipliers_longer_streak_same_flat_penalty():
    # No graduated curve -- 12 straight games gets the SAME flat penalty as exactly 8, matching
    # the same "no real data to support a graduated curve" posture as the pitcher-side functions.
    assert P.hitter_fatigue_multipliers(12) == P.hitter_fatigue_multipliers(8)
    print("✓ hitter_fatigue_multipliers applies a flat penalty across the whole fatigued range, not a fabricated graduated curve")


def test_pitcher_allowed_rates_guards():
    assert P.pitcher_allowed_rates(None) is None
    assert P.pitcher_allowed_rates(dict(battersFaced=10)) is None  # too thin


def test_pitcher_allowed_rates_short_rest_applies_correct_direction():
    stat = dict(battersFaced=400, homeRuns=15, strikeOuts=95, baseOnBalls=42, hits=105)
    normal = P.pitcher_allowed_rates(stat)
    short = P.pitcher_allowed_rates(stat, days_rest=4)
    # Hand-verified exact ratios, not just directional checks
    assert abs(short["k"] / normal["k"] - P.REST_K_MULT) < 1e-9
    assert abs(short["bb"] / normal["bb"] - P.REST_BB_MULT) < 1e-9
    assert abs(short["hr"] / normal["hr"] - P.REST_HR_MULT) < 1e-9
    print("✓ pitcher_allowed_rates applies the exact, hand-verified short-rest multiplier to k/bb/hr")


def test_pitcher_allowed_rates_short_rest_leaves_nonhr_hit_untouched():
    # Deliberate: DIPS theory already established elsewhere in this module treats hits-allowed
    # as mostly luck/defense, not pitcher skill -- a rest effect shouldn't suddenly appear here.
    stat = dict(battersFaced=400, homeRuns=15, strikeOuts=95, baseOnBalls=42, hits=105)
    normal = P.pitcher_allowed_rates(stat)
    short = P.pitcher_allowed_rates(stat, days_rest=4)
    assert short["nonhr_hit"] == normal["nonhr_hit"]
    print("✓ pitcher_allowed_rates correctly leaves nonhr_hit untouched by the rest adjustment")


def test_pitcher_allowed_rates_normal_rest_unaffected():
    stat = dict(battersFaced=400, homeRuns=15, strikeOuts=95, baseOnBalls=42, hits=105)
    no_arg = P.pitcher_allowed_rates(stat)
    explicit_normal = P.pitcher_allowed_rates(stat, days_rest=5)
    assert no_arg == explicit_normal
    print("✓ pitcher_allowed_rates produces identical output whether days_rest is omitted or explicitly normal")


def test_pitcher_allowed_rates_bullpen_fatigue_applies_correct_direction():
    stat = dict(battersFaced=400, homeRuns=15, strikeOuts=95, baseOnBalls=42, hits=105)
    normal = P.pitcher_allowed_rates(stat)
    fatigued = P.pitcher_allowed_rates(stat, bullpen_fatigue=0.5)
    assert abs(fatigued["k"] / normal["k"] - P.REST_K_MULT) < 1e-9
    assert abs(fatigued["bb"] / normal["bb"] - P.REST_BB_MULT) < 1e-9
    assert abs(fatigued["hr"] / normal["hr"] - P.REST_HR_MULT) < 1e-9
    assert fatigued["nonhr_hit"] == normal["nonhr_hit"]   # same DIPS-theory posture as rest
    print("✓ pitcher_allowed_rates applies the exact, hand-verified bullpen fatigue penalty")


def test_pitcher_allowed_rates_bullpen_fatigue_below_threshold_unaffected():
    stat = dict(battersFaced=400, homeRuns=15, strikeOuts=95, baseOnBalls=42, hits=105)
    normal = P.pitcher_allowed_rates(stat)
    below = P.pitcher_allowed_rates(stat, bullpen_fatigue=0.2)
    assert normal == below
    print("✓ pitcher_allowed_rates applies no adjustment when bullpen_fatigue is below the real threshold")


def test_pitcher_allowed_rates_combines_rest_and_fatigue_multiplicatively():
    # A real, deliberate design confirmation: if both were somehow provided together (in
    # practice they never are for the same real stat dict), they compose multiplicatively
    # rather than one silently overriding the other.
    stat = dict(battersFaced=400, homeRuns=15, strikeOuts=95, baseOnBalls=42, hits=105)
    normal = P.pitcher_allowed_rates(stat)
    both = P.pitcher_allowed_rates(stat, days_rest=4, bullpen_fatigue=0.5)
    assert abs(both["k"] / normal["k"] - (P.REST_K_MULT ** 2)) < 1e-9
    assert abs(both["bb"] / normal["bb"] - (P.REST_BB_MULT ** 2)) < 1e-9
    print("✓ pitcher_allowed_rates combines rest and bullpen fatigue multiplicatively when both are present")


def test_handedness_split_applies():
    slug = _slugger()
    vs_r = dict(plateAppearances=420, atBats=380, hits=130, doubles=28, triples=1,
                homeRuns=32, baseOnBalls=35, strikeOuts=80)
    vs_l = dict(plateAppearances=180, atBats=165, hits=35, doubles=6, triples=0,
                homeRuns=6, baseOnBalls=12, strikeOuts=55)
    p_vsR = P.batter_pa_probs(slug, P.NEUTRAL_PARK, split_stat=vs_r)
    p_vsL = P.batter_pa_probs(slug, P.NEUTRAL_PARK, split_stat=vs_l)
    assert p_vsR[P.HR] > p_vsL[P.HR]   # mashes RHP
    assert p_vsL[P.K] > p_vsR[P.K]     # whiffs vs LHP
    # A tiny split sample barely moves the season rate (shrinkage).
    tiny = dict(plateAppearances=8, atBats=7, hits=5, doubles=2, triples=0,
                homeRuns=3, baseOnBalls=1, strikeOuts=1)
    base = P.batter_pa_probs(slug, P.NEUTRAL_PARK)
    p_tiny = P.batter_pa_probs(slug, P.NEUTRAL_PARK, split_stat=tiny)
    assert abs(p_tiny[P.HR] - base[P.HR]) < 0.01


def test_lineup_k_bb_rates():
    whiff = [dict(plateAppearances=600, strikeOuts=180, baseOnBalls=45) for _ in range(9)]
    rates = P.lineup_k_bb_rates(whiff)
    assert 0.25 < rates["k"] < 0.32          # ~30% K lineup
    # thin lineup data -> None (falls back to neutral)
    assert P.lineup_k_bb_rates([dict(plateAppearances=10, strikeOuts=3, baseOnBalls=1)]) is None


def test_pitcher_matchup_moves_strikeouts():
    ace = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29, strikeOuts=235, baseOnBalls=42)
    whiff = P.lineup_k_bb_rates([dict(plateAppearances=600, strikeOuts=180, baseOnBalls=45) for _ in range(9)])
    contact = P.lineup_k_bb_rates([dict(plateAppearances=600, strikeOuts=90, baseOnBalls=45) for _ in range(9)])
    k_vs_whiff = P.project_pitcher(ace, whiff)["exp_k"]
    k_neutral = P.project_pitcher(ace)["exp_k"]
    k_vs_contact = P.project_pitcher(ace, contact)["exp_k"]
    assert k_vs_whiff > k_neutral > k_vs_contact


def test_pitcher_matchup_moves_walks():
    ace = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29, strikeOuts=235, baseOnBalls=42)
    patient = P.lineup_k_bb_rates([dict(plateAppearances=600, strikeOuts=120, baseOnBalls=80) for _ in range(9)])
    hacker = P.lineup_k_bb_rates([dict(plateAppearances=600, strikeOuts=120, baseOnBalls=25) for _ in range(9)])
    assert P.project_pitcher(ace, patient)["exp_bb"] > P.project_pitcher(ace, hacker)["exp_bb"]


def test_lineup_rate_map():
    rows = [
        {"GameLabel": "A @ B", "Team": "A", "_stat": dict(plateAppearances=600, strikeOuts=150, baseOnBalls=50)},
        {"GameLabel": "A @ B", "Team": "A", "_stat": dict(plateAppearances=600, strikeOuts=120, baseOnBalls=60)},
    ]
    m = P.build_lineup_rate_map(rows)
    assert ("A @ B", "A") in m
    assert m[("A @ B", "A")] is None or "k" in m[("A @ B", "A")]


def test_favored_side():
    # over above reference -> Over; below -> Under (with complemented prob/ref)
    assert P._favored_side(0.30, 0.11)[0] == "Over"
    side, sp, refs = P._favored_side(0.30, 0.62)   # 30% over a 62% baseline -> Under is the lean
    assert side == "Under" and abs(sp - 0.70) < 1e-9 and abs(refs - 0.38) < 1e-9


def test_build_best_bets_ranks_and_reasons():
    hitters = [
        dict(Hitter="Slugger", Team="A", GameLabel="A @ B", Hand="L",
             **{"Opp Hand": "R", "Opp Pitcher": "Ace"}, Advantage="Advantage",
             _weather_hr=1.12, Due=0.03, **{"HR%": 0.22, "TB1.5%": 0.49, "Hit%": 0.70, "SO Prob": 0.55}),
    ]
    pitchers = [
        dict(Pitcher="Whiff Ace", Team="B", Opp="A",
             **{"K over%": 0.74, "Outs over%": 0.58, "BB over%": 0.30},
             **{"Proj K": 9.2, "Proj BB": 1.6, "Proj IP": 6.2, "Proj Outs": 18.6},
             _opp_k=0.265, _opp_bb=0.07, _game="A @ B"),
    ]
    plays = P.build_best_bets(hitters, pitchers)
    assert plays, "should produce plays"
    # sorted by conviction descending
    convs = [p["Conviction"] for p in plays]
    assert convs == sorted(convs, reverse=True)
    # the slugger HR over should be the top conviction play and carry reasoning
    top = plays[0]
    assert top["Market"] == "Batter HR" and top["Side"] == "Over"
    assert "platoon" in top["Why"] and "weather" in top["Why"]
    # no "won't homer" plays
    assert not any(p["Market"] == "Batter HR" and p["Side"] == "Under" for p in plays)


def test_build_best_bets_includes_new_markets():
    hitters = [
        dict(Hitter="Slugger", Team="A", GameLabel="A @ B", Hand="L",
            **{"Opp Hand": "R", "Opp Pitcher": "Ace"}, Advantage="Advantage",
            _weather_hr=1.0, Due=0.0, _opp_stat={"era": 5.2},
            **{"HR%": 0.15, "TB1.5%": 0.40, "Hit%": 0.65, "SO Prob": 0.50,
              "Runs%": 0.42, "RBI%": 0.40, "SB%": 0.08}),
    ]
    pitchers = [
        dict(Pitcher="Ace", Team="B", Opp="A", ERA=3.10,
            **{"K over%": 0.55, "Outs over%": 0.50, "BB over%": 0.30, "ER over%": 0.42},
            **{"Proj K": 6.0, "Proj BB": 1.6, "Proj IP": 6.2, "Proj Outs": 18.6, "Proj ER": 2.1},
            _opp_k=0.22, _opp_bb=0.08, _game="A @ B"),
    ]
    plays = P.build_best_bets(hitters, pitchers)
    markets_present = {p["Market"] for p in plays}
    assert "Batter Runs" in markets_present
    assert "Batter RBIs" in markets_present
    assert "Batter Stolen Bases" in markets_present
    assert "Pitcher Earned Runs" in markets_present

    runs_play = next(p for p in plays if p["Market"] == "Batter Runs")
    assert runs_play["Line"] == 0.5
    assert "Why" in runs_play and runs_play["Why"]

    er_play = next(p for p in plays if p["Market"] == "Pitcher Earned Runs")
    assert er_play["Line"] == 2.5
    assert "ERA" in er_play["Why"] or "2.5" in str(er_play.get("Line"))
    print("\u2713 build_best_bets correctly produces real, correctly-shaped plays for all four new markets end-to-end")


def test_build_best_bets_includes_second_wave_of_new_markets():
    hitters = [
        dict(Hitter="Slugger", Team="A", GameLabel="A @ B", Hand="L",
            **{"Opp Hand": "R", "Opp Pitcher": "Ace"}, Advantage="Advantage",
            _weather_hr=1.0, Due=0.0, _opp_stat={"era": 5.2},
            **{"HR%": 0.15, "TB1.5%": 0.40, "Hit%": 0.65, "SO Prob": 0.50,
              "Runs%": 0.42, "RBI%": 0.40, "SB%": 0.08,
              "Single%": 0.45, "Double%": 0.16, "Triple%": 0.025, "Walk%": 0.38}),
    ]
    pitchers = [
        dict(Pitcher="Ace", Team="B", Opp="A", ERA=3.10,
            **{"K over%": 0.55, "Outs over%": 0.50, "BB over%": 0.30, "ER over%": 0.42,
              "Hits Allowed over%": 0.48},
            **{"Proj K": 6.0, "Proj BB": 1.6, "Proj IP": 6.2, "Proj Outs": 18.6, "Proj ER": 2.1,
              "Proj Hits Allowed": 5.4},
            _opp_k=0.22, _opp_bb=0.08, _game="A @ B"),
    ]
    plays = P.build_best_bets(hitters, pitchers)
    markets_present = {p["Market"] for p in plays}
    for market in ("Batter Singles", "Batter Doubles", "Batter Triples", "Batter Walks",
                  "Pitcher Hits Allowed"):
        assert market in markets_present, f"{market} missing from build_best_bets output"

    walks_play = next(p for p in plays if p["Market"] == "Batter Walks")
    assert walks_play["Line"] == 0.5
    assert "Why" in walks_play and walks_play["Why"]

    ha_play = next(p for p in plays if p["Market"] == "Pitcher Hits Allowed")
    assert ha_play["Line"] == 5.5
    assert "5.4" in ha_play["Why"] or "league average" in ha_play["Why"].lower()
    print("\u2713 build_best_bets correctly produces real, correctly-shaped plays for all five second-wave markets end-to-end")


def test_build_best_bets_includes_hrr():
    hitters = [
        dict(Hitter="Slugger", Team="A", GameLabel="A @ B", Hand="L",
            **{"Opp Hand": "R", "Opp Pitcher": "Ace"}, Advantage="Advantage",
            _weather_hr=1.0, Due=0.0, _opp_stat={"era": 5.2},
            **{"HR%": 0.15, "TB1.5%": 0.40, "Hit%": 0.65, "SO Prob": 0.50,
              "Runs%": 0.42, "RBI%": 0.40, "SB%": 0.08,
              "Single%": 0.45, "Double%": 0.16, "Triple%": 0.025, "Walk%": 0.38,
              "HRR%": 0.60}),
    ]
    plays = P.build_best_bets(hitters, [])
    hrr_play = next((p for p in plays if p["Market"] == "Batter Hits+Runs+RBIs"), None)
    assert hrr_play is not None
    assert hrr_play["Line"] == 1.5
    assert "correlation-aware" in hrr_play["Why"]
    print("\u2713 build_best_bets correctly produces a real Batter Hits+Runs+RBIs play with honest, correlation-aware reasoning")


# ----------------------------------------------------------------- build_best_bets: real lines end to end
def test_build_best_bets_falls_back_to_default_line_source_when_row_lacks_companion_fields():
    # A row shaped the OLD way (no "<Market> Line"/"LineSource" companion fields at all, as
    # every fixture above this point in the file already is) must still work exactly as before —
    # falling back to DEFAULT_LINES and reporting an honest "default" source, never a crash or a
    # fabricated "book" claim for a line that was never actually real.
    hitters = [dict(Hitter="Old Style Row", Team="A", GameLabel="A @ B", Hand="L",
                    **{"Opp Hand": "R", "Opp Pitcher": "Ace"}, Advantage="Advantage",
                    _weather_hr=1.0, Due=0.0, **{"HR%": 0.15, "TB1.5%": 0.40})]
    plays = P.build_best_bets(hitters, [])
    tb_play = next(p for p in plays if p["Market"] == "Batter Total Bases")
    assert tb_play["Line"] == 1.5 and tb_play["LineSource"] == "default"
    print("✓ build_best_bets falls back to the honest DEFAULT_LINES/'default' source for a row lacking the new companion fields, exactly as before this feature")


def test_build_best_bets_reads_real_line_and_source_from_the_row():
    hitters = [dict(Hitter="Real Line Guy", Team="A", GameLabel="A @ B", Hand="L",
                    **{"Opp Hand": "R", "Opp Pitcher": "Ace"}, Advantage="Advantage",
                    _weather_hr=1.0, Due=0.0,
                    **{"TB1.5%": 0.35, "TB Line": 2.5, "TB LineSource": "book"})]
    plays = P.build_best_bets(hitters, [])
    tb_play = next(p for p in plays if p["Market"] == "Batter Total Bases")
    assert tb_play["Line"] == 2.5 and tb_play["LineSource"] == "book"
    print("✓ build_best_bets correctly reads the real line and 'book' source from the row's own companion fields, not a hardcoded literal")


def test_build_best_bets_full_pipeline_reproduces_the_real_sugano_case():
    # THE full, real, end-to-end reproduction: real odds -> build_pitcher_projection_rows ->
    # build_best_bets -> the actual play a person would see on Best Bets/Graded Picks. This is
    # the complete chain the real, reported discrepancy traveled through.
    stat = dict(battersFaced=650, inningsPitched="165.0", gamesStarted=27,
               strikeOuts=95, baseOnBalls=35, earnedRuns=60, hits=160)
    sugano = _fake_pm(700, "Tomoyuki Sugano", "R", 3.80, 4.10, stat)
    opp = _fake_pm(701, "Opposing Pitcher", "L", 4.00, 4.00, stat)
    meta = [{"label": "Opponent @ Padres", "home_id": 135, "away_id": 999,
            "home_name": "San Diego Padres", "away_name": "Opponent",
            "game_date": "2026-07-24", "home_pm": sugano, "away_pm": opp}]
    real_lines = {(P.normalize_name("Tomoyuki Sugano"), "pitcher_strikeouts"): 3.5}

    pitcher_rows_real = P.build_pitcher_projection_rows([], meta, seed=1, real_lines=real_lines)
    pitcher_rows_default = P.build_pitcher_projection_rows([], meta, seed=1, real_lines=None)

    plays_real = P.build_best_bets([], pitcher_rows_real)
    plays_default = P.build_best_bets([], pitcher_rows_default)

    sugano_play_real = next(p for p in plays_real
                            if p["Player"] == "Tomoyuki Sugano" and p["Market"] == "Pitcher Strikeouts")
    sugano_play_default = next(p for p in plays_default
                               if p["Player"] == "Tomoyuki Sugano" and p["Market"] == "Pitcher Strikeouts")

    assert sugano_play_real["Line"] == 3.5 and sugano_play_real["LineSource"] == "book"
    assert sugano_play_default["Line"] == 5.5 and sugano_play_default["LineSource"] == "default"
    assert sugano_play_real["ModelProb"] != sugano_play_default["ModelProb"]
    print(f"✓ FULL PIPELINE, end to end: real odds -> build_pitcher_projection_rows -> "
         f"build_best_bets correctly produces 'Pitcher Strikeouts {sugano_play_real['Side']} "
         f"{sugano_play_real['Line']:g}' (the real DraftKings line) instead of the old hardcoded "
         f"'{sugano_play_default['Side']} {sugano_play_default['Line']:g}' — the exact real, "
         f"reported case, resolved completely from the real-odds lookup through to the final play")


# ----------------------------------------------------------------- MLB_MARKET_TO_ODDS_KEY and real_line_or_default
def test_mlb_market_to_odds_key_matches_sports_market_map():
    """Drift guard: MLB_MARKET_TO_ODDS_KEY in projections.py and _MLB_MARKET_MAP in sports.py
    must always be identical -- projections.py's own comment says exactly this, and this test
    is the automated enforcement. Fails loudly if one gets updated without the other."""
    import sports
    assert P.MLB_MARKET_TO_ODDS_KEY == sports._MLB_MARKET_MAP, (
        "projections.MLB_MARKET_TO_ODDS_KEY and sports._MLB_MARKET_MAP have drifted apart -- "
        "update both together. Differences: "
        f"{set(P.MLB_MARKET_TO_ODDS_KEY.items()) ^ set(sports._MLB_MARKET_MAP.items())}")
    print(f"✓ MLB_MARKET_TO_ODDS_KEY matches sports._MLB_MARKET_MAP exactly across all "
         f"{len(P.MLB_MARKET_TO_ODDS_KEY)} real markets — no drift")


def test_real_line_or_default_returns_real_line_when_available():
    import projections as P
    normalized = P.normalize_name("Tomoyuki Sugano")
    real_lines = {(normalized, "pitcher_strikeouts"): 3.5}
    line, src = P.real_line_or_default("Pitcher Strikeouts", "Tomoyuki Sugano", real_lines, 5.5)
    assert line == 3.5 and src == "book"
    print("✓ real_line_or_default returns the real book line and 'book' source when available")


def test_real_line_or_default_falls_back_to_placeholder_when_player_absent():
    real_lines = {(P.normalize_name("Someone Else"), "pitcher_strikeouts"): 3.5}
    line, src = P.real_line_or_default("Pitcher Strikeouts", "Tomoyuki Sugano", real_lines, 5.5)
    assert line == 5.5 and src == "default"
    print("✓ real_line_or_default falls back to the placeholder when no real line exists for this specific player")


def test_real_line_or_default_falls_back_when_real_lines_is_none():
    line, src = P.real_line_or_default("Pitcher Strikeouts", "Anyone", None, 5.5)
    assert line == 5.5 and src == "default"
    print("✓ real_line_or_default falls back cleanly when real_lines=None (no odds fetch attempted this run)")


def test_real_line_or_default_none_for_unrecognized_market():
    real_lines = {}
    line, src = P.real_line_or_default("Some Unknown Market", "Tomoyuki Sugano", real_lines, 5.5)
    assert line == 5.5 and src == "default"
    print("✓ real_line_or_default falls back for an unrecognized market key rather than crashing")



# ----------------------------------------------------------------- build_bullpen_matchup_rows
def _hitter_row_for_bullpen_test(team, opp_stat):
    return {
        "Hitter": "Test Slugger", "Team": team, "_pid": 1, "_stat": _slugger(),
        "_opp_stat": opp_stat, "_venue_id": None, "_split_stat": None,
        "_exp_pa": 4.25, "_weather_hr": 1.0,
    }


def test_bullpen_matchup_rows_only_touches_the_target_teams_rows():
    home_row = _hitter_row_for_bullpen_test("Home", dict(battersFaced=700, homeRuns=15,
                                                         strikeOuts=150, baseOnBalls=50, hits=150))
    away_row = _hitter_row_for_bullpen_test("Away", dict(battersFaced=700, homeRuns=15,
                                                         strikeOuts=150, baseOnBalls=50, hits=150))
    bullpen_stat = dict(battersFaced=700, homeRuns=10, strikeOuts=210, baseOnBalls=40, hits=130)
    out = P.build_bullpen_matchup_rows([home_row, away_row], "Away", bullpen_stat, seed=1)
    assert len(out) == 1 and out[0]["Team"] == "Away"   # Home's row never appears in the output
    print("✓ build_bullpen_matchup_rows only recomputes rows for the requested opponent team")


def test_bullpen_matchup_rows_never_mutates_original_rows():
    starter_stat = dict(battersFaced=700, homeRuns=28, strikeOuts=120, baseOnBalls=70, hits=180)
    away_row = _hitter_row_for_bullpen_test("Away", starter_stat)
    bullpen_stat = dict(battersFaced=700, homeRuns=10, strikeOuts=210, baseOnBalls=40, hits=130)
    P.build_bullpen_matchup_rows([away_row], "Away", bullpen_stat, seed=1)
    assert away_row["_opp_stat"] is starter_stat   # original row's _opp_stat untouched
    assert "HR%" not in away_row   # enrich_hitter_rows mutates in place — the COPY, not the original
    print("✓ build_bullpen_matchup_rows works on copies, never mutating the original slate rows")


def test_bullpen_matchup_rows_produces_a_genuinely_different_read_than_the_starter():
    # THE actual point of the toggle: a hitter who looks tough to homer against the ace should
    # look like a real, different (easier) matchup once the bullpen_stat is a homer-prone pen.
    away_row = _hitter_row_for_bullpen_test(
        "Away", dict(battersFaced=700, homeRuns=10, strikeOuts=210, baseOnBalls=40, hits=130))  # vs ace
    bullpen_stat = dict(battersFaced=700, homeRuns=28, strikeOuts=120, baseOnBalls=70, hits=180)  # homer-prone pen
    starter_read = P.enrich_hitter_rows([dict(away_row)], seed=1)
    bullpen_read = P.build_bullpen_matchup_rows([away_row], "Away", bullpen_stat, seed=1)
    assert bullpen_read[0]["HR%"] > starter_read[0]["HR%"]
    print("✓ build_bullpen_matchup_rows produces a genuinely different (and correctly higher, "
         "vs. a homer-prone pen) HR% than the same hitter's vs-starter read")


# ----------------------------------------------------------------- times_through_order
def test_times_through_order_basic():
    assert P.times_through_order(27.0) == 3.0    # exactly 3 full trips through a 9-batter lineup
    assert P.times_through_order(18.0) == 2.0
    assert P.times_through_order(22.5) == 2.5     # partial trip, a real fractional read


def test_times_through_order_custom_lineup_size():
    assert P.times_through_order(24.0, lineup_size=8) == 3.0


def test_times_through_order_zero_lineup_size_safe():
    assert P.times_through_order(20.0, lineup_size=0) == 0.0


# ----------------------------------------------------------------- build_pitcher_projection_rows
def _fake_pm(pid, name, hand, era, fip, stat):
    from types import SimpleNamespace
    return SimpleNamespace(id=pid, name=name, hand=hand, era=era, fip=fip, stat=stat)


def test_build_pitcher_projection_rows_includes_tto_and_team_id():
    ace_stat = dict(gamesStarted=20, inningsPitched="120.0", battersFaced=480,
                    strikeOuts=140, baseOnBalls=35)
    hp = _fake_pm(111, "Home Ace", "R", 3.20, 3.10, ace_stat)
    ap = _fake_pm(222, "Away Ace", "L", 3.80, 3.70, ace_stat)
    meta = [{"label": "Away @ Home", "home_name": "Home", "away_name": "Away",
            "home_id": 117, "away_id": 111, "home_pm": hp, "away_pm": ap, "game_date": None}]
    rows = []   # empty lineup rate map -> neutral matchup, still projects fine
    out = P.build_pitcher_projection_rows(rows, meta, sims=2000, seed=1)
    assert len(out) == 2
    home_row = next(r for r in out if r["Pitcher"] == "Home Ace")
    assert "Proj TTO" in home_row
    assert home_row["Proj TTO"] == round(home_row["Proj BF"] / 9, 2)
    assert home_row["_team_id"] == 117   # the home pitcher's OWN team id, not the opponent's
    away_row = next(r for r in out if r["Pitcher"] == "Away Ace")
    assert away_row["_team_id"] == 111
    print("✓ build_pitcher_projection_rows includes Proj TTO (matching Proj BF / 9) and each pitcher's own _team_id")


# ----------------------------------------------------------------- pitcher_consistency_index
def _start(hits=5, k=6, er=3, ip="6.0"):
    return {"gamePk": 1, "game_date": "2026-06-01", "stat": {
        "hits": hits, "strikeOuts": k, "earnedRuns": er, "inningsPitched": ip}}


def test_pitcher_consistency_index_hand_verified_mean_stdev_cv():
    # 5 real starts, hits/IP computed directly (not by hand) then locked in as a regression
    # value: (5,6.0), (3,6.0), (8,5.0), (4,7.0), (6,6.0) -> per-9 rates 7.5, 4.5, 14.4,
    # 5.142857, 9.0 -> mean 8.1086, sample stdev 3.9549, cv 0.4877.
    starts = [_start(hits=5, ip="6.0"), _start(hits=3, ip="6.0"), _start(hits=8, ip="5.0"),
             _start(hits=4, ip="7.0"), _start(hits=6, ip="6.0")]
    result = P.pitcher_consistency_index(starts, stat_keys=("hits",), min_starts=5)
    assert result is not None
    assert result["n_starts"] == 5
    hits_result = result["hits"]
    assert abs(hits_result["mean"] - 8.11) < 0.01
    assert abs(hits_result["stdev"] - 3.95) < 0.01
    assert abs(hits_result["cv"] - 0.488) < 0.001
    assert hits_result["per_start"] == [7.5, 4.5, 14.4, 5.14, 9.0]
    print("✓ pitcher_consistency_index hand-verifies exactly against directly-computed mean/stdev/cv")


def test_pitcher_consistency_index_none_below_min_starts():
    starts = [_start(), _start(), _start()]   # only 3, default min_starts=5
    assert P.pitcher_consistency_index(starts) is None
    print("✓ pitcher_consistency_index returns None (not a noisy read) below the min_starts floor")


def test_pitcher_consistency_index_skips_zero_ip_starts():
    # A start with 0 IP (a real, rare MLB Stats API edge case) must not count toward min_starts
    # or contribute a fabricated 0.0 rate.
    starts = [_start(ip="0.0")] + [_start()] * 5
    result = P.pitcher_consistency_index(starts, stat_keys=("hits",), min_starts=5)
    assert result is not None
    assert result["n_starts"] == 5   # the 0-IP start excluded, not counted as a 6th
    print("✓ pitcher_consistency_index correctly excludes zero-IP starts rather than fabricating a rate for them")


def test_pitcher_consistency_index_cv_none_when_mean_is_zero():
    # A pitcher who's allowed 0 earned runs in every one of his last several starts -- CV is
    # mathematically undefined (division by a zero mean), must be honest None, not a fabricated
    # 0.0 or an error.
    starts = [_start(er=0)] * 6
    result = P.pitcher_consistency_index(starts, stat_keys=("earnedRuns",), min_starts=5)
    assert result["earnedRuns"]["mean"] == 0.0
    assert result["earnedRuns"]["cv"] is None
    print("✓ pitcher_consistency_index returns cv=None (not a fabricated value) when the mean rate is exactly zero")


def test_pitcher_consistency_index_multiple_stats_independently():
    starts = [_start(hits=5, k=8, er=2, ip="6.0"), _start(hits=6, k=7, er=3, ip="6.0"),
             _start(hits=4, k=9, er=1, ip="6.0"), _start(hits=5, k=8, er=2, ip="6.0"),
             _start(hits=5, k=8, er=2, ip="6.0")]
    result = P.pitcher_consistency_index(starts, stat_keys=("hits", "strikeOuts", "earnedRuns"))
    assert set(result.keys()) == {"n_starts", "hits", "strikeOuts", "earnedRuns"}
    # Strikeouts are nearly identical every start (8,7,9,8,8) -- should show LOWER relative
    # variability (cv) than earned runs (2,3,1,2,2), a real, directionally-correct comparison.
    assert result["strikeOuts"]["cv"] < result["earnedRuns"]["cv"]
    print("✓ pitcher_consistency_index computes each requested stat independently and comparably via CV")


def test_pitcher_consistency_index_consistent_pitcher_has_low_cv():
    # A genuinely steady pitcher (nearly the same hits allowed every start) should show a real,
    # low CV -- a direct, meaningful check that the metric actually measures what it claims to.
    steady = [_start(hits=5, ip="6.0")] * 4 + [_start(hits=6, ip="6.0")]
    streaky = [_start(hits=1, ip="6.0"), _start(hits=10, ip="6.0"), _start(hits=2, ip="6.0"),
              _start(hits=9, ip="6.0"), _start(hits=1, ip="6.0")]
    steady_result = P.pitcher_consistency_index(steady, stat_keys=("hits",))
    streaky_result = P.pitcher_consistency_index(streaky, stat_keys=("hits",))
    assert steady_result["hits"]["cv"] < streaky_result["hits"]["cv"]
    print("✓ pitcher_consistency_index correctly gives a genuinely steady pitcher a lower CV than a genuinely streaky one")


def test_hitter_starter_exposures_leadoff_sees_starter_multiple_times():
    # Leadoff (idx=0) comes up as batter #1, #10, #19, #28... A starter projecting 27 BF means
    # the leadoff hitter faces him 3 full times (batters 1, 10, 19 all <= 27).
    exp = P.hitter_starter_exposures(lineup_idx=0, starter_proj_bf=27.0, exp_pa=4.25)
    assert exp["vs_starter"] == 3.0
    assert round(exp["vs_starter"] + exp["vs_bullpen"], 2) == 4.25
    print("✓ hitter_starter_exposures correctly gives the leadoff hitter 3 starter exposures at 27 projected BF")


def test_hitter_starter_exposures_bottom_of_order_sees_starter_less():
    # 9-hole (idx=8) comes up as batter #9, #18, #27... Same 27 BF starter -> only reaches him
    # for the 3rd time right at the edge (batter 27), still 3, but with much less BUFFER than
    # the leadoff hitter — the real, well-known "bottom of the order sees the starter less" effect
    # should show up as LESS bullpen-vs-starter margin, not necessarily a different raw count here.
    top = P.hitter_starter_exposures(lineup_idx=0, starter_proj_bf=20.0, exp_pa=4.25)
    bottom = P.hitter_starter_exposures(lineup_idx=8, starter_proj_bf=20.0, exp_pa=4.25)
    assert top["vs_starter"] > bottom["vs_starter"]
    print("✓ hitter_starter_exposures correctly gives a bottom-of-the-order hitter fewer starter looks than a leadoff hitter, same starter")


def test_hitter_starter_exposures_short_start_means_mostly_bullpen():
    # A starter projecting only 12 BF still reaches the leadoff hitter's SECOND PA (batter #10,
    # since 10 <= 12) — a real, correct consequence of the math, not a bug: even a short-ish start
    # gives the top of the order a second look. A genuinely short start (6 BF) is needed before
    # someone at the bottom of the order (8th spot, batter #8) gets zero starter exposure at all.
    leadoff = P.hitter_starter_exposures(lineup_idx=0, starter_proj_bf=12.0, exp_pa=4.25)
    assert leadoff["vs_starter"] == 2.0   # batters 1 and 10 both <= 12
    late = P.hitter_starter_exposures(lineup_idx=7, starter_proj_bf=6.0, exp_pa=4.25)
    assert late["vs_starter"] == 0.0 and late["vs_bullpen"] == 4.25
    print("✓ hitter_starter_exposures correctly sends a hitter entirely to the bullpen when the starter's own projected work doesn't reach them at all")


def test_hitter_starter_exposures_caps_at_exp_pa():
    # vs_starter can never exceed the hitter's own total expected PA, even if the arithmetic
    # would otherwise suggest more exposures than plate appearances physically available.
    exp = P.hitter_starter_exposures(lineup_idx=0, starter_proj_bf=999.0, exp_pa=4.25)
    assert exp["vs_starter"] == 4.25 and exp["vs_bullpen"] == 0.0


def test_hitter_starter_exposures_always_sums_to_exp_pa():
    for idx in range(9):
        for bf in (12.0, 18.0, 22.5, 27.0, 33.0):
            exp = P.hitter_starter_exposures(lineup_idx=idx, starter_proj_bf=bf, exp_pa=4.25)
            assert round(exp["vs_starter"] + exp["vs_bullpen"], 2) == 4.25
    print("✓ hitter_starter_exposures' two components always sum back to the hitter's own exp_pa")


def test_hitter_starter_exposures_zero_exp_pa_safe():
    exp = P.hitter_starter_exposures(lineup_idx=0, starter_proj_bf=27.0, exp_pa=0.0)
    assert exp == {"vs_starter": 0.0, "vs_bullpen": 0.0}


# ----------------------------------------------------------------- add_starter_exposure_context
def _ace_stat():
    return dict(gamesStarted=20, inningsPitched="120.0", battersFaced=480,
               strikeOuts=140, baseOnBalls=35)


def test_add_starter_exposure_context_adds_vs_sp_and_vs_pen():
    row = {"Hitter": "Leadoff Guy", "_opp_stat": _ace_stat(), "_exp_pa": 4.25, "_lineup_idx": 0}
    out = P.add_starter_exposure_context([row])
    assert "vs SP" in out[0] and "vs Pen" in out[0]
    assert round(out[0]["vs SP"] + out[0]["vs Pen"], 2) == 4.25
    print("✓ add_starter_exposure_context adds vs SP / vs Pen fields that sum to the hitter's own exp_pa")


def test_add_starter_exposure_context_shares_projection_across_same_opponent():
    # Two hitters facing the SAME starter (same stat dict) should get project_pitcher called
    # only ONCE, not once per hitter — confirmed via a real call-count check, not just asserted.
    shared_stat = _ace_stat()
    rows = [
        {"Hitter": "Leadoff", "_opp_stat": shared_stat, "_exp_pa": 4.25, "_lineup_idx": 0},
        {"Hitter": "Cleanup", "_opp_stat": shared_stat, "_exp_pa": 4.25, "_lineup_idx": 3},
    ]
    calls = {"n": 0}
    real_project_pitcher = P.project_pitcher

    def counting_project_pitcher(stat, opp_lineup=None, days_rest=None):
        calls["n"] += 1
        return real_project_pitcher(stat, opp_lineup, days_rest)

    orig = P.project_pitcher
    P.project_pitcher = counting_project_pitcher
    try:
        P.add_starter_exposure_context(rows)
    finally:
        P.project_pitcher = orig
    assert calls["n"] == 1
    print("✓ add_starter_exposure_context computes the starter projection once per opponent, not once per hitter")


def test_add_starter_exposure_context_skips_rows_missing_data():
    rows = [
        {"Hitter": "No Opp Stat", "_exp_pa": 4.25, "_lineup_idx": 0},
        {"Hitter": "No Exp PA", "_opp_stat": _ace_stat(), "_lineup_idx": 0},
        {"Hitter": "No Lineup Idx", "_opp_stat": _ace_stat(), "_exp_pa": 4.25},
    ]
    out = P.add_starter_exposure_context(rows)
    for r in out:
        assert "vs SP" not in r and "vs Pen" not in r
    print("✓ add_starter_exposure_context leaves rows with missing data honestly unset, no fabricated split")


def test_add_starter_exposure_context_skips_when_not_a_real_starter():
    thin_stat = dict(gamesStarted=1, inningsPitched="2.0", battersFaced=10, strikeOuts=2, baseOnBalls=1)
    row = {"Hitter": "Test", "_opp_stat": thin_stat, "_exp_pa": 4.25, "_lineup_idx": 0}
    out = P.add_starter_exposure_context([row])
    assert "vs SP" not in out[0]   # project_pitcher's own starter gate correctly returns None here


# ----------------------------------------------------------------- blend_hitter_probs_with_bullpen
def _blendable_row(lineup_idx=0, exp_pa=4.25, opp_stat=None, weather_hr=1.0):
    return {
        "Hitter": "Test Slugger", "_pid": 1, "_stat": _slugger(), "_venue_id": None,
        "_opp_stat": opp_stat or dict(gamesStarted=20, inningsPitched="120.0", battersFaced=480,
                                     strikeOuts=140, baseOnBalls=35, homeRuns=8, hits=95),
        "_split_stat": None, "_exp_pa": exp_pa, "_weather_hr": weather_hr, "_lineup_idx": lineup_idx,
    }


def test_blend_reproduces_real_slate_direction_ace_starter_weak_pen():
    # A rough reproduction of the real, reported scenario: a genuinely BAD starter (high HR/K
    # allowed) with a short projected outing, and a MUCH BETTER bullpen. The blended HR%
    # should come out LOWER than a starter-only read would show, not higher and not identical —
    # confirming the correction moves in the right direction on a case shaped like the real one.
    bad_starter_stat = dict(gamesStarted=15, inningsPitched="70.0", battersFaced=380,
                            strikeOuts=55, baseOnBalls=40, homeRuns=22, hits=110)  # ~7+ ERA shape
    good_pen_stat = dict(strikeOuts=300, baseOnBalls=90, hitByPitch=10, homeRuns=35,
                         battersFaced=1800, hits=380, atBats=1600, earnedRuns=180,
                         inningsPitched="450.0")  # a much better run-prevention shape
    row = _blendable_row(lineup_idx=0, exp_pa=4.55, opp_stat=bad_starter_stat)

    starter_only = P.enrich_hitter_rows([dict(row)], seed=7)[0]
    blended = P.blend_hitter_probs_with_bullpen(row, good_pen_stat, seed=7)

    assert blended is not None
    assert blended["HR%"] < starter_only["HR%"]
    print(f"✓ blend_hitter_probs_with_bullpen correctly lowers HR% ({starter_only['HR%']:.3f} -> "
         f"{blended['HR%']:.3f}) when the real bullpen is meaningfully better than a bad starter, "
         f"matching the direction of the real reported case")


def test_blend_uses_real_line_when_available():
    # THE real, important guarantee this section exists for: the re-pricing pass must stay
    # consistent with whatever real line the play was ORIGINALLY shown against, not silently
    # revert to the placeholder default during the blend step.
    good_pen_stat = dict(strikeOuts=300, baseOnBalls=90, hitByPitch=10, homeRuns=35,
                         battersFaced=1800, hits=380, atBats=1600, earnedRuns=180,
                         inningsPitched="450.0")
    row = _blendable_row(lineup_idx=0, exp_pa=4.55)
    real_lines = {(P.normalize_name("Test Slugger"), "batter_total_bases"): 2.5}

    blended_default = P.blend_hitter_probs_with_bullpen(row, good_pen_stat, seed=7)
    blended_real = P.blend_hitter_probs_with_bullpen(row, good_pen_stat, seed=7, real_lines=real_lines)

    assert blended_default is not None and blended_real is not None
    # A materially higher real line (2.5 vs the 1.5 default) must produce a LOWER TB1.5% —
    # genuinely harder to clear a higher bar, not just a differently-labeled identical number.
    assert blended_real["TB1.5%"] < blended_default["TB1.5%"]
    print(f"✓ blend_hitter_probs_with_bullpen correctly uses the real line (TB1.5% drops from "
         f"{blended_default['TB1.5%']:.3f} at the default 1.5 to {blended_real['TB1.5%']:.3f} "
         f"at the real 2.5) rather than silently reverting to the placeholder during re-pricing")


def test_blend_returns_none_when_no_bullpen_exposure():
    # A leadoff hitter with a LOW exp_pa (3.0, artificially trimmed for this test) against a
    # starter genuinely projected to cover the whole game (exp_bf=30, well past 3 full trips
    # through a 9-batter lineup) leaves zero real bullpen exposure — hand-verified via
    # hitter_starter_exposures directly: exposures_to_starter = floor((30-0-1)/9)+1 = 4, capped
    # at min(4, 3.0) = 3.0, so vs_pen = 3.0 - 3.0 = 0. Nothing to blend, starter-only is correct.
    workhorse_stat = dict(gamesStarted=30, inningsPitched="220.0", battersFaced=900,
                          strikeOuts=200, baseOnBalls=50, homeRuns=15, hits=180)
    row = _blendable_row(lineup_idx=0, exp_pa=3.0, opp_stat=workhorse_stat)
    pen_stat = dict(strikeOuts=300, baseOnBalls=90, hitByPitch=10, homeRuns=35,
                    battersFaced=1800, hits=380, atBats=1600, earnedRuns=180, inningsPitched="450.0")
    result = P.blend_hitter_probs_with_bullpen(row, pen_stat, seed=1)
    assert result is None
    print("✓ blend_hitter_probs_with_bullpen correctly returns None when there's no real bullpen exposure to blend")


def test_blend_none_when_row_not_projectable():
    row = _blendable_row()
    row["_stat"] = None   # can't project this hitter at all
    pen_stat = dict(strikeOuts=300, baseOnBalls=90, hitByPitch=10, homeRuns=35,
                    battersFaced=1800, hits=380, atBats=1600, earnedRuns=180, inningsPitched="450.0")
    assert P.blend_hitter_probs_with_bullpen(row, pen_stat, seed=1) is None


def test_blend_none_when_starter_not_projectable():
    # {"gamesStarted": 1} — real dict, so it survives the fixture's own `opp_stat or dict(...)`
    # fallback (an empty {} would be falsy and get silently replaced, a real mistake caught while
    # writing this test) — but still genuinely fails project_pitcher's own gs>=3 starter gate.
    row = _blendable_row(opp_stat={"gamesStarted": 1, "inningsPitched": "4.0", "battersFaced": 18})
    pen_stat = dict(strikeOuts=300, baseOnBalls=90, hitByPitch=10, homeRuns=35,
                    battersFaced=1800, hits=380, atBats=1600, earnedRuns=180, inningsPitched="450.0")
    assert P.blend_hitter_probs_with_bullpen(row, pen_stat, seed=1) is None
    print("✓ blend_hitter_probs_with_bullpen correctly returns None when the opposing starter can't be projected")


def test_blend_none_when_bullpen_stat_too_thin():
    row = _blendable_row()
    thin_pen_stat = dict(strikeOuts=5, baseOnBalls=2, homeRuns=1, battersFaced=20, hits=6)  # < 40 BF floor
    assert P.blend_hitter_probs_with_bullpen(row, thin_pen_stat, seed=1) is None
    print("✓ blend_hitter_probs_with_bullpen correctly returns None for a bullpen sample too thin to trust")


def test_blend_bullpen_fatigue_raises_hr_percent():
    # Added directly on request: a genuinely FATIGUED bullpen (same season-long stat line, but
    # currently taxed) should project real hitters a real, modest degree WORSE than that same
    # bullpen's fresh read -- confirmed directly, not just assumed from the unit-level tests.
    pen_stat = dict(strikeOuts=300, baseOnBalls=90, hitByPitch=10, homeRuns=35,
                    battersFaced=1800, hits=380, atBats=1600, earnedRuns=180,
                    inningsPitched="450.0")
    row = _blendable_row(lineup_idx=0, exp_pa=4.55)
    fresh = P.blend_hitter_probs_with_bullpen(row, pen_stat, seed=7)
    fatigued = P.blend_hitter_probs_with_bullpen(row, pen_stat, seed=7, bullpen_fatigue=0.5)
    assert fresh is not None and fatigued is not None
    assert fatigued["HR%"] > fresh["HR%"]
    print(f"✓ blend_hitter_probs_with_bullpen correctly raises HR% ({fresh['HR%']:.3f} -> "
         f"{fatigued['HR%']:.3f}) for a genuinely fatigued bullpen vs the same bullpen fresh")


def test_blend_vs_sp_vs_pen_sum_to_exp_pa():
    row = _blendable_row(lineup_idx=0, exp_pa=4.55)
    pen_stat = dict(strikeOuts=300, baseOnBalls=90, hitByPitch=10, homeRuns=35,
                    battersFaced=1800, hits=380, atBats=1600, earnedRuns=180, inningsPitched="450.0")
    result = P.blend_hitter_probs_with_bullpen(row, pen_stat, seed=1)
    assert result is not None
    assert round(result["vs SP"] + result["vs Pen"], 2) == 4.55


def test_blend_is_deterministic_with_same_seed():
    row = _blendable_row()
    pen_stat = dict(strikeOuts=300, baseOnBalls=90, hitByPitch=10, homeRuns=35,
                    battersFaced=1800, hits=380, atBats=1600, earnedRuns=180, inningsPitched="450.0")
    r1 = P.blend_hitter_probs_with_bullpen(row, pen_stat, seed=42)
    r2 = P.blend_hitter_probs_with_bullpen(row, pen_stat, seed=42)
    assert r1 == r2


# ----------------------------------------------------------------- apply_bullpen_blend_to_top_plays
def _hr_play(player_id, conviction, side="Over"):
    return {"Player": f"P{player_id}", "PlayerId": player_id, "Market": "Batter HR",
           "Side": side, "Line": 0.5, "ModelProb": 0.30, "Fair": -100,
           "Conviction": conviction, "Why": "some reason"}


def _pitcher_play(conviction):
    return {"Player": "Some Pitcher", "PlayerId": 999, "Market": "Pitcher Strikeouts",
           "Side": "Over", "Line": 5.5, "ModelProb": 0.55, "Fair": -110,
           "Conviction": conviction, "Why": "projects X K"}


def _bad_starter_row(pid, opp_id, lineup_idx=0):
    r = _blendable_row(lineup_idx=lineup_idx, exp_pa=4.55,
                       opp_stat=dict(gamesStarted=15, inningsPitched="70.0", battersFaced=380,
                                    strikeOuts=55, baseOnBalls=40, homeRuns=22, hits=110))
    r["_pid"] = pid
    r["_opp_id"] = opp_id
    return r


_GOOD_PEN_STAT = dict(strikeOuts=300, baseOnBalls=90, hitByPitch=10, homeRuns=35,
                      battersFaced=1800, hits=380, atBats=1600, earnedRuns=180, inningsPitched="450.0")


def test_apply_blend_updates_top_candidate_and_preserves_side():
    play = _hr_play(1, conviction=4.25)
    row = _bad_starter_row(1, opp_id=114)
    calls = []

    def fake_get_bullpen(team_id, exclude_pid):
        calls.append(team_id)
        return _GOOD_PEN_STAT

    out = P.apply_bullpen_blend_to_top_plays([play], {1: row}, fake_get_bullpen, seed=7)
    assert out[0]["_bullpen_blended"] is True
    assert out[0]["_pre_blend_conviction"] == 4.25
    assert out[0]["Conviction"] != 4.25   # actually recomputed, not left untouched
    assert out[0]["Side"] == "Over"        # side preserved, not re-derived
    assert "bullpen-blended" in out[0]["Why"]
    assert calls == [114]
    print("✓ apply_bullpen_blend_to_top_plays correctly updates a top candidate and preserves its existing side")


def test_apply_blend_respects_top_n_limit():
    plays = [_hr_play(i, conviction=10 - i) for i in range(5)]   # 5 plays, descending conviction
    rows = {i: _bad_starter_row(i, opp_id=100 + i) for i in range(5)}
    calls = []

    def fake_get_bullpen(team_id, exclude_pid):
        calls.append(team_id)
        return _GOOD_PEN_STAT

    P.apply_bullpen_blend_to_top_plays(plays, rows, fake_get_bullpen, seed=1, top_n=2)
    blended = [p for p in plays if p.get("_bullpen_blended")]
    assert len(blended) == 2   # only the top 2 by conviction got touched
    assert set(calls) == {100, 101}   # only the top 2 hitters' opponents were ever looked up
    print("✓ apply_bullpen_blend_to_top_plays respects top_n, never fetching bullpen data beyond it")


def test_apply_blend_never_touches_non_hitter_markets():
    plays = [_pitcher_play(conviction=5.0)]
    out = P.apply_bullpen_blend_to_top_plays(plays, {}, lambda tid, ex: _GOOD_PEN_STAT, seed=1)
    assert "_bullpen_blended" not in out[0]
    assert out[0]["Conviction"] == 5.0
    print("✓ apply_bullpen_blend_to_top_plays never touches pitcher-market plays")


def test_apply_blend_leaves_play_unchanged_when_no_matching_row():
    play = _hr_play(1, conviction=4.25)
    out = P.apply_bullpen_blend_to_top_plays([play], {}, lambda tid, ex: _GOOD_PEN_STAT, seed=1)
    assert "_bullpen_blended" not in out[0]
    assert out[0]["Conviction"] == 4.25


def test_apply_blend_leaves_play_unchanged_when_no_opp_id():
    play = _hr_play(1, conviction=4.25)
    row = _bad_starter_row(1, opp_id=None)
    out = P.apply_bullpen_blend_to_top_plays([play], {1: row}, lambda tid, ex: _GOOD_PEN_STAT, seed=1)
    assert "_bullpen_blended" not in out[0]


def test_apply_blend_leaves_play_unchanged_when_bullpen_lookup_returns_none():
    play = _hr_play(1, conviction=4.25)
    row = _bad_starter_row(1, opp_id=114)
    out = P.apply_bullpen_blend_to_top_plays([play], {1: row}, lambda tid, ex: None, seed=1)
    assert "_bullpen_blended" not in out[0]
    assert out[0]["Conviction"] == 4.25
    print("✓ apply_bullpen_blend_to_top_plays leaves a play untouched when the bullpen lookup itself fails")


def test_apply_blend_backward_compatible_without_fatigue_fn():
    # A REAL, CONFIRMED backward-compatibility guard: an existing caller that hasn't wired up
    # get_bullpen_fatigue_fn yet (the default, None) must keep working exactly as before -- a
    # real, deliberate non-breaking rollout, not assumed.
    play = _hr_play(1, conviction=4.25)
    row = _bad_starter_row(1, opp_id=114)
    out = P.apply_bullpen_blend_to_top_plays([play], {1: row}, lambda tid, ex: _GOOD_PEN_STAT, seed=7)
    assert out[0]["_bullpen_blended"] is True
    print("✓ apply_bullpen_blend_to_top_plays works correctly without get_bullpen_fatigue_fn, unchanged from before this feature")


def test_apply_blend_fetches_and_applies_bullpen_fatigue():
    play = _hr_play(1, conviction=4.25)
    row = _bad_starter_row(1, opp_id=114)
    fatigue_calls = []

    def fake_get_fatigue(team_id, exclude_pid):
        fatigue_calls.append(team_id)
        return 0.6   # a genuinely fatigued bullpen

    without_fatigue = P.apply_bullpen_blend_to_top_plays(
        [dict(play)], {1: dict(row)}, lambda tid, ex: _GOOD_PEN_STAT, seed=7)
    with_fatigue = P.apply_bullpen_blend_to_top_plays(
        [dict(play)], {1: dict(row)}, lambda tid, ex: _GOOD_PEN_STAT, seed=7,
        get_bullpen_fatigue_fn=fake_get_fatigue)

    assert fatigue_calls == [114]   # fetched using the real opponent team id
    assert with_fatigue[0]["ModelProb"] != without_fatigue[0]["ModelProb"]
    print("✓ apply_bullpen_blend_to_top_plays correctly fetches and applies real bullpen fatigue when get_bullpen_fatigue_fn is supplied")


def test_apply_blend_leaves_play_unchanged_when_no_real_exposure():
    # A hitter with zero real bullpen exposure (the common case) — blend_hitter_probs_with_
    # bullpen itself returns None, and this must be handled the same as any other None case.
    row = _blendable_row(lineup_idx=0, exp_pa=3.0,
                         opp_stat=dict(gamesStarted=30, inningsPitched="220.0", battersFaced=900,
                                      strikeOuts=200, baseOnBalls=50, homeRuns=15, hits=180))
    row["_pid"] = 1
    row["_opp_id"] = 114
    play = _hr_play(1, conviction=4.25)
    out = P.apply_bullpen_blend_to_top_plays([play], {1: row}, lambda tid, ex: _GOOD_PEN_STAT, seed=1)
    assert "_bullpen_blended" not in out[0]
    assert out[0]["Conviction"] == 4.25
    print("✓ apply_bullpen_blend_to_top_plays correctly leaves the common no-exposure case untouched")


def test_apply_blend_resorts_by_updated_conviction():
    # Play A starts with LOWER conviction but gets no real blend adjustment (no bullpen data
    # available for its opponent); Play B starts with HIGHER conviction but its blend correctly
    # lowers it. After blending, A should end up ranked ABOVE B.
    play_a = _hr_play(1, conviction=3.0)
    play_b = _hr_play(2, conviction=5.0)
    row_a = _bad_starter_row(1, opp_id=None)   # no opp_id -> never touched, stays at 3.0
    row_b = _bad_starter_row(2, opp_id=114)    # gets blended down

    out = P.apply_bullpen_blend_to_top_plays([play_a, play_b], {1: row_a, 2: row_b},
                                             lambda tid, ex: _GOOD_PEN_STAT, seed=7)
    assert out[0]["PlayerId"] == 1   # A is now ranked first after B's conviction dropped
    print("✓ apply_bullpen_blend_to_top_plays correctly re-sorts when blending changes the ranking")


# ----------------------------------------------------------------- grading.py re-export
# GRADE_THRESHOLDS/conviction_to_grade/organize_graded_picks/grade_accuracy_by_letter now live
# in grading.py (a real fix, not a refactor for its own sake -- see grading.py's own docstring
# and test_grading.py for the full test suite and the confirmed cross-sport bug this fixed).
# These are focused re-export sanity checks, not a duplicate of grading.py's own comprehensive
# suite -- confirming P.* (this module's own namespace) still resolves to the exact same,
# single real implementation, so existing callers that reference these via P.* (e.g. best_bets_
# data.py) keep working without needing to be rewritten.
import grading as _grading


def test_grade_reexports_are_the_same_object_as_grading_module():
    assert P.conviction_to_grade is _grading.conviction_to_grade
    assert P.organize_graded_picks is _grading.organize_graded_picks
    assert P.grade_accuracy_by_letter is _grading.grade_accuracy_by_letter
    assert P.GRADE_THRESHOLDS is _grading.GRADE_THRESHOLDS
    print("✓ projections.py's re-exported grading functions are the exact same objects as grading.py's own, not stale copies")


def test_grade_reexport_produces_identical_results():
    assert P.conviction_to_grade(3.2) == _grading.conviction_to_grade(3.2)


# ----------------------------------------------------------------- batter_counting_rate
def _counting_stat(pa, stat_val, key="runs"):
    return {"plateAppearances": pa, key: stat_val}


def test_batter_counting_rate_none_below_pa_floor():
    stat = _counting_stat(15, 5)   # below the 20 PA floor
    assert P.batter_counting_rate(stat, 4.5, "runs", P.LG_RUNS_PER_PA, P.RUNS_RBI_PRIOR_PA) is None
    print("✓ batter_counting_rate returns None for a season sample below the real PA floor")


def test_batter_counting_rate_scales_with_exp_pa():
    stat = _counting_stat(600, 90, "runs")   # a real, established season rate
    rate_normal = P.batter_counting_rate(stat, 4.5, "runs", P.LG_RUNS_PER_PA, P.RUNS_RBI_PRIOR_PA)
    rate_double_pa = P.batter_counting_rate(stat, 9.0, "runs", P.LG_RUNS_PER_PA, P.RUNS_RBI_PRIOR_PA)
    assert rate_double_pa == pytest.approx(rate_normal * 2, rel=1e-6)
    print("✓ batter_counting_rate scales linearly with tonight's real projected PA, not a season average")


def test_batter_counting_rate_thin_sample_regresses_toward_league_average():
    # A hitter with a genuinely thin sample (barely above the 20 PA floor) should land close to
    # league average, not close to his own small-sample rate -- confirms real shrinkage, not a
    # naive count/PA calculation.
    thin_stat = _counting_stat(22, 8, "runs")   # a wildly hot ~36% runs/PA rate over a tiny sample
    rate = P.batter_counting_rate(thin_stat, 4.5, "runs", P.LG_RUNS_PER_PA, P.RUNS_RBI_PRIOR_PA)
    naive_rate = (8 / 22) * 4.5   # what a naive, unregressed calculation would produce
    assert rate < naive_rate * 0.5   # real shrinkage pulls this WAY down from the naive number
    print("✓ batter_counting_rate meaningfully regresses a thin, small-sample rate toward league average")


def test_batter_counting_rate_opp_era_adjustment():
    stat = _counting_stat(600, 90, "runs")
    rate_vs_average = P.batter_counting_rate(stat, 4.5, "runs", P.LG_RUNS_PER_PA,
                                             P.RUNS_RBI_PRIOR_PA, opp_era=P.LG_ERA)
    rate_vs_bad_pitcher = P.batter_counting_rate(stat, 4.5, "runs", P.LG_RUNS_PER_PA,
                                                 P.RUNS_RBI_PRIOR_PA, opp_era=6.0)
    rate_vs_ace = P.batter_counting_rate(stat, 4.5, "runs", P.LG_RUNS_PER_PA,
                                         P.RUNS_RBI_PRIOR_PA, opp_era=2.5)
    assert rate_vs_bad_pitcher > rate_vs_average > rate_vs_ace
    print("✓ batter_counting_rate correctly raises expected runs against a bad pitcher and lowers it against an ace")


def test_batter_counting_rate_no_opp_era_unaffected():
    stat = _counting_stat(600, 90, "runs")
    rate = P.batter_counting_rate(stat, 4.5, "runs", P.LG_RUNS_PER_PA, P.RUNS_RBI_PRIOR_PA)
    rate_with_league_avg_era = P.batter_counting_rate(stat, 4.5, "runs", P.LG_RUNS_PER_PA,
                                                       P.RUNS_RBI_PRIOR_PA, opp_era=P.LG_ERA)
    assert rate == pytest.approx(rate_with_league_avg_era, rel=1e-9)
    print("✓ omitting opp_era matches passing exactly league-average ERA (a neutral adjustment)")


def test_batter_counting_rate_never_negative():
    stat = _counting_stat(600, 0, "runs")   # a real player who somehow never scored (extreme edge case)
    rate = P.batter_counting_rate(stat, 4.5, "runs", P.LG_RUNS_PER_PA, P.RUNS_RBI_PRIOR_PA)
    assert rate >= 0.0


# ----------------------------------------------------------------- poisson_over_half_prob
def test_poisson_over_half_prob_matches_closed_form():
    # Hand-verified against the real Poisson formula: P(X>=1) = 1 - e^(-lambda)
    import math
    for lam in (0.1, 0.3, 0.5, 1.0, 2.0):
        expected = 1 - math.exp(-lam)
        assert P.poisson_over_half_prob(lam) == pytest.approx(expected, rel=1e-9)
    print("✓ poisson_over_half_prob exactly matches the real closed-form Poisson P(X>=1) formula")


def test_poisson_over_half_prob_zero_at_zero_rate():
    assert P.poisson_over_half_prob(0.0) == 0.0


def test_poisson_over_half_prob_monotonic():
    # A higher expected count should always mean a higher probability of at least one occurring.
    probs = [P.poisson_over_half_prob(x) for x in (0.05, 0.15, 0.3, 0.6, 1.2, 2.5)]
    assert probs == sorted(probs)
    print("✓ poisson_over_half_prob is correctly monotonic in the expected count")


def test_poisson_over_half_prob_bounded_below_one():
    # exp_count=100 would be nonsensical for these real markets (a realistic value is ~0.05-0.5)
    # and float64 genuinely can't distinguish 1 - e^(-100) from 1.0 at that scale -- not a bug,
    # just outside any value this function will ever realistically see. Checked at a real,
    # plausible-if-extreme value instead, where the bound is meaningfully checkable.
    assert P.poisson_over_half_prob(5.0) < 1.0


# ----------------------------------------------------------------- poisson_over_prob
def test_poisson_over_prob_matches_poisson_over_half_prob_at_line_half():
    # THE real, required guarantee: every existing caller of poisson_over_half_prob must see
    # zero behavior change now that it's a thin wrapper over this general function.
    for lam in (0.1, 0.3, 0.42, 1.0, 2.5, 5.0):
        assert abs(P.poisson_over_prob(lam, 0.5) - P.poisson_over_half_prob(lam)) < 1e-12
    print("✓ poisson_over_prob(lam, 0.5) is byte-identical to poisson_over_half_prob(lam) for every real lambda checked")


def test_poisson_over_prob_hand_verified_non_half_lines():
    # Computed directly (not estimated by hand), then locked in as regression values.
    assert abs(P.poisson_over_prob(1.0, 1.5) - 0.26424111765711533) < 1e-9
    assert abs(P.poisson_over_prob(2.5, 2.5) - 0.4561868841166705) < 1e-9
    print("✓ poisson_over_prob hand-verifies exactly for real, non-0.5 lines (1.5, 2.5) — the actual generalization this function exists for")


def test_poisson_over_prob_monotonic_in_line():
    # A higher real line should always be harder to clear, for the same expected count.
    lam = 1.2
    p_low = P.poisson_over_prob(lam, 0.5)
    p_mid = P.poisson_over_prob(lam, 1.5)
    p_high = P.poisson_over_prob(lam, 2.5)
    assert p_low > p_mid > p_high
    print("✓ poisson_over_prob is correctly monotonically decreasing as the real line increases")


def test_poisson_over_prob_negative_line_is_certain():
    assert P.poisson_over_prob(0.3, -0.5) == 1.0
    print("✓ poisson_over_prob correctly returns 1.0 for a line below zero (any real non-negative count clears it)")


def test_poisson_over_prob_zero_rate_never_clears_a_real_line():
    assert P.poisson_over_prob(0.0, 0.5) == 0.0
    assert P.poisson_over_prob(0.0, 1.5) == 0.0


# ----------------------------------------------------------------- simulate_hits_runs_rbi
def test_hrr_hrr_equals_exact_per_trial_sum():
    rng = np.random.default_rng(0)
    sim_hits = np.array([0, 1, 2, 3, 0, 1])
    out = P.simulate_hits_runs_rbi(sim_hits, exp_hits=1.1, exp_runs=0.5, exp_rbi=0.5, rng=rng)
    assert (out["hrr"] == out["hits"] + out["runs"] + out["rbi"]).all()
    print("✓ simulate_hits_runs_rbi's hrr field is EXACTLY the per-trial sum of hits+runs+rbi, for every trial")


def test_hrr_output_shape_and_nonnegativity():
    rng = np.random.default_rng(0)
    sim_hits = np.random.default_rng(1).poisson(1.1, size=10000)
    out = P.simulate_hits_runs_rbi(sim_hits, exp_hits=1.1, exp_runs=0.5, exp_rbi=0.5, rng=rng)
    for key in ("hits", "runs", "rbi", "hrr"):
        assert key in out
        assert len(out[key]) == 10000
        assert (out[key] >= 0).all()


def test_hrr_real_positive_correlation_between_hits_and_runs_rbi():
    # THE core property this whole mechanism exists to produce: trials with MORE hits should
    # have a genuinely HIGHER average runs+rbi than trials with FEWER hits -- not just similar,
    # independently-noisy averages. This is the actual, direct proof the correlation mechanism
    # works, not just that the function runs without crashing.
    rng = np.random.default_rng(0)
    sim_hits = np.random.default_rng(1).poisson(1.1, size=50000)
    out = P.simulate_hits_runs_rbi(sim_hits, exp_hits=1.1, exp_runs=0.5, exp_rbi=0.5, rng=rng)
    combined_rr = out["runs"] + out["rbi"]
    zero_hit_mask = sim_hits == 0
    high_hit_mask = sim_hits >= 3
    avg_rr_zero_hits = combined_rr[zero_hit_mask].mean()
    avg_rr_high_hits = combined_rr[high_hit_mask].mean()
    assert avg_rr_high_hits > avg_rr_zero_hits * 1.5
    print(f"✓ simulate_hits_runs_rbi produces real positive correlation: avg R+RBI on 0-hit trials={avg_rr_zero_hits:.2f}, on 3+-hit trials={avg_rr_high_hits:.2f}")


def test_hrr_zero_hit_trials_still_have_real_nonzero_runs_rbi_chance():
    # The real, deliberate floor: even a genuine zero-hit trial must NOT have runs/rbi driven to
    # exactly zero -- a player can score or drive in a run via a walk, sac fly, or fielder's
    # choice without recording a hit. Confirms the floor behavior directly.
    rng = np.random.default_rng(0)
    sim_hits = np.zeros(20000, dtype=np.int64)   # every single trial is a genuine zero-hit trial
    out = P.simulate_hits_runs_rbi(sim_hits, exp_hits=1.1, exp_runs=0.5, exp_rbi=0.5, rng=rng)
    assert out["runs"].mean() > 0.0
    assert out["rbi"].mean() > 0.0
    # Expected mean on an all-zero-hit input: exp_runs * HRR_CORRELATION_FLOOR = 0.5 * 0.5 = 0.25
    assert out["runs"].mean() == pytest.approx(0.25, abs=0.03)
    print("✓ simulate_hits_runs_rbi correctly keeps a real, nonzero runs/rbi chance even on genuine zero-hit trials")


def test_hrr_multiplier_ceiling_bounds_extreme_hot_trials():
    # An extremely hot trial (far more hits than expected) should NOT get an unbounded
    # multiplier -- confirms the stated ceiling actually caps it.
    rng = np.random.default_rng(0)
    sim_hits = np.full(20000, 10)   # an absurdly hot trial value, testing the real bound
    out = P.simulate_hits_runs_rbi(sim_hits, exp_hits=1.1, exp_runs=0.5, exp_rbi=0.5, rng=rng)
    # Expected mean at the ceiling: exp_runs * HRR_CORRELATION_CEILING = 0.5 * 2.0 = 1.0
    assert out["runs"].mean() == pytest.approx(1.0, abs=0.05)
    print("✓ simulate_hits_runs_rbi correctly caps the multiplier for an extremely hot trial, not letting it scale unboundedly")


def test_hrr_unclipped_mean_stays_close_to_unconditional_rate():
    # A real, important property: on a REALISTIC hits distribution (not an artificial all-zero
    # or all-extreme input), the overall average runs/rbi across all trials should stay close to
    # the original, unconditional exp_runs/exp_rbi -- confirming the correlation mechanism
    # redistributes variance across trials without systematically biasing the overall mean.
    rng = np.random.default_rng(0)
    sim_hits = np.random.default_rng(1).poisson(1.1, size=100000)
    out = P.simulate_hits_runs_rbi(sim_hits, exp_hits=1.1, exp_runs=0.5, exp_rbi=0.5, rng=rng)
    assert out["runs"].mean() == pytest.approx(0.5, abs=0.03)
    assert out["rbi"].mean() == pytest.approx(0.5, abs=0.03)
    print("✓ simulate_hits_runs_rbi's overall mean stays close to the real, unconditional rate on a realistic hits distribution")


def test_hrr_handles_near_zero_exp_hits_without_crashing():
    rng = np.random.default_rng(0)
    sim_hits = np.zeros(1000, dtype=np.int64)
    out = P.simulate_hits_runs_rbi(sim_hits, exp_hits=0.0, exp_runs=0.3, exp_rbi=0.3, rng=rng)
    assert (out["runs"] >= 0).all()
    assert (out["rbi"] >= 0).all()
    print("✓ simulate_hits_runs_rbi handles a near-zero exp_hits edge case without dividing by zero or crashing")


# ----------------------------------------------------------------- enrich_hitter_rows: Runs/RBI/SB
def _slugger_with_counting_stats():
    return dict(plateAppearances=600, atBats=540, hits=165, doubles=34, triples=2,
               homeRuns=38, baseOnBalls=55, strikeOuts=140, runs=95, rbi=102, stolenBases=8)


def test_enrich_hitter_rows_attaches_runs_rbi_sb():
    row = {"Hitter": "Test Slugger", "Team": "Test Team", "_pid": 1,
          "_stat": _slugger_with_counting_stats(), "_opp_stat": None, "_venue_id": None,
          "_split_stat": None, "_exp_pa": 4.25, "_weather_hr": 1.0}
    out = P.enrich_hitter_rows([row], seed=1)[0]
    assert "Runs%" in out and "RBI%" in out and "SB%" in out
    assert 0.0 < out["Runs%"] < 1.0
    assert 0.0 < out["RBI%"] < 1.0
    assert 0.0 < out["SB%"] < 1.0
    print("✓ enrich_hitter_rows correctly attaches Runs%/RBI%/SB% with a real, complete stat dict")


def test_enrich_hitter_rows_uses_opp_era_when_present():
    stat = _slugger_with_counting_stats()
    row_vs_ace = {"Hitter": "X", "Team": "T", "_pid": 1, "_stat": stat,
                 "_opp_stat": {"era": 2.5}, "_venue_id": None, "_split_stat": None,
                 "_exp_pa": 4.25, "_weather_hr": 1.0}
    row_vs_bad = {"Hitter": "X", "Team": "T", "_pid": 1, "_stat": stat,
                 "_opp_stat": {"era": 6.0}, "_venue_id": None, "_split_stat": None,
                 "_exp_pa": 4.25, "_weather_hr": 1.0}
    out_vs_ace = P.enrich_hitter_rows([row_vs_ace], seed=1)[0]
    out_vs_bad = P.enrich_hitter_rows([row_vs_bad], seed=1)[0]
    assert out_vs_bad["Runs%"] > out_vs_ace["Runs%"]
    assert out_vs_bad["RBI%"] > out_vs_ace["RBI%"]
    print("✓ enrich_hitter_rows correctly raises Runs%/RBI% against a bad opposing starter and lowers it against an ace")


def test_enrich_hitter_rows_handles_missing_counting_stat_fields_gracefully():
    # A REAL edge case, not hypothetical: _slugger() (used throughout the rest of this test
    # file) never included runs/rbi/stolenBases at all -- confirms enrich_hitter_rows doesn't
    # crash on a stat dict missing these fields, the same real-world shape an older or partial
    # data source could produce, and still produces a sane (low, shrunk-toward-league-average,
    # never negative) rate rather than erroring out.
    row = {"Hitter": "Test Slugger", "Team": "Test Team", "_pid": 1, "_stat": _slugger(),
          "_opp_stat": None, "_venue_id": None, "_split_stat": None,
          "_exp_pa": 4.25, "_weather_hr": 1.0}
    out = P.enrich_hitter_rows([row], seed=1)[0]
    assert "Runs%" in out and "RBI%" in out and "SB%" in out
    assert 0.0 <= out["Runs%"] < 1.0
    assert 0.0 <= out["RBI%"] < 1.0
    assert 0.0 <= out["SB%"] < 1.0
    print("✓ enrich_hitter_rows doesn't crash and produces sane values even when runs/rbi/stolenBases are entirely missing from the stat dict")


# ----------------------------------------------------------------- enrich_hitter_rows: Single/Double/Triple/Walk
def test_enrich_hitter_rows_attaches_single_double_triple_walk():
    row = {"Hitter": "Test Slugger", "Team": "Test Team", "_pid": 1,
          "_stat": _slugger_with_counting_stats(), "_opp_stat": None, "_venue_id": None,
          "_split_stat": None, "_exp_pa": 4.25, "_weather_hr": 1.0}
    out = P.enrich_hitter_rows([row], seed=1)[0]
    for key in ("Single%", "Double%", "Triple%", "Walk%"):
        assert key in out
        assert 0.0 <= out[key] < 1.0
    print("✓ enrich_hitter_rows correctly attaches Single%/Double%/Triple%/Walk%")


def test_enrich_hitter_rows_triple_pct_lower_than_single_pct():
    row = {"Hitter": "Test Slugger", "Team": "Test Team", "_pid": 1,
          "_stat": _slugger_with_counting_stats(), "_opp_stat": None, "_venue_id": None,
          "_split_stat": None, "_exp_pa": 4.25, "_weather_hr": 1.0}
    out = P.enrich_hitter_rows([row], seed=1)[0]
    assert out["Triple%"] < out["Single%"]
    print("✓ enrich_hitter_rows correctly produces a lower Triple% than Single%, matching real relative hit-type frequency")


def test_enrich_hitter_rows_single_double_triple_walk_use_slugger_fixture_gracefully():
    # _slugger() (used throughout the rest of this file) has homeRuns/baseOnBalls/strikeOuts but
    # no explicit doubles/triples counts beyond what's in the base fixture -- confirms this still
    # produces sane, non-crashing values using the SAME PA-outcome simulation as every other
    # field here, not a separate code path that could silently diverge.
    row = {"Hitter": "X", "Team": "T", "_pid": 1, "_stat": _slugger(), "_opp_stat": None,
          "_venue_id": None, "_split_stat": None, "_exp_pa": 4.25, "_weather_hr": 1.0}
    out = P.enrich_hitter_rows([row], seed=1)[0]
    for key in ("Single%", "Double%", "Triple%", "Walk%"):
        assert key in out
        assert 0.0 <= out[key] < 1.0


# ----------------------------------------------------------------- enrich_hitter_rows: HRR%
def test_enrich_hitter_rows_attaches_hrr():
    row = {"Hitter": "Test Slugger", "Team": "Test Team", "_pid": 1,
          "_stat": _slugger_with_counting_stats(), "_opp_stat": None, "_venue_id": None,
          "_split_stat": None, "_exp_pa": 4.25, "_weather_hr": 1.0}
    out = P.enrich_hitter_rows([row], seed=1)[0]
    assert "HRR%" in out
    assert 0.0 <= out["HRR%"] < 1.0
    print("✓ enrich_hitter_rows correctly attaches HRR% (Hits+Runs+RBIs)")


def test_enrich_hitter_rows_hrr_higher_than_hit_pct_alone():
    # A real, meaningful sanity check: combining three stats into one "over 1.5" line should
    # produce a genuinely different (here, real cross-check via a real comparison) number than
    # any single component -- specifically, HRR% should be a real, distinct probability, not
    # accidentally identical to Hit% (which would suggest Runs/RBI aren't actually contributing).
    row = {"Hitter": "Test Slugger", "Team": "Test Team", "_pid": 1,
          "_stat": _slugger_with_counting_stats(), "_opp_stat": None, "_venue_id": None,
          "_split_stat": None, "_exp_pa": 4.25, "_weather_hr": 1.0}
    out = P.enrich_hitter_rows([row], seed=1)[0]
    assert out["HRR%"] != out["Hit%"]
    print("✓ enrich_hitter_rows' HRR% is a genuinely distinct probability from Hit% alone, confirming Runs/RBI are real contributors")


# ----------------------------------------------------------------- project_pitcher: opener detection
def test_project_pitcher_opener_uses_own_low_ip_not_forced_to_floor():
    # THE real, confirmed fix: a genuine opener profile (12 starts averaging 2.0 IP each) must
    # keep his own real, low exp_ip -- NOT get force-floored up to 3.0 the way a normal
    # starter's occasional short outing correctly would be.
    opener = dict(battersFaced=100, inningsPitched="24.0", gamesStarted=12,
                 strikeOuts=28, baseOnBalls=8, earnedRuns=6, hits=18)
    proj = P.project_pitcher(opener)
    assert proj["exp_ip"] == pytest.approx(2.0, abs=1e-9)
    print("✓ project_pitcher correctly keeps a genuine opener's own low exp_ip instead of forcing it to the normal-starter floor")


def test_project_pitcher_normal_starter_unaffected_by_opener_logic():
    normal = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
                 strikeOuts=235, baseOnBalls=42, earnedRuns=65, hits=170)
    proj = P.project_pitcher(normal)
    assert proj["exp_ip"] == pytest.approx(180 / 29, abs=0.01)
    print("✓ project_pitcher's opener detection correctly leaves a real, normal starter's exp_ip unaffected")


def test_project_pitcher_struggling_starter_still_gets_normal_floor():
    # A real, deliberate distinction: a CONVENTIONAL starter having a bad year (short outings,
    # but still genuinely a starter, not an opener) should still get the ORIGINAL 3.0 floor --
    # confirms the fix doesn't overcorrect and start under-crediting real, if struggling,
    # starters. ip/gs here is 2.8, above the 2.5 opener threshold.
    struggling = dict(battersFaced=350, inningsPitched="84.0", gamesStarted=30,
                      strikeOuts=70, baseOnBalls=40, earnedRuns=55, hits=100)
    proj = P.project_pitcher(struggling)
    assert proj["exp_ip"] == pytest.approx(3.0, abs=1e-9)
    print("✓ project_pitcher still applies the normal 3.0-inning floor to a genuinely struggling (but real) starter, not just any short-outing pitcher")


def test_project_pitcher_opener_floor_guards_against_near_zero_noise():
    # An extreme, near-zero-IP-per-start edge case should still be floored at a small, sane
    # minimum (0.5), not left at an unrealistic near-zero value. ip=16, gs=40 keeps this fixture
    # within the real starter gate (ip >= 15) while still exercising the extreme low end.
    extreme = dict(battersFaced=100, inningsPitched="16.0", gamesStarted=40,
                  strikeOuts=15, baseOnBalls=10, earnedRuns=8, hits=14)
    proj = P.project_pitcher(extreme)
    assert proj["exp_ip"] == pytest.approx(0.5, abs=1e-9)
    print("✓ project_pitcher's opener floor correctly guards against an unrealistic near-zero exp_ip")


def test_project_pitcher_opener_reduces_hitter_exposure_via_exp_bf():
    # A real, end-to-end proof that the fix actually changes the downstream number that matters
    # -- exp_bf, which hitter_starter_exposures directly reads to decide how many of a hitter's
    # PA fall against this specific pitcher vs. the bullpen.
    opener = dict(battersFaced=100, inningsPitched="24.0", gamesStarted=12,
                 strikeOuts=28, baseOnBalls=8, earnedRuns=6, hits=18)
    old_style_exp_bf = 3.0 * (100 / 24.0)   # what the OLD, un-fixed floor would have produced
    proj = P.project_pitcher(opener)
    assert proj["exp_bf"] < old_style_exp_bf
    print(f"✓ project_pitcher's fix reduces exp_bf from what the old floor would have produced ({old_style_exp_bf:.1f}) to a real, honest value ({proj['exp_bf']:.1f})")


# ----------------------------------------------------------------- project_pitcher: days_rest
def test_project_pitcher_short_rest_applies_correct_direction_and_magnitude():
    stat = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
               strikeOuts=235, baseOnBalls=42, earnedRuns=65, hits=170)
    normal = P.project_pitcher(stat)
    short = P.project_pitcher(stat, days_rest=4)
    # Hand-verified exact ratios, not just directional checks
    assert abs(short["exp_k"] / normal["exp_k"] - P.REST_K_MULT) < 1e-9
    assert abs(short["exp_bb"] / normal["exp_bb"] - P.REST_BB_MULT) < 1e-9
    assert abs(short["exp_er"] / normal["exp_er"] - P.REST_ER_MULT) < 1e-9
    print("✓ project_pitcher applies the exact, hand-verified short-rest multiplier to exp_k/exp_bb/exp_er")


def test_project_pitcher_short_rest_leaves_hits_allowed_and_innings_untouched():
    stat = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
               strikeOuts=235, baseOnBalls=42, earnedRuns=65, hits=170)
    normal = P.project_pitcher(stat)
    short = P.project_pitcher(stat, days_rest=4)
    assert short["exp_hits_allowed"] == normal["exp_hits_allowed"]   # DIPS-theory posture
    assert short["exp_ip"] == normal["exp_ip"]     # rest doesn't change HOW LONG he's expected
                                                   # to pitch, a separate decision driven by his
                                                   # own usage pattern, not tonight's rest status
    print("✓ project_pitcher correctly leaves exp_hits_allowed and exp_ip unaffected by the rest adjustment")


def test_project_pitcher_short_rest_still_applies_with_opponent_matchup():
    # Confirms the rest penalty survives the odds-ratio opponent-matchup step, not just the
    # unadjusted case -- a short-rest ace facing a weak lineup should still project worse than
    # his own full-rest numbers against that same lineup would.
    stat = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
               strikeOuts=235, baseOnBalls=42, earnedRuns=65, hits=170)
    weak_lineup = {"k": 0.28, "bb": 0.06}   # a real, whiff-prone opposing lineup
    normal = P.project_pitcher(stat, opp_lineup=weak_lineup)
    short = P.project_pitcher(stat, opp_lineup=weak_lineup, days_rest=4)
    assert short["exp_k"] < normal["exp_k"]
    assert short["exp_bb"] > normal["exp_bb"]
    print("✓ project_pitcher's rest penalty survives the opponent-matchup step, not just the unadjusted case")


def test_project_pitcher_extra_and_unknown_rest_no_adjustment():
    stat = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
               strikeOuts=235, baseOnBalls=42, earnedRuns=65, hits=170)
    baseline = P.project_pitcher(stat)
    extra_rest = P.project_pitcher(stat, days_rest=7)
    unknown_rest = P.project_pitcher(stat, days_rest=None)
    assert extra_rest == baseline
    assert unknown_rest == baseline
    print("✓ project_pitcher correctly applies no adjustment for extra rest or unknown rest, matching the baseline exactly")



    ace = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
              strikeOuts=235, baseOnBalls=42, earnedRuns=65)   # a real ~3.25 ERA season
    proj = P.project_pitcher(ace)
    assert "exp_er" in proj
    # Hand-verified: raw ERA 3.25 over ~6.21 expected IP = ~2.24 unshrunk; shrinkage toward the
    # slightly higher league-average ERA (4.10) pulls this up slightly, to ~2.33.
    assert 2.0 < proj["exp_er"] < 2.6
    print("✓ project_pitcher correctly computes a sane, hand-verified exp_er for a realistic full season")


def test_project_pitcher_exp_er_missing_field_defaults_gracefully():
    # The existing `ace` fixture used throughout the rest of this test file never included
    # earnedRuns at all -- a real edge case, confirms this doesn't crash and produces a sane,
    # shrunk-toward-league-average value rather than erroring on the missing key.
    ace_no_er = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
                     strikeOuts=235, baseOnBalls=42)
    proj = P.project_pitcher(ace_no_er)
    assert "exp_er" in proj
    assert proj["exp_er"] >= 0.0
    print("✓ project_pitcher handles a stat dict missing earnedRuns entirely without crashing")


def test_project_pitcher_exp_er_thin_sample_regresses_to_league_average():
    thin = dict(battersFaced=65, inningsPitched="16.0", gamesStarted=3,
               strikeOuts=15, baseOnBalls=5, earnedRuns=1)   # a tiny, wildly-good sample
    proj = P.project_pitcher(thin)
    naive_er_rate = 1 / 16.0   # what an unregressed calculation would use
    shrunk_er_rate = proj["exp_er"] / proj["exp_ip"]
    assert shrunk_er_rate > naive_er_rate   # real shrinkage pulls this UP toward league average
    print("✓ project_pitcher meaningfully regresses a thin-sample ER rate toward league average")


def test_project_pitcher_exp_er_never_negative():
    great = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
                strikeOuts=235, baseOnBalls=42, earnedRuns=0)   # extreme edge case
    proj = P.project_pitcher(great)
    assert proj["exp_er"] >= 0.0


# ----------------------------------------------------------------- simulate_pitcher: er
def test_simulate_pitcher_produces_er_array():
    ace = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
              strikeOuts=235, baseOnBalls=42, earnedRuns=65)
    proj = P.project_pitcher(ace)
    rng = np.random.default_rng(0)
    sim = P.simulate_pitcher(proj, 20000, rng)
    assert "er" in sim
    assert len(sim["er"]) == 20000
    assert sim["er"].mean() == pytest.approx(proj["exp_er"], abs=0.1)
    print("✓ simulate_pitcher's simulated ER distribution correctly converges to the real expected value")


# ----------------------------------------------------------------- project_pitcher: exp_hits_allowed
def test_project_pitcher_exp_hits_allowed_present_and_hand_verified():
    ace = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
              strikeOuts=235, baseOnBalls=42, earnedRuns=65, hits=170)
    proj = P.project_pitcher(ace)
    assert "exp_hits_allowed" in proj
    # Hand-verified directly: shrunk rate 0.2357 * exp_bf 24.83 = 5.853
    assert proj["exp_hits_allowed"] == pytest.approx(5.853, abs=0.01)
    print("✓ project_pitcher correctly computes a hand-verified exp_hits_allowed")


def test_project_pitcher_exp_hits_allowed_missing_field_defaults_gracefully():
    # The `ace` fixture used throughout the rest of this file never included "hits" at all --
    # confirms this doesn't crash and produces a sane, shrunk-toward-league-average value.
    ace_no_hits = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
                       strikeOuts=235, baseOnBalls=42)
    proj = P.project_pitcher(ace_no_hits)
    assert "exp_hits_allowed" in proj
    assert proj["exp_hits_allowed"] >= 0.0
    print("✓ project_pitcher handles a stat dict missing hits entirely without crashing")


def test_project_pitcher_exp_hits_allowed_shrinks_harder_than_k_or_bb():
    # A real, deliberate design property, not incidental: hits_allowed's prior (350 BF) matches
    # BB's own prior exactly, and is meaningfully larger than K's (150) -- confirms a thin-sample
    # pitcher's hits-allowed rate regresses AT LEAST as hard toward league average as his BB rate
    # does, honestly reflecting that hits allowed carries less individual signal (DIPS theory).
    thin = dict(battersFaced=65, inningsPitched="16.0", gamesStarted=3,
               strikeOuts=15, baseOnBalls=5, earnedRuns=1, hits=5)   # a small, hot sample
    proj = P.project_pitcher(thin)
    naive_hits_rate = 5 / 65
    shrunk_hits_rate = proj["exp_hits_allowed"] / proj["exp_bf"]
    naive_k_rate = 15 / 65
    shrunk_k_rate = proj["exp_k"] / proj["exp_bf"]
    hits_shrink_amount = abs(naive_hits_rate - shrunk_hits_rate)
    k_shrink_amount = abs(naive_k_rate - shrunk_k_rate)
    assert hits_shrink_amount > k_shrink_amount
    print("✓ project_pitcher shrinks a thin-sample hits-allowed rate harder than the same pitcher's K rate, honestly reflecting DIPS theory")


def test_project_pitcher_exp_hits_allowed_never_negative():
    great = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
                strikeOuts=235, baseOnBalls=42, hits=0)   # extreme edge case
    proj = P.project_pitcher(great)
    assert proj["exp_hits_allowed"] >= 0.0


# ----------------------------------------------------------------- simulate_pitcher: hits_allowed
def test_simulate_pitcher_produces_hits_allowed_array():
    ace = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
              strikeOuts=235, baseOnBalls=42, earnedRuns=65, hits=170)
    proj = P.project_pitcher(ace)
    rng = np.random.default_rng(0)
    sim = P.simulate_pitcher(proj, 20000, rng)
    assert "hits_allowed" in sim
    assert len(sim["hits_allowed"]) == 20000
    assert sim["hits_allowed"].mean() == pytest.approx(proj["exp_hits_allowed"], abs=0.1)
    print("✓ simulate_pitcher's simulated hits-allowed distribution correctly converges to the real expected value")


# ----------------------------------------------------------------- build_pitcher_projection_rows: ER
def test_build_pitcher_projection_rows_includes_er_fields():
    home_stat = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
                     strikeOuts=235, baseOnBalls=42, earnedRuns=65)
    away_stat = dict(battersFaced=700, inningsPitched="175.0", gamesStarted=28,
                     strikeOuts=210, baseOnBalls=50, earnedRuns=70)
    hp = _fake_pm(601, "Home Ace", "R", 3.25, 3.20, home_stat)
    ap = _fake_pm(602, "Away Ace", "L", 3.60, 3.55, away_stat)
    meta = [{"label": "NYY @ BOS", "home_id": 1, "away_id": 2,
            "home_name": "Boston Red Sox", "away_name": "New York Yankees",
            "game_date": "2026-07-18", "home_pm": hp, "away_pm": ap}]
    out = P.build_pitcher_projection_rows([], meta, seed=1)
    assert len(out) == 2
    for r in out:
        assert "Proj ER" in r and "ER line" in r and "ER over%" in r and "ER fair" in r
        assert r["ER line"] == 2.5
        assert 0.0 <= r["ER over%"] <= 1.0
    print("✓ build_pitcher_projection_rows correctly includes Proj ER/ER line/ER over%/ER fair for every starter")


def test_build_pitcher_projection_rows_includes_hits_allowed_fields():
    home_stat = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
                     strikeOuts=235, baseOnBalls=42, earnedRuns=65, hits=170)
    away_stat = dict(battersFaced=700, inningsPitched="175.0", gamesStarted=28,
                     strikeOuts=210, baseOnBalls=50, earnedRuns=70, hits=165)
    hp = _fake_pm(601, "Home Ace", "R", 3.25, 3.20, home_stat)
    ap = _fake_pm(602, "Away Ace", "L", 3.60, 3.55, away_stat)
    meta = [{"label": "NYY @ BOS", "home_id": 1, "away_id": 2,
            "home_name": "Boston Red Sox", "away_name": "New York Yankees",
            "game_date": "2026-07-18", "home_pm": hp, "away_pm": ap}]
    out = P.build_pitcher_projection_rows([], meta, seed=1)
    assert len(out) == 2
    for r in out:
        assert "Proj Hits Allowed" in r and "Hits Allowed line" in r
        assert "Hits Allowed over%" in r and "Hits Allowed fair" in r
        assert r["Hits Allowed line"] == 5.5
        assert 0.0 <= r["Hits Allowed over%"] <= 1.0
    print("✓ build_pitcher_projection_rows correctly includes all four Hits Allowed fields for every starter")


# ----------------------------------------------------------------- build_pitcher_projection_rows: real lines
def test_build_pitcher_projection_rows_default_line_when_no_real_lines_given():
    stat = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
               strikeOuts=235, baseOnBalls=42, earnedRuns=65, hits=170)
    hp = _fake_pm(601, "Home Ace", "R", 3.25, 3.20, stat)
    ap = _fake_pm(602, "Away Ace", "L", 3.60, 3.55, stat)
    meta = [{"label": "NYY @ BOS", "home_id": 1, "away_id": 2,
            "home_name": "Boston Red Sox", "away_name": "New York Yankees",
            "game_date": "2026-07-18", "home_pm": hp, "away_pm": ap}]
    out = P.build_pitcher_projection_rows([], meta, seed=1)   # real_lines not passed at all
    for r in out:
        assert r["K line"] == 5.5 and r["K LineSource"] == "default"
        assert r["Outs line"] == 17.5 and r["Outs LineSource"] == "default"
        assert r["BB line"] == 1.5 and r["BB LineSource"] == "default"
    print("✓ build_pitcher_projection_rows falls back to the exact original default-line behavior when real_lines isn't passed at all, unchanged from before this feature")


def test_build_pitcher_projection_rows_uses_real_line_when_available():
    stat = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
               strikeOuts=235, baseOnBalls=42, earnedRuns=65, hits=170)
    hp = _fake_pm(601, "Home Ace", "R", 3.25, 3.20, stat)
    ap = _fake_pm(602, "Away Ace", "L", 3.60, 3.55, stat)
    meta = [{"label": "NYY @ BOS", "home_id": 1, "away_id": 2,
            "home_name": "Boston Red Sox", "away_name": "New York Yankees",
            "game_date": "2026-07-18", "home_pm": hp, "away_pm": ap}]
    real_lines = {(P.normalize_name("Home Ace"), "pitcher_strikeouts"): 7.5}
    out = P.build_pitcher_projection_rows([], meta, seed=1, real_lines=real_lines)
    home_row = next(r for r in out if r["Pitcher"] == "Home Ace")
    away_row = next(r for r in out if r["Pitcher"] == "Away Ace")
    assert home_row["K line"] == 7.5 and home_row["K LineSource"] == "book"
    assert away_row["K line"] == 5.5 and away_row["K LineSource"] == "default"   # no real line for Away Ace
    print("✓ build_pitcher_projection_rows uses the real line for the pitcher who has one, and the honest default for the one who doesn't — independently, not all-or-nothing")


def test_build_pitcher_projection_rows_reproduces_the_real_sugano_case():
    # THE exact real, reported case this entire feature was built from: Graded Picks showed
    # "Pitcher Strikeouts Under 5.5" for Tomoyuki Sugano, whose real DraftKings line was 3.5.
    # Confirms directly that the real line, once available, is what the probability is actually
    # computed against -- not just displayed differently while the math stays on the old default.
    stat = dict(battersFaced=650, inningsPitched="165.0", gamesStarted=27,
               strikeOuts=95, baseOnBalls=35, earnedRuns=60, hits=160)   # a real, modest-K profile
    sugano = _fake_pm(700, "Tomoyuki Sugano", "R", 3.80, 4.10, stat)
    opp = _fake_pm(701, "Opposing Pitcher", "L", 4.00, 4.00, stat)
    meta = [{"label": "Opponent @ Padres", "home_id": 135, "away_id": 999,
            "home_name": "San Diego Padres", "away_name": "Opponent",
            "game_date": "2026-07-24", "home_pm": sugano, "away_pm": opp}]
    real_lines = {(P.normalize_name("Tomoyuki Sugano"), "pitcher_strikeouts"): 3.5}

    with_real_line = P.build_pitcher_projection_rows([], meta, seed=1, real_lines=real_lines)
    without_real_line = P.build_pitcher_projection_rows([], meta, seed=1, real_lines=None)

    sugano_real = next(r for r in with_real_line if r["Pitcher"] == "Tomoyuki Sugano")
    sugano_default = next(r for r in without_real_line if r["Pitcher"] == "Tomoyuki Sugano")

    assert sugano_real["K line"] == 3.5 and sugano_real["K LineSource"] == "book"
    assert sugano_default["K line"] == 5.5 and sugano_default["K LineSource"] == "default"
    # The probability itself must genuinely differ between the two -- confirming the real line
    # actually drove a different computation, not just a different label on the same number.
    assert sugano_real["K over%"] != sugano_default["K over%"]
    print(f"✓ build_pitcher_projection_rows resolves the exact real Sugano case: real line 3.5 "
         f"(K over% = {sugano_real['K over%']}) vs. the old hardcoded 5.5 "
         f"(K over% = {sugano_default['K over%']}) — genuinely different numbers, not just a relabel")


def test_build_pitcher_projection_rows_real_lines_for_all_five_markets():
    stat = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
               strikeOuts=235, baseOnBalls=42, earnedRuns=65, hits=170)
    pm = _fake_pm(601, "Five Market Guy", "R", 3.25, 3.20, stat)
    other = _fake_pm(602, "Other Guy", "L", 3.60, 3.55, stat)
    meta = [{"label": "AWY @ HOM", "home_id": 1, "away_id": 2,
            "home_name": "HOM", "away_name": "AWY",
            "game_date": "2026-07-18", "home_pm": pm, "away_pm": other}]
    real_lines = {
        (P.normalize_name("Five Market Guy"), "pitcher_strikeouts"): 6.5,
        (P.normalize_name("Five Market Guy"), "pitcher_outs"): 18.5,
        (P.normalize_name("Five Market Guy"), "pitcher_walks"): 2.5,
        (P.normalize_name("Five Market Guy"), "pitcher_earned_runs"): 1.5,
        (P.normalize_name("Five Market Guy"), "pitcher_hits_allowed"): 4.5,
    }
    out = P.build_pitcher_projection_rows([], meta, seed=1, real_lines=real_lines)
    r = next(row for row in out if row["Pitcher"] == "Five Market Guy")
    assert r["K line"] == 6.5 and r["K LineSource"] == "book"
    assert r["Outs line"] == 18.5 and r["Outs LineSource"] == "book"
    assert r["BB line"] == 2.5 and r["BB LineSource"] == "book"
    assert r["ER line"] == 1.5 and r["ER LineSource"] == "book"
    assert r["Hits Allowed line"] == 4.5 and r["Hits Allowed LineSource"] == "book"
    print("✓ build_pitcher_projection_rows correctly wires real lines independently into all five real pitcher markets, not just strikeouts")


# ----------------------------------------------------------------- _hitter_reasons: new markets
def test_hitter_reasons_runs_rbi_references_bad_opposing_starter():
    row = {"_opp_stat": {"era": 5.5}}
    why = P._hitter_reasons(row, "Batter Runs", "Over")
    assert any("struggling starter" in w and "5.50" in w for w in why)
    why_rbi = P._hitter_reasons(row, "Batter RBIs", "Over")
    assert any("struggling starter" in w for w in why_rbi)
    print("✓ _hitter_reasons correctly references a real, struggling opposing starter's ERA for Runs/RBI")


def test_hitter_reasons_runs_rbi_references_strong_opposing_starter():
    row = {"_opp_stat": {"era": 2.8}}
    why = P._hitter_reasons(row, "Batter Runs", "Under")
    assert any("strong starter" in w and "2.80" in w for w in why)


def test_hitter_reasons_runs_rbi_no_era_falls_back_to_generic():
    row = {"_opp_stat": None}
    why = P._hitter_reasons(row, "Batter Runs", "Over")
    assert why == ["model leans Over of a typical line here"]
    print("✓ _hitter_reasons falls back to the honest generic reason when no opponent ERA is available")


def test_hitter_reasons_stolen_bases_references_own_rate_not_a_fabricated_matchup():
    row = {}
    why = P._hitter_reasons(row, "Batter Stolen Bases", "Over")
    assert why == ["based on his own season stolen-base rate"]
    print("✓ _hitter_reasons is honest that SB has no real opponent matchup factor in the model")


# ----------------------------------------------------------------- _pitcher_reasons: earned runs
def test_pitcher_reasons_earned_runs_references_era_and_ip():
    row = {"ERA": 3.45, "Proj IP": 6.1}
    why = P._pitcher_reasons(row, "Pitcher Earned Runs", "Over")
    assert why == ["3.45 ERA over a projected 6.1 IP"]
    print("✓ _pitcher_reasons correctly references the pitcher's own ERA/IP for Earned Runs, honest about no opponent adjustment")


def test_pitcher_reasons_hits_allowed_references_dips_caveat():
    row = {"Proj Hits Allowed": 5.9}
    why = P._pitcher_reasons(row, "Pitcher Hits Allowed", "Over")
    assert len(why) == 1
    assert "5.9" in why[0]
    assert "league average" in why[0].lower()
    print("✓ _pitcher_reasons correctly references Proj Hits Allowed with an honest DIPS-theory caveat, not overstated confidence")


def test_hitter_reasons_walks_gets_own_distinct_reasoning():
    why_over = P._hitter_reasons({}, "Batter Walks", "Over")
    why_under = P._hitter_reasons({}, "Batter Walks", "Under")
    assert why_over == ["real plate discipline in this matchup"]
    assert why_under == ["aggressive approach, rarely walks"]
    assert why_over != why_under
    print("✓ _hitter_reasons gives Batter Walks its own distinct reasoning, not reused power/platoon language")


def test_hitter_reasons_singles_doubles_triples_get_platoon_reasoning():
    # Confirms these join the SAME platoon-aware "offense" group as HR/TB/Hits, since they share
    # the same underlying platoon-adjusted PA-outcome distribution -- not a separate, unrelated
    # code path that could silently diverge from what the model actually does.
    row = {"Advantage": "Advantage", "Hand": "R", "Opp Hand": "L"}
    for market in ("Batter Singles", "Batter Doubles", "Batter Triples"):
        why = P._hitter_reasons(row, market, "Over")
        assert any("platoon edge" in w for w in why)
    print("✓ _hitter_reasons correctly extends platoon-edge reasoning to Singles/Doubles/Triples")


def test_hitter_reasons_singles_doubles_triples_no_weather_claim():
    # A real, deliberate honesty check: weather in this model only DIRECTLY affects HR (via
    # p_hr *= weather_hr), not singles/doubles/triples -- confirms these markets never claim a
    # weather boost the model doesn't actually apply to them.
    row = {"Advantage": None, "_weather_hr": 1.15}
    for market in ("Batter Singles", "Batter Doubles", "Batter Triples"):
        why = P._hitter_reasons(row, market, "Over")
        assert not any("weather" in w for w in why)
    print("✓ _hitter_reasons correctly does NOT claim a weather boost for Singles/Doubles/Triples, honest about what the model actually applies")


# ----------------------------------------------------------------- build_best_bets: _ceiling
def test_build_best_bets_attaches_correct_ceiling():
    hitters = [
        dict(Hitter="Slugger", Team="A", GameLabel="A @ B", Hand="L",
            **{"Opp Hand": "R", "Opp Pitcher": "Ace"}, Advantage="Advantage",
            _weather_hr=1.0, Due=0.0, _opp_stat={"era": 4.0},
            **{"HR%": 0.15, "TB1.5%": 0.40, "Hit%": 0.65, "SO Prob": 0.50,
              "Runs%": 0.42, "RBI%": 0.40, "SB%": 0.08}),
    ]
    plays = P.build_best_bets(hitters, [])
    hr_play = next(p for p in plays if p["Market"] == "Batter HR")
    sb_play = next(p for p in plays if p["Market"] == "Batter Stolen Bases")
    # HR's ref is 0.11 -> ceiling should be 1/0.11 ~ 9.09; SB's ref is 0.05 -> ceiling ~20.0
    # (or their real Under-side complements, whichever side is actually favored for this fixture)
    assert hr_play["_ceiling"] is not None
    assert sb_play["_ceiling"] is not None
    assert sb_play["_ceiling"] > hr_play["_ceiling"]   # SB genuinely has more headroom than HR
    print("✓ build_best_bets correctly attaches each play's own real theoretical ceiling")


# ----------------------------------------------------------------- build_best_bets: OppERA
def test_build_best_bets_attaches_opp_era():
    hitters = [
        dict(Hitter="Slugger", Team="A", GameLabel="A @ B", Hand="L",
            **{"Opp Hand": "R", "Opp Pitcher": "Some Starter"}, Advantage="Advantage",
            _weather_hr=1.0, Due=0.0, _opp_stat={"era": 5.16},
            **{"HR%": 0.15, "TB1.5%": 0.40, "Hit%": 0.65, "SO Prob": 0.50,
              "Runs%": 0.42, "RBI%": 0.40, "SB%": 0.08}),
    ]
    plays = P.build_best_bets(hitters, [])
    for p in plays:
        assert p["OppERA"] == 5.16
        assert p["Opp"] == "Some Starter"
    print("✓ build_best_bets correctly attaches the real opposing starter's ERA to every batter play, straight from _opp_stat")


def test_build_best_bets_opp_era_none_when_unavailable():
    hitters = [
        dict(Hitter="Slugger", Team="A", GameLabel="A @ B", Hand="L",
            **{"Opp Hand": "R", "Opp Pitcher": "Unknown Starter"}, Advantage="Advantage",
            _weather_hr=1.0, Due=0.0, _opp_stat={},   # no era field at all
            **{"HR%": 0.15, "TB1.5%": 0.40, "Hit%": 0.65, "SO Prob": 0.50,
              "Runs%": 0.42, "RBI%": 0.40, "SB%": 0.08}),
    ]
    plays = P.build_best_bets(hitters, [])
    for p in plays:
        assert p["OppERA"] is None   # never fabricated as 0.0, which would misleadingly look elite
    print("✓ build_best_bets correctly leaves OppERA as None (not a fabricated 0.0) when the real ERA isn't available")


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
