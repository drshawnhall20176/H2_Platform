"""
test_grading.py — offline tests for grading.py, the shared sport-agnostic letter-grade/tier
logic used by Graded Picks and Retrospective across every sport on this platform.

    python test_grading.py     # or: pytest test_grading.py
"""

import grading
import pytest


# ----------------------------------------------------------------- conviction_to_grade
def test_conviction_to_grade_thresholds():
    assert grading.conviction_to_grade(3.5) == {"letter": "A", "tier": "Top Lean", "conviction": 3.5}
    assert grading.conviction_to_grade(3.0) == {"letter": "A", "tier": "Top Lean", "conviction": 3.0}
    assert grading.conviction_to_grade(2.99) == {"letter": "B", "tier": "Strong Lean", "conviction": 2.99}
    assert grading.conviction_to_grade(2.0) == {"letter": "B", "tier": "Strong Lean", "conviction": 2.0}
    assert grading.conviction_to_grade(1.99) == {"letter": "C", "tier": "Lean", "conviction": 1.99}
    assert grading.conviction_to_grade(1.5) == {"letter": "C", "tier": "Lean", "conviction": 1.5}
    assert grading.conviction_to_grade(1.49) == {"letter": "D", "tier": "Watch", "conviction": 1.49}
    assert grading.conviction_to_grade(1.2) == {"letter": "D", "tier": "Watch", "conviction": 1.2}
    print("✓ conviction_to_grade correctly applies threshold boundaries")


def test_conviction_to_grade_none_below_floor():
    assert grading.conviction_to_grade(1.19) is None
    assert grading.conviction_to_grade(0.5) is None
    assert grading.conviction_to_grade(0.0) is None
    print("✓ conviction_to_grade returns None below the real floor, not a fabricated low grade")


def test_conviction_to_grade_none_for_none_input():
    assert grading.conviction_to_grade(None) is None


# ----------------------------------------------------------------- conviction_to_grade: ceiling normalization
def test_conviction_to_grade_no_ceiling_matches_old_raw_behavior():
    # Backward compatibility: omitting ceiling entirely must behave exactly as before this fix.
    assert grading.conviction_to_grade(3.5) == grading.conviction_to_grade(3.5, None)
    assert grading.conviction_to_grade(1.8) == grading.conviction_to_grade(1.8, None)


def test_conviction_to_grade_hr_own_ceiling_unchanged():
    # HR's own ceiling (~9.09, matching REFERENCE_CEILING itself) should produce IDENTICAL
    # letter grades before and after normalization -- the whole point of using HR's own ceiling
    # as the fixed benchmark is that HR's own grades don't move at all.
    hr_ceiling = 1.0 / 0.11
    for conviction in (3.5, 2.2, 1.6, 1.25, 1.0):
        raw_grade = grading.conviction_to_grade(conviction)
        normalized_grade = grading.conviction_to_grade(conviction, hr_ceiling)
        assert (raw_grade is None) == (normalized_grade is None)
        if raw_grade is not None:
            assert raw_grade["letter"] == normalized_grade["letter"]
    print("✓ conviction_to_grade produces identical grades for HR's own ceiling, confirming backward compatibility")


def test_conviction_to_grade_low_ceiling_market_can_now_reach_a():
    # The real, confirmed bug this fix addresses: a market with ref=0.5 (every market on every
    # non-MLB sport, plus most of MLB's own newer markets) has a raw ceiling of exactly 2.0x --
    # mathematically incapable of reaching a 3.0x "A" threshold without normalization. Confirms
    # a play at 90% of ITS OWN ceiling (1.8 raw, ceiling 2.0) now correctly grades A.
    grade = grading.conviction_to_grade(1.8, ceiling=2.0)
    assert grade is not None
    assert grade["letter"] == "A"
    assert grade["conviction"] == 1.8   # the DISPLAYED number stays the real, raw one
    print("✓ conviction_to_grade lets a low-ceiling market (e.g. any ref=0.5 market) reach A when genuinely near its own ceiling")


def test_conviction_to_grade_would_have_been_impossible_without_normalization():
    # Confirms the OLD (pre-fix) behavior really would have failed here -- 1.8 raw conviction is
    # well below the 3.0 threshold on its own, proving the fix is doing real work, not a no-op.
    assert grading.conviction_to_grade(1.8) is not None
    assert grading.conviction_to_grade(1.8)["letter"] != "A"


def test_conviction_to_grade_high_ceiling_market_gets_compressed():
    # The real, reported Stolen Bases issue: a market with MORE headroom than HR (ref=0.05,
    # ceiling 20.0) should have its conviction correctly compressed relative to HR, not inflated.
    # A real burner's raw 4.78x conviction (ceiling 20.0) should normalize DOWN, not stay at 4.78.
    grade = grading.conviction_to_grade(4.78, ceiling=20.0)
    assert grade is not None
    assert grade["conviction"] == 4.78   # still the honest, real raw number, displayed as-is
    # normalized value = 4.78 * (9.0909/20.0) = ~2.17 -> B, not A
    assert grade["letter"] == "B"
    print("✓ conviction_to_grade correctly compresses a high-ceiling market's (e.g. Stolen Bases) inflated conviction")


def test_conviction_to_grade_similar_probability_different_markets_now_comparable():
    # The real end-to-end validation: a real burner's SB play (23.9% prob, ceiling 20.0, raw
    # conviction 4.78) and a real elite slugger's HR play (22.3% prob, ceiling 9.09, raw
    # conviction 2.03) have nearly identical real probabilities -- they should now land on
    # comparable, not wildly different, grades.
    sb_grade = grading.conviction_to_grade(4.78, ceiling=20.0)
    hr_grade = grading.conviction_to_grade(2.03, ceiling=9.09)
    assert sb_grade["letter"] == "B"
    assert hr_grade["letter"] == "B"
    print("✓ conviction_to_grade now grades two markets' near-identical real probabilities comparably, not wildly apart")


def test_conviction_to_grade_zero_or_negative_ceiling_falls_back_to_raw():
    # A defensive edge case: a malformed/zero ceiling must not crash or divide by zero, and
    # should fall back to the raw, unnormalized comparison rather than erroring out.
    assert grading.conviction_to_grade(3.5, ceiling=0) == grading.conviction_to_grade(3.5)
    assert grading.conviction_to_grade(3.5, ceiling=-1) == grading.conviction_to_grade(3.5)


# ----------------------------------------------------------------- organize_graded_picks
def _pick(player, team, game, conviction, market="Batter HR"):
    return {"Player": player, "Team": team, "Game": game, "Market": market, "Side": "Over",
           "Line": 0.5, "ModelProb": 0.3, "Fair": -100, "Conviction": conviction, "Why": "x"}


def test_organize_graded_picks_groups_by_game_and_player():
    plays = [
        _pick("A", "TB", "TB @ BOS", 3.5),
        _pick("B", "BOS", "TB @ BOS", 2.0),
        _pick("C", "NYY", "SEA @ NYY", 4.0),
    ]
    result = grading.organize_graded_picks(plays)
    assert len(result) == 2
    games = {g["game"]: g for g in result}
    assert len(games["TB @ BOS"]["players"]) == 2
    assert len(games["SEA @ NYY"]["players"]) == 1
    print("✓ organize_graded_picks correctly groups plays by game and by player within each game")


def test_organize_graded_picks_sorts_games_by_best_conviction():
    plays = [
        _pick("A", "TB", "Game Low", 1.3),
        _pick("B", "NYY", "Game High", 4.5),
    ]
    result = grading.organize_graded_picks(plays)
    assert result[0]["game"] == "Game High"
    assert result[1]["game"] == "Game Low"
    print("✓ organize_graded_picks sorts games with the most interesting (highest conviction) first")


def test_organize_graded_picks_sorts_players_within_game():
    plays = [
        _pick("Low Player", "TB", "TB @ BOS", 1.3),
        _pick("High Player", "BOS", "TB @ BOS", 3.8),
    ]
    result = grading.organize_graded_picks(plays)
    assert result[0]["players"][0]["player"] == "High Player"
    assert result[0]["players"][1]["player"] == "Low Player"


def test_organize_graded_picks_filters_ungraded_plays():
    plays = [
        _pick("Real Play", "TB", "TB @ BOS", 2.0),
        _pick("Too Weak", "TB", "TB @ BOS", 1.0),   # below the 1.2 floor
    ]
    result = grading.organize_graded_picks(plays)
    all_players = [p["player"] for g in result for p in g["players"]]
    assert "Real Play" in all_players
    assert "Too Weak" not in all_players
    print("✓ organize_graded_picks correctly excludes plays below the real grading floor")


def test_organize_graded_picks_empty_when_nothing_graded():
    plays = [_pick("A", "TB", "TB @ BOS", 1.0), _pick("B", "TB", "TB @ BOS", 0.8)]
    assert grading.organize_graded_picks(plays) == []


def test_organize_graded_picks_each_play_carries_grade():
    plays = [_pick("A", "TB", "TB @ BOS", 3.2)]
    result = grading.organize_graded_picks(plays)
    play = result[0]["players"][0]["plays"][0]
    assert play["_grade"] == {"letter": "A", "tier": "Top Lean", "conviction": 3.2}


def test_organize_graded_picks_multiple_plays_per_player_sorted():
    plays = [
        _pick("Multi Play", "TB", "TB @ BOS", 1.5, market="Batter Total Hits"),
        _pick("Multi Play", "TB", "TB @ BOS", 3.0, market="Batter HR"),
    ]
    result = grading.organize_graded_picks(plays)
    player_plays = result[0]["players"][0]["plays"]
    assert player_plays[0]["Market"] == "Batter HR"        # higher conviction first
    assert player_plays[1]["Market"] == "Batter Total Hits"
    print("✓ organize_graded_picks sorts a single player's own multiple plays by conviction too")


def test_organize_graded_picks_works_for_non_mlb_shaped_plays():
    # Regression guard for the REAL confirmed bug this module was created to fix: Graded Picks
    # used to call P.organize_graded_picks(plays) where P is whichever sport's own projections
    # module is active. That crashed immediately (AttributeError, confirmed directly) for every
    # non-MLB sport, since organize_graded_picks only ever lived in MLB's projections.py. This
    # uses WNBA-market-shaped plays (Points/Rebounds/Assists, not Batter HR/Pitcher Strikeouts)
    # specifically to prove the fix doesn't just avoid crashing, it produces the correct result
    # for a genuinely different sport's own market names.
    plays = [
        {"Player": "Star Guard", "Team": "Aces", "Game": "Aces @ Liberty", "Market": "Points",
        "Side": "Over", "Line": 20.5, "ModelProb": 0.60, "Fair": -150, "Conviction": 2.8, "Why": "x"},
        {"Player": "Role Player", "Team": "Liberty", "Game": "Aces @ Liberty", "Market": "Rebounds",
        "Side": "Over", "Line": 6.5, "ModelProb": 0.52, "Fair": -108, "Conviction": 1.3, "Why": "y"},
    ]
    result = grading.organize_graded_picks(plays)
    assert len(result) == 1
    assert result[0]["game"] == "Aces @ Liberty"
    assert result[0]["players"][0]["player"] == "Star Guard"   # higher conviction first
    assert result[0]["players"][0]["plays"][0]["_grade"]["letter"] == "B"
    assert result[0]["players"][1]["player"] == "Role Player"
    assert result[0]["players"][1]["plays"][0]["_grade"]["letter"] == "D"
    print("✓ organize_graded_picks correctly handles WNBA-shaped plays (Points/Rebounds), not just MLB markets — the real fix confirmed working, not just non-crashing")


# ----------------------------------------------------------------- grade_accuracy_by_letter
def _graded_play(conviction, hit):
    return {"Conviction": conviction, "Hit": hit, "Player": "X", "Market": "Batter HR"}


def test_grade_accuracy_computes_hit_rate_per_letter():
    plays = [
        _graded_play(3.5, True), _graded_play(3.2, True), _graded_play(3.1, False),   # A: 2/3
        _graded_play(2.5, True), _graded_play(2.1, False),                            # B: 1/2
    ]
    result = grading.grade_accuracy_by_letter(plays)
    by_letter = {r["letter"]: r for r in result}
    assert by_letter["A"]["n"] == 3
    assert by_letter["A"]["hit_rate"] == round(2 / 3, 3)
    assert by_letter["B"]["n"] == 2
    assert by_letter["B"]["hit_rate"] == 0.5
    print("✓ grade_accuracy_by_letter correctly computes real hit rate per letter grade")


def test_grade_accuracy_excludes_unsettled_plays():
    plays = [_graded_play(3.0, True), _graded_play(3.0, None)]   # one play still pending
    result = grading.grade_accuracy_by_letter(plays)
    a = next(r for r in result if r["letter"] == "A")
    assert a["n"] == 1   # only the settled play counted
    print("✓ grade_accuracy_by_letter excludes unsettled (Hit=None) plays from the count")


def test_grade_accuracy_excludes_below_floor():
    plays = [_graded_play(3.0, True), _graded_play(0.8, True)]   # second play never gets a grade
    result = grading.grade_accuracy_by_letter(plays)
    total_n = sum(r["n"] for r in result)
    assert total_n == 1


def test_grade_accuracy_absent_grade_not_fabricated():
    plays = [_graded_play(3.0, True)]   # only an A-grade play exists in this window
    result = grading.grade_accuracy_by_letter(plays)
    letters = {r["letter"] for r in result}
    assert letters == {"A"}   # B/C/D simply absent, not shown as a fabricated 0%
    print("✓ grade_accuracy_by_letter omits grades with zero settled plays rather than faking a rate")


def test_grade_accuracy_empty_when_nothing_settled():
    plays = [_graded_play(3.0, None), _graded_play(2.0, None)]
    assert grading.grade_accuracy_by_letter(plays) == []


def test_grade_accuracy_preserves_grade_order():
    plays = [_graded_play(1.3, True), _graded_play(3.5, True), _graded_play(2.2, False)]
    result = grading.grade_accuracy_by_letter(plays)
    letters_in_order = [r["letter"] for r in result]
    assert letters_in_order == ["A", "B", "D"]   # A, B, D present (no C plays) — stays A->D order
    print("✓ grade_accuracy_by_letter preserves A->D order regardless of input order")


def test_grade_accuracy_works_for_non_mlb_shaped_plays():
    # Same regression guard as organize_graded_picks' own cross-sport test, applied here too —
    # grade_accuracy_by_letter had the identical MLB-only-module problem before this fix.
    plays = [
        {"Conviction": 3.2, "Hit": True, "Player": "Star Guard", "Market": "Points"},
        {"Conviction": 3.1, "Hit": False, "Player": "Other Guard", "Market": "Points"},
    ]
    result = grading.grade_accuracy_by_letter(plays)
    a = next(r for r in result if r["letter"] == "A")
    assert a["n"] == 2
    assert a["hit_rate"] == 0.5
    print("✓ grade_accuracy_by_letter correctly handles WNBA-shaped graded plays")


# ----------------------------------------------------------------- build_parlay_leg_pool
def _leg(player, team, game, conviction, market="Batter HR", model_prob=0.3):
    return {"Player": player, "Team": team, "Game": game, "Market": market, "Side": "Over",
           "Line": 0.5, "ModelProb": model_prob, "Fair": -100, "Conviction": conviction, "Why": "x"}


def test_parlay_pool_excludes_second_leg_on_same_player():
    # THE core correlation safeguard -- a second market on the same player must never make it
    # into the pool, regardless of how high its own conviction is.
    plays = [
        _leg("Ohtani", "LAD", "LAD @ SF", 3.5, market="Batter HR"),
        _leg("Ohtani", "LAD", "LAD @ SF", 3.2, market="Batter Total Bases"),   # same player, different market
        _leg("Judge", "NYY", "NYY @ BOS", 2.0, market="Batter HR"),
    ]
    pool = grading.build_parlay_leg_pool(plays)
    players = [p["Player"] for p in pool]
    assert players.count("Ohtani") == 1   # only the higher-conviction Ohtani leg survives
    assert "Judge" in players
    print("✓ build_parlay_leg_pool excludes a second leg on the same player, the core correlation safeguard")


def test_parlay_pool_keeps_higher_conviction_leg_when_same_player_collides():
    plays = [
        _leg("Ohtani", "LAD", "LAD @ SF", 2.0, market="Batter Total Bases"),
        _leg("Ohtani", "LAD", "LAD @ SF", 3.5, market="Batter HR"),   # listed second, but higher conviction
    ]
    pool = grading.build_parlay_leg_pool(plays)
    assert len(pool) == 1
    assert pool[0]["Market"] == "Batter HR"   # the genuinely higher-conviction leg wins, not just first-seen
    print("✓ build_parlay_leg_pool keeps the higher-conviction leg when two plays collide on the same player")


def test_parlay_pool_same_name_different_team_not_falsely_collided():
    # A real, deliberate edge case: two genuinely different people can share a common surname
    # across different teams -- player uniqueness is keyed on (Player, Team), not Player alone.
    plays = [
        _leg("Garcia", "Team A", "Team A @ Team C", 3.0),
        _leg("Garcia", "Team B", "Team B @ Team D", 2.5),
    ]
    pool = grading.build_parlay_leg_pool(plays)
    assert len(pool) == 2
    print("✓ build_parlay_leg_pool correctly treats same-name players on different teams as different people")


def test_parlay_pool_respects_max_per_game():
    plays = [_leg(f"Player{i}", f"Team{i}", "A @ B", 3.0 - i * 0.1) for i in range(5)]
    pool = grading.build_parlay_leg_pool(plays, max_per_game=2)
    assert len(pool) == 2
    print("✓ build_parlay_leg_pool respects the max-per-game cap")


def test_parlay_pool_respects_max_per_market():
    plays = [_leg(f"Player{i}", f"Team{i}", f"Game{i}", 3.0 - i * 0.1, market="Batter HR") for i in range(5)]
    pool = grading.build_parlay_leg_pool(plays, max_per_game=99, max_per_market=2)
    assert len(pool) == 2
    print("✓ build_parlay_leg_pool respects the max-per-market cap")


def test_parlay_pool_default_caps_a_single_skewed_market_at_two_legs():
    # Regression guard for a real, reported issue: three different real base-stealers' Stolen
    # Bases legs alone filled an entire early tier before any other market appeared, because SB
    # is a genuinely more skewed market than HR (an elite burner's conviction ratio can run well
    # above an elite slugger's for a similar raw probability). Confirms the DEFAULT (not an
    # explicitly passed cap) now limits this to 2, using the exact market name involved.
    plays = [_leg(f"Burner{i}", f"Team{i}", f"Game{i}", 4.0 - i * 0.3, market="Batter Stolen Bases")
            for i in range(5)]
    pool = grading.build_parlay_leg_pool(plays)   # no max_per_market passed -- testing the DEFAULT
    assert len(pool) == 2
    print("✓ build_parlay_leg_pool's default correctly caps a single skewed market (e.g. Stolen Bases) at 2 legs")


# ----------------------------------------------------------------- build_parlay_leg_pool: min_pool_size
def test_parlay_pool_min_pool_size_zero_matches_old_behavior():
    plays = [_leg(f"P{i}", f"T{i}", f"G{i}", 3.0 - i * 0.1, market="Pitcher Strikeouts") for i in range(6)]
    assert grading.build_parlay_leg_pool(plays) == grading.build_parlay_leg_pool(plays, min_pool_size=0)


def test_parlay_pool_min_pool_size_loosens_market_cap_for_single_market():
    # THE exact real, reported bug: selecting only "Pitcher Strikeouts" (a single market) with
    # the default max_per_market=2 silently capped the whole pool at 2 legs, even with 6 real,
    # different graded pitchers on the board. Confirms min_pool_size=6 correctly loosens the
    # market cap (there's nothing else to diversify into with only one market present) while the
    # game cap stays real (each leg is its own distinct game here, so it was never the bottleneck).
    plays = [_leg(f"Pitcher{i}", f"Team{i}", f"Game{i}", 3.0 - i * 0.1, market="Pitcher Strikeouts")
            for i in range(6)]
    pool = grading.build_parlay_leg_pool(plays, min_pool_size=6)
    assert len(pool) == 6
    print("✓ build_parlay_leg_pool correctly loosens the market cap when only one market is selected but enough real legs exist")


def test_parlay_pool_min_pool_size_does_not_loosen_when_already_diverse_enough():
    # When there's already enough real diversity to hit min_pool_size under the ORIGINAL caps,
    # nothing should loosen -- confirms this doesn't just always widen caps regardless of need.
    plays = [_leg(f"P{i}", f"T{i}", f"G{i}", 3.0 - i * 0.1, market=f"Market{i % 3}") for i in range(6)]
    pool_normal = grading.build_parlay_leg_pool(plays)
    pool_with_min = grading.build_parlay_leg_pool(plays, min_pool_size=6)
    assert pool_normal == pool_with_min
    print("✓ build_parlay_leg_pool doesn't loosen caps unnecessarily when the original caps already support the requested size")


def test_parlay_pool_min_pool_size_loosens_game_cap_too():
    # The same real mechanism applies symmetrically to games, not just markets -- a thin slate
    # with few games shouldn't strand the bigger tiers either.
    plays = [_leg(f"Player{i}", f"Team{i}", "OnlyGame", 3.0 - i * 0.1, market=f"Market{i}") for i in range(6)]
    pool = grading.build_parlay_leg_pool(plays, min_pool_size=6)
    assert len(pool) == 6
    print("✓ build_parlay_leg_pool correctly loosens the game cap too when only one game is available")


def test_parlay_pool_min_pool_size_still_respects_same_player_exclusion():
    # THE core safeguard must never be loosened by this mechanism, no matter how large
    # min_pool_size is -- confirms same-player exclusion stays a hard constraint regardless.
    plays = [_leg("OnlyPlayer", "TeamX", f"Game{i}", 3.0 - i * 0.1, market=f"Market{i}") for i in range(6)]
    pool = grading.build_parlay_leg_pool(plays, min_pool_size=6)
    assert len(pool) == 1   # still just the one real distinct player, regardless of min_pool_size
    print("✓ build_parlay_leg_pool never loosens the same-player exclusion, even to satisfy min_pool_size")


def test_parlay_pool_min_pool_size_cannot_exceed_real_available_legs():
    # If there genuinely aren't enough distinct players even with loosened caps, the pool stays
    # honestly smaller than min_pool_size rather than fabricating legs that don't exist.
    plays = [_leg(f"P{i}", f"T{i}", "G1", 3.0 - i * 0.1, market="Market1") for i in range(3)]
    pool = grading.build_parlay_leg_pool(plays, min_pool_size=6)
    assert len(pool) == 3
    print("✓ build_parlay_leg_pool honestly returns fewer legs than min_pool_size when that's all that genuinely exists")


def test_parlay_pool_excludes_below_floor_plays():
    plays = [_leg("Real Play", "A", "A @ B", 2.0), _leg("Too Weak", "C", "C @ D", 1.0)]
    pool = grading.build_parlay_leg_pool(plays)
    assert len(pool) == 1 and pool[0]["Player"] == "Real Play"


def test_parlay_pool_sorted_by_conviction_descending():
    plays = [_leg("Low", "A", "A @ B", 1.3, market="Batter Total Bases"),
            _leg("High", "C", "C @ D", 3.5, market="Batter HR"),
            _leg("Mid", "E", "E @ F", 2.0, market="Batter Strikeouts")]
    pool = grading.build_parlay_leg_pool(plays)
    assert [p["Player"] for p in pool] == ["High", "Mid", "Low"]


# ----------------------------------------------------------------- combined_parlay_prob
def test_combined_parlay_prob_multiplies_correctly():
    legs = [_leg("A", "T", "G", 3.0, model_prob=0.5), _leg("B", "T2", "G2", 2.5, model_prob=0.4)]
    assert grading.combined_parlay_prob(legs) == pytest.approx(0.2, rel=1e-9)
    print("✓ combined_parlay_prob correctly multiplies each leg's own probability")


def test_combined_parlay_prob_empty_legs():
    assert grading.combined_parlay_prob([]) == 1.0


def test_combined_parlay_prob_decreases_with_more_legs():
    legs = [_leg(f"P{i}", f"T{i}", f"G{i}", 3.0, model_prob=0.6) for i in range(6)]
    probs = [grading.combined_parlay_prob(legs[:n]) for n in range(1, 7)]
    assert probs == sorted(probs, reverse=True)   # strictly decreasing as more legs are chained
    print("✓ combined_parlay_prob correctly decreases as more legs are chained together")


# ----------------------------------------------------------------- build_suggested_parlays
def _big_diverse_pool(n=8):
    return [_leg(f"Player{i}", f"Team{i}", f"Game{i}", 3.5 - i * 0.15, market=f"Market{i % 4}",
                model_prob=0.55) for i in range(n)]


def test_suggested_parlays_builds_all_three_tiers_with_enough_legs():
    plays = _big_diverse_pool(8)
    parlays = grading.build_suggested_parlays(plays)
    tiers = {p["tier"]: p for p in parlays}
    assert set(tiers.keys()) == {"Safer", "Balanced", "Longshot"}
    assert tiers["Safer"]["size"] == 2
    assert tiers["Balanced"]["size"] == 4
    assert tiers["Longshot"]["size"] == 6
    print("✓ build_suggested_parlays correctly builds all three tiers when the pool is large enough")


def test_suggested_parlays_tiers_are_cumulative_from_the_same_pool():
    plays = _big_diverse_pool(8)
    parlays = grading.build_suggested_parlays(plays)
    tiers = {p["tier"]: p for p in parlays}
    safer_players = [leg["Player"] for leg in tiers["Safer"]["legs"]]
    balanced_players = [leg["Player"] for leg in tiers["Balanced"]["legs"]]
    assert balanced_players[:2] == safer_players   # the 4-leg tier's first two legs ARE the 2-leg tier
    print("✓ build_suggested_parlays tiers are correctly cumulative, not independently re-optimized sets")


def test_suggested_parlays_skips_tier_when_pool_too_small():
    plays = _big_diverse_pool(3)   # enough for a 2-leg tier, not enough for 4 or 6
    parlays = grading.build_suggested_parlays(plays)
    tiers = {p["tier"] for p in parlays}
    assert tiers == {"Safer"}
    print("✓ build_suggested_parlays skips tiers it can't honestly fill rather than padding with weaker plays")


def test_suggested_parlays_empty_when_pool_too_thin_for_any_tier():
    plays = _big_diverse_pool(1)
    assert grading.build_suggested_parlays(plays) == []


def test_suggested_parlays_includes_combined_odds():
    plays = _big_diverse_pool(8)
    parlays = grading.build_suggested_parlays(plays)
    for p in parlays:
        assert 0.0 < p["combined_prob"] < 1.0
        assert p["combined_fair_decimal"] > 1.0
        assert p["combined_fair_american"] is not None
    print("✓ build_suggested_parlays correctly includes real combined odds for every tier")


def test_suggested_parlays_works_for_non_mlb_shaped_plays():
    # Regression guard matching the same real fix this module exists for -- confirms the parlay
    # builder works correctly for a genuinely different sport's own market names, not just MLB's.
    plays = [
        {"Player": "Star Guard", "Team": "Aces", "Game": "Aces @ Liberty", "Market": "Points",
        "Side": "Over", "Line": 20.5, "ModelProb": 0.60, "Fair": -150, "Conviction": 2.8, "Why": "x"},
        {"Player": "Role Player", "Team": "Liberty", "Game": "Aces @ Liberty", "Market": "Rebounds",
        "Side": "Over", "Line": 6.5, "ModelProb": 0.55, "Fair": -122, "Conviction": 1.5, "Why": "y"},
    ]
    parlays = grading.build_suggested_parlays(plays)
    assert len(parlays) == 1   # only enough diverse legs for the Safer (2-leg) tier
    assert parlays[0]["tier"] == "Safer"
    print("✓ build_suggested_parlays correctly handles WNBA-shaped plays, confirming cross-sport support from day one")


def test_suggested_parlays_single_market_selection_still_fills_all_tiers():
    # The exact real, reported scenario: a person filters the page down to a single market
    # (e.g. "Pitcher Strikeouts" only) and still expects Balanced/Longshot to build, given
    # enough real, different pitchers exist that night -- not silently stuck at Safer only
    # because a market-diversity cap has nothing left to diversify into.
    plays = [_leg(f"Pitcher{i}", f"Team{i}", f"Game{i}", 3.5 - i * 0.15, market="Pitcher Strikeouts")
            for i in range(8)]
    parlays = grading.build_suggested_parlays(plays)
    tiers = {p["tier"] for p in parlays}
    assert tiers == {"Safer", "Balanced", "Longshot"}
    print("✓ build_suggested_parlays fills all three tiers even with only one market selected, given enough real graded plays")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
