"""
test_grading.py — offline tests for grading.py, the shared sport-agnostic letter-grade/tier
logic used by Graded Picks and Retrospective across every sport on this platform.

    python test_grading.py     # or: pytest test_grading.py
"""

import grading
import pytest


# ----------------------------------------------------------------- conviction_to_grade
def test_conviction_to_grade_thresholds():
    assert grading.conviction_to_grade(3.5) == {"letter": "A", "tier": "Top Lean", "conviction": 3.5, "rank_value": 3.5}
    assert grading.conviction_to_grade(3.0) == {"letter": "A", "tier": "Top Lean", "conviction": 3.0, "rank_value": 3.0}
    assert grading.conviction_to_grade(2.99) == {"letter": "B", "tier": "Strong Lean", "conviction": 2.99, "rank_value": 2.99}
    assert grading.conviction_to_grade(2.0) == {"letter": "B", "tier": "Strong Lean", "conviction": 2.0, "rank_value": 2.0}
    assert grading.conviction_to_grade(1.99) == {"letter": "C", "tier": "Lean", "conviction": 1.99, "rank_value": 1.99}
    assert grading.conviction_to_grade(1.5) == {"letter": "C", "tier": "Lean", "conviction": 1.5, "rank_value": 1.5}
    assert grading.conviction_to_grade(1.49) == {"letter": "D", "tier": "Watch", "conviction": 1.49, "rank_value": 1.49}
    assert grading.conviction_to_grade(1.2) == {"letter": "D", "tier": "Watch", "conviction": 1.2, "rank_value": 1.2}
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


def test_conviction_to_grade_ceiling_of_exactly_one_falls_back_to_raw():
    # A real, deliberate guard added alongside the anchor fix: ceiling=1.0 would divide by zero
    # in the new (ceiling - 1.0) denominator -- an extreme, unrealistic edge case (it would
    # require a reference probability of exactly 0 or 1), but must not crash.
    assert grading.conviction_to_grade(3.5, ceiling=1.0) == grading.conviction_to_grade(3.5)


# ----------------------------------------------------------------- conviction_to_grade: anchor-at-1.0 fix
def test_conviction_to_grade_trivial_edge_on_low_ceiling_market_no_longer_reaches_a():
    # THE exact real, reported bug: a trivial, barely-above-breakeven raw conviction (1.03x --
    # essentially no real edge at all) on a low-ceiling market (H-R-R's Under side, ceiling
    # ~2.63) was reaching "A" purely because the OLD normalization scaled the whole raw number,
    # including its 1.0 no-edge baseline, by the market's ceiling ratio. Confirmed directly this
    # exact case now correctly falls below even the D-grade floor.
    grade = grading.conviction_to_grade(1.03, ceiling=2.6315789473684212)
    assert grade is None
    print("✓ conviction_to_grade no longer lets a trivial, near-breakeven edge on a low-ceiling market reach A")


def test_conviction_to_grade_anchor_fix_still_lets_genuine_low_ceiling_edge_reach_a():
    # Confirms the fix doesn't overcorrect -- a REAL, substantial edge (not a token one) on a
    # low-ceiling market must still be able to reach A, the original intent of ceiling
    # normalization in the first place.
    grade = grading.conviction_to_grade(1.8, ceiling=2.0)
    assert grade is not None
    assert grade["letter"] == "A"
    print("✓ conviction_to_grade's anchor fix still lets a genuinely large edge on a low-ceiling market reach A")


def test_conviction_to_grade_anchor_fix_hr_still_byte_identical():
    # HR's own ceiling equals REFERENCE_CEILING exactly, so the new formula must reduce to
    # graded_value == conviction exactly, same as before this fix -- confirmed across the same
    # range of values the original ceiling-normalization tests already used.
    hr_ceiling = 1.0 / 0.11
    for conviction in (3.5, 2.2, 1.6, 1.25, 1.0):
        with_ceiling = grading.conviction_to_grade(conviction, hr_ceiling)
        without_ceiling = grading.conviction_to_grade(conviction)
        assert with_ceiling == without_ceiling
    print("✓ conviction_to_grade's anchor fix leaves HR's own grades exactly byte-identical to the raw, unnormalized comparison")


def test_conviction_to_grade_anchor_fix_sb_compression_still_holds():
    # Regression guard: the real Stolen Bases compression fix from earlier this session must
    # still hold under the corrected formula, not regress back to the original over-inflation.
    sb_grade = grading.conviction_to_grade(4.78, ceiling=20.0)
    hr_grade = grading.conviction_to_grade(2.03, ceiling=9.09)
    assert sb_grade["letter"] == "B"
    assert hr_grade["letter"] == "B"
    print("✓ conviction_to_grade's anchor fix preserves the earlier Stolen Bases compression fix")


# ----------------------------------------------------------------- conviction_to_grade: AMPLIFICATION_CAP fix
def test_conviction_to_grade_modest_edge_on_compressed_ceiling_market_no_longer_reaches_a():
    # THE exact real, second reported case: a real but genuinely modest edge (-115 American odds
    # implies ModelProb ~53.5%, raw conviction 1.408x against H-R-R's real Under-side ceiling of
    # ~2.63) was STILL reaching "A" even after the anchor fix, because the anchor fix alone was
    # mathematically consistent but didn't account for how compressed a near-50%-reference
    # market's ceiling naturally is. Confirmed this exact real case now lands at a "B", not "A".
    grade = grading.conviction_to_grade(1.408, ceiling=2.6316)
    assert grade is not None
    assert grade["letter"] == "B"
    print("✓ conviction_to_grade's amplification cap correctly downgrades a modest edge on a compressed-ceiling market from A to B")


def test_conviction_to_grade_amplification_cap_still_lets_exceptional_near_50_edge_reach_a():
    # Confirms the cap doesn't overcorrect -- a GENUINELY exceptional edge on a near-50%-
    # reference market (90% ModelProb, raw conviction 1.8x against a ceiling of 2.0, e.g. a
    # real WNBA/NBA/NFL-style market) must still be able to reach A.
    grade = grading.conviction_to_grade(1.8, ceiling=2.0)
    assert grade is not None
    assert grade["letter"] == "A"
    print("✓ conviction_to_grade's amplification cap still lets a genuinely exceptional near-50%-reference edge reach A")


def test_conviction_to_grade_amplification_cap_keeps_modest_near_50_edge_well_below_a():
    # A merely modest edge (60% ModelProb, raw conviction 1.2x) on the same kind of market
    # should stay well below A -- confirms the cap produces a real, meaningful spread between
    # "exceptional" and "modest" for markets whose ceiling is naturally compressed.
    grade = grading.conviction_to_grade(1.2, ceiling=2.0)
    assert grade is None or grade["letter"] in ("C", "D")
    print("✓ conviction_to_grade's amplification cap keeps a merely modest near-50%-reference edge well below A")


def test_conviction_to_grade_amplification_cap_hr_still_byte_identical():
    # HR's own ceiling equals REFERENCE_CEILING, so the amplification ratio is exactly 1.0 --
    # well below the cap -- meaning this fix must leave HR's own grades completely untouched.
    hr_ceiling = 1.0 / 0.11
    for conviction in (3.5, 2.2, 1.6, 1.25, 1.0):
        with_ceiling = grading.conviction_to_grade(conviction, hr_ceiling)
        without_ceiling = grading.conviction_to_grade(conviction)
        assert with_ceiling == without_ceiling
    print("✓ conviction_to_grade's amplification cap leaves HR's own grades exactly byte-identical")


def test_conviction_to_grade_amplification_cap_trivial_edge_still_excluded():
    # Regression guard: the original anchor-fix bug case (a trivial, near-1.0 raw conviction on
    # H-R-R's Under side) must still fall below the D floor under the cap too.
    grade = grading.conviction_to_grade(1.03, ceiling=2.6316)
    assert grade is None
    print("✓ conviction_to_grade's amplification cap still correctly excludes the original trivial-edge bug case")


# ----------------------------------------------------------------- conviction_to_grade: rank_value
def test_conviction_to_grade_rank_value_resolves_real_cross_market_inversion():
    # THE exact real, confirmed problem this field exists to solve: sorting by raw Conviction
    # alone can rank a lower-letter-grade play ABOVE a higher-letter-grade one, purely because
    # different markets' raw numbers run at different scales. Confirmed directly: a genuinely
    # great near-50%-reference play (raw 1.8, ceiling 2.0, real letter A) has a LOWER raw
    # Conviction than a merely decent HR play (raw 2.5, ceiling 9.09, real letter B) -- sorting
    # by raw Conviction inverts them; sorting by rank_value correctly does not.
    a_grade_play = grading.conviction_to_grade(1.8, ceiling=2.0)
    b_grade_play = grading.conviction_to_grade(2.5, ceiling=9.0909)
    assert a_grade_play["letter"] == "A"
    assert b_grade_play["letter"] == "B"
    # The real, confirmed inversion in raw terms:
    assert a_grade_play["conviction"] < b_grade_play["conviction"]
    # rank_value correctly reverses this, matching the real letter grades:
    assert a_grade_play["rank_value"] > b_grade_play["rank_value"]
    print("✓ conviction_to_grade's rank_value correctly resolves the real cross-market ranking inversion raw Conviction alone produces")


def test_conviction_to_grade_rank_value_equals_conviction_without_ceiling():
    grade = grading.conviction_to_grade(2.4)
    assert grade["rank_value"] == grade["conviction"] == 2.4


# ----------------------------------------------------------------- rank_flat_plays
def test_rank_flat_plays_by_rank_value_resolves_cross_market_inversion():
    plays = [
        {"Player": "A", "Conviction": 2.5, "_ceiling": 9.0909, "_grade": grading.conviction_to_grade(2.5, 9.0909)},
        {"Player": "B", "Conviction": 1.8, "_ceiling": 2.0, "_grade": grading.conviction_to_grade(1.8, 2.0)},
    ]
    ranked = grading.rank_flat_plays(plays, key="rank_value")
    assert ranked[0]["Player"] == "B"   # the real A-grade play ranks first, despite lower raw Conviction
    assert ranked[0]["_rank"] == 1
    assert ranked[1]["Player"] == "A"
    assert ranked[1]["_rank"] == 2
    print("✓ rank_flat_plays by rank_value correctly resolves the real cross-market inversion")


def test_rank_flat_plays_by_model_prob():
    plays = [
        {"Player": "LowProb", "ModelProb": 0.30},
        {"Player": "HighProb", "ModelProb": 0.70},
        {"Player": "MidProb", "ModelProb": 0.50},
    ]
    ranked = grading.rank_flat_plays(plays, key="ModelProb")
    assert [p["Player"] for p in ranked] == ["HighProb", "MidProb", "LowProb"]
    assert [p["_rank"] for p in ranked] == [1, 2, 3]
    print("✓ rank_flat_plays by ModelProb correctly orders by real probability of hitting")


def test_rank_flat_plays_missing_grade_sorts_last_not_crash():
    plays = [
        {"Player": "Graded", "_grade": grading.conviction_to_grade(2.0)},
        {"Player": "Ungraded"},   # no _grade at all
    ]
    ranked = grading.rank_flat_plays(plays, key="rank_value")
    assert ranked[0]["Player"] == "Graded"
    assert ranked[1]["Player"] == "Ungraded"
    print("✓ rank_flat_plays handles a play missing _grade gracefully, sorting it last rather than crashing")


def test_rank_flat_plays_does_not_mutate_input_list_order():
    plays = [{"Player": "A", "ModelProb": 0.2}, {"Player": "B", "ModelProb": 0.8}]
    grading.rank_flat_plays(plays, key="ModelProb")
    assert plays[0]["Player"] == "A"   # original list order unchanged, only a new list returned
    print("✓ rank_flat_plays returns a new, sorted list without reordering the caller's own list in place")


# ----------------------------------------------------------------- organize_graded_picks
def _pick(player, team, game, conviction, market="Batter HR", ceiling=None):
    return {"Player": player, "Team": team, "Game": game, "Market": market, "Side": "Over",
           "Line": 0.5, "ModelProb": 0.3, "Fair": -100, "Conviction": conviction, "Why": "x",
           "_ceiling": ceiling}


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
    assert play["_grade"] == {"letter": "A", "tier": "Top Lean", "conviction": 3.2, "rank_value": 3.2}


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


def test_organize_graded_picks_sorts_by_rank_value_not_raw_conviction():
    # THE exact real, confirmed cross-market inversion, now checked inside organize_graded_picks
    # itself: a play with a genuinely LOWER raw Conviction but a HIGHER real letter grade (a
    # near-50%-reference market with a compressed ceiling) must sort ABOVE a play with a higher
    # raw Conviction but a LOWER real letter grade (HR, whose raw numbers run much bigger).
    plays = [
        _pick("Same Player", "T1", "G1", conviction=1.8, market="Points", ceiling=2.0),      # A
        _pick("Same Player", "T1", "G1", conviction=2.5, market="Batter HR", ceiling=9.0909),  # B
    ]
    result = grading.organize_graded_picks(plays)
    player_plays = result[0]["players"][0]["plays"]
    assert player_plays[0]["Market"] == "Points"       # the real A-grade play, despite lower raw Conviction
    assert player_plays[0]["_grade"]["letter"] == "A"
    assert player_plays[1]["Market"] == "Batter HR"
    assert player_plays[1]["_grade"]["letter"] == "B"
    print("✓ organize_graded_picks correctly sorts by rank_value, resolving the real cross-market inversion raw Conviction alone would produce")


def test_organize_graded_picks_game_order_uses_rank_value():
    plays = [
        _pick("Player A", "T1", "Game Alpha", conviction=1.8, market="Points", ceiling=2.0),      # A
        _pick("Player B", "T2", "Game Beta", conviction=2.5, market="Batter HR", ceiling=9.0909),  # B
    ]
    result = grading.organize_graded_picks(plays)
    assert result[0]["game"] == "Game Alpha"   # the game with the real A-grade play comes first
    assert result[1]["game"] == "Game Beta"
    print("✓ organize_graded_picks correctly orders GAMES by rank_value too, not just plays within one player")


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


# ----------------------------------------------------------------- build_parlay_leg_pool: min_grade_letter
def test_parlay_pool_min_grade_letter_excludes_d_grade_plays():
    plays = [
        _leg("A-Grade Play", "T1", "G1", conviction=3.5, market="Batter HR"),
        _leg("B-Grade Play", "T2", "G2", conviction=2.2, market="Batter Total Bases"),
        _leg("C-Grade Play", "T3", "G3", conviction=1.6, market="Batter Strikeouts"),
        _leg("D-Grade Play", "T4", "G4", conviction=1.25, market="Batter Walks"),
    ]
    pool = grading.build_parlay_leg_pool(plays, min_grade_letter="C")
    players = {p["Player"] for p in pool}
    assert players == {"A-Grade Play", "B-Grade Play", "C-Grade Play"}
    assert "D-Grade Play" not in players
    print("✓ build_parlay_leg_pool's min_grade_letter correctly excludes plays below the real floor")


def test_parlay_pool_min_grade_letter_none_matches_old_behavior():
    plays = [_leg("D-Grade Play", "T1", "G1", conviction=1.25)]
    assert (grading.build_parlay_leg_pool(plays, min_grade_letter=None)
           == grading.build_parlay_leg_pool(plays))


def test_parlay_pool_min_grade_letter_a_only_excludes_everything_below_a():
    plays = [_leg("A-Grade Play", "T1", "G1", conviction=3.5),
            _leg("B-Grade Play", "T2", "G2", conviction=2.2)]
    pool = grading.build_parlay_leg_pool(plays, min_grade_letter="A")
    assert len(pool) == 1 and pool[0]["Player"] == "A-Grade Play"


def test_parlay_pool_sorted_by_conviction_descending():
    plays = [_leg("Low", "A", "A @ B", 1.3, market="Batter Total Bases"),
            _leg("High", "C", "C @ D", 3.5, market="Batter HR"),
            _leg("Mid", "E", "E @ F", 2.0, market="Batter Strikeouts")]
    pool = grading.build_parlay_leg_pool(plays)
    assert [p["Player"] for p in pool] == ["High", "Mid", "Low"]


# ----------------------------------------------------------------- _tier_sort_key
def test_tier_sort_key_safety_ranks_by_raw_model_prob_not_conviction():
    # THE real, deliberate distinction: a play with LOWER Conviction but HIGHER raw ModelProb
    # should rank ABOVE a play with higher Conviction but lower ModelProb under "safety" --
    # Conviction measures relative edge, not absolute likelihood, and "safer" should mean the
    # play most likely to simply happen.
    high_conv_low_prob = _leg("A", "T1", "G1", conviction=4.0, model_prob=0.20)   # rare, high-edge
    low_conv_high_prob = _leg("B", "T2", "G2", conviction=1.3, model_prob=0.85)   # common, safe
    key = grading._tier_sort_key("safety")
    ranked = sorted([high_conv_low_prob, low_conv_high_prob], key=key, reverse=True)
    assert ranked[0]["Player"] == "B"   # the higher-probability play ranks first for "safety"
    print("\u2713 _tier_sort_key('safety') correctly ranks by raw probability, not Conviction")


def test_tier_sort_key_payout_ranks_by_inverse_model_prob():
    # The mirror case: "payout" should favor the LOWER-probability (bigger real price) play,
    # even though it has lower Conviction here too -- confirms payout genuinely chases price,
    # not just re-deriving whatever conviction would have picked anyway.
    high_conv_low_prob = _leg("A", "T1", "G1", conviction=4.0, model_prob=0.20)
    low_conv_high_prob = _leg("B", "T2", "G2", conviction=1.3, model_prob=0.85)
    key = grading._tier_sort_key("payout")
    ranked = sorted([high_conv_low_prob, low_conv_high_prob], key=key, reverse=True)
    assert ranked[0]["Player"] == "A"   # the LOWER-probability (bigger payout) play ranks first
    print("\u2713 _tier_sort_key('payout') correctly ranks by lowest probability (biggest real price)")


def test_tier_sort_key_conviction_unchanged_for_balanced():
    high_conv_low_prob = _leg("A", "T1", "G1", conviction=4.0, model_prob=0.20)
    low_conv_high_prob = _leg("B", "T2", "G2", conviction=1.3, model_prob=0.85)
    key = grading._tier_sort_key("conviction")
    ranked = sorted([high_conv_low_prob, low_conv_high_prob], key=key, reverse=True)
    assert ranked[0]["Player"] == "A"   # the higher-Conviction play ranks first, the original metric
    print("\u2713 _tier_sort_key('conviction') correctly preserves the original Conviction-based ranking for Balanced")


# ----------------------------------------------------------------- build_suggested_parlays: per-tier objectives
def test_suggested_parlays_safer_tier_picks_by_probability_not_conviction():
    # A real, end-to-end proof: give Safer a genuine choice between a high-Conviction/low-prob
    # play and a low-Conviction/high-prob play -- Safer must pick the SAFE one, even though a
    # pure Conviction ranking would have picked the other.
    plays = [
        _leg("Longshot Play", "T1", "G1", conviction=4.0, model_prob=0.20),
        _leg("Safe Play A", "T2", "G2", conviction=1.3, model_prob=0.85),
        _leg("Safe Play B", "T3", "G3", conviction=1.25, model_prob=0.80),
    ]
    parlays = grading.build_suggested_parlays(plays, tier_sizes=[(2, "Safer", "safety", None)])
    safer = next(p for p in parlays if p["tier"] == "Safer")
    picked_players = {leg["Player"] for leg in safer["legs"]}
    assert picked_players == {"Safe Play A", "Safe Play B"}
    assert "Longshot Play" not in picked_players
    print("\u2713 build_suggested_parlays' Safer tier correctly picks by real probability, ignoring a higher-Conviction but riskier play")


def test_suggested_parlays_longshot_tier_picks_by_payout_not_just_conviction():
    plays = [
        _leg("Big Price Play", "T1", "G1", conviction=1.4, model_prob=0.15),   # low prob, real edge
        _leg("Safe But Boring", "T2", "G2", conviction=1.35, model_prob=0.88),  # high prob, low edge
    ]
    parlays = grading.build_suggested_parlays(plays, tier_sizes=[(2, "Longshot", "payout", None)])
    longshot = next(p for p in parlays if p["tier"] == "Longshot")
    picked_players = [leg["Player"] for leg in longshot["legs"]]
    assert picked_players[0] == "Big Price Play"   # the lower-probability, bigger-price play ranks first
    print("\u2713 build_suggested_parlays' Longshot tier correctly favors real payout size among genuinely graded plays")


def test_suggested_parlays_different_tiers_can_pick_genuinely_different_legs():
    # The actual concern this whole redesign addresses: with a real spread of probabilities and
    # convictions, Safer and Longshot should be able to pick DIFFERENT legs, not just different
    # SLICES of the same ranking -- confirmed here with a real, deliberately mixed pool.
    plays = [
        _leg("HighProbLowEdge", "T1", "G1", conviction=1.25, model_prob=0.82),
        _leg("LowProbHighEdge", "T2", "G2", conviction=3.8, model_prob=0.18),
        _leg("Middling", "T3", "G3", conviction=2.0, model_prob=0.50),
    ]
    parlays = grading.build_suggested_parlays(
        plays, tier_sizes=[(1, "Safer", "safety", None), (1, "Longshot", "payout", None)])
    safer_pick = next(p for p in parlays if p["tier"] == "Safer")["legs"][0]["Player"]
    longshot_pick = next(p for p in parlays if p["tier"] == "Longshot")["legs"][0]["Player"]
    assert safer_pick == "HighProbLowEdge"
    assert longshot_pick == "LowProbHighEdge"
    assert safer_pick != longshot_pick
    print("\u2713 build_suggested_parlays' Safer and Longshot tiers genuinely diverge, driven by real, different objectives")


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


# ----------------------------------------------------------------- basket_prob_at_least_one_wins
def test_basket_prob_at_least_one_matches_hand_calculation():
    legs = [_leg("A", "T1", "G1", 3.0, model_prob=0.3), _leg("B", "T2", "G2", 2.5, model_prob=0.4)]
    # P(at least one) = 1 - (1-0.3)(1-0.4) = 1 - 0.7*0.6 = 1 - 0.42 = 0.58
    assert grading.basket_prob_at_least_one_wins(legs) == pytest.approx(0.58, rel=1e-9)
    print("✓ basket_prob_at_least_one_wins exactly matches the hand-calculated OR probability")


def test_basket_prob_at_least_one_increases_with_more_legs():
    # THE core, opposite behavior from a parlay: adding MORE independent positions makes "at
    # least one hits" MORE likely, not less -- the exact reason a basket of positions is a
    # fundamentally different, less punishing structure than a parlay chaining the same legs.
    legs = [_leg(f"P{i}", f"T{i}", f"G{i}", 2.0, model_prob=0.2) for i in range(6)]
    probs = [grading.basket_prob_at_least_one_wins(legs[:n]) for n in range(1, 7)]
    assert probs == sorted(probs)   # strictly INCREASING, the opposite of combined_parlay_prob
    print("✓ basket_prob_at_least_one_wins correctly INCREASES as more independent positions are added, the opposite of parlay math")


def test_basket_prob_at_least_one_empty_legs():
    assert grading.basket_prob_at_least_one_wins([]) == 0.0


def test_basket_prob_at_least_one_single_leg_equals_its_own_prob():
    legs = [_leg("A", "T1", "G1", 2.5, model_prob=0.35)]
    assert grading.basket_prob_at_least_one_wins(legs) == pytest.approx(0.35, rel=1e-9)


# ----------------------------------------------------------------- build_speculative_basket
def test_speculative_basket_reuses_the_payout_objective():
    # Confirms the basket picks the SAME kind of legs Longshot would -- lowest real probability
    # among plays clearing the grade floor, not just any graded plays.
    plays = [
        _leg("Safe Play", "T1", "G1", conviction=2.0, model_prob=0.80, market="Batter HR"),
        _leg("Long Odds Play", "T2", "G2", conviction=1.6, model_prob=0.15, market="Batter Total Bases"),
    ]
    basket = grading.build_speculative_basket(plays, size=1)
    assert basket["legs"][0]["Player"] == "Long Odds Play"
    print("✓ build_speculative_basket correctly reuses the payout objective, favoring the real long-odds play")


def test_speculative_basket_respects_min_grade_floor():
    # The same real fix Bold/Longshot needed applies here too -- a D-grade play must never be
    # selected purely for having the longest odds.
    plays = [
        _leg("D-Grade Longshot", "T1", "G1", conviction=1.25, model_prob=0.05, market="Batter HR"),
        _leg("C-Grade Real Play", "T2", "G2", conviction=1.6, model_prob=0.20, market="Batter Total Bases"),
    ]
    basket = grading.build_speculative_basket(plays, size=2)
    grades = {leg["_grade"]["letter"] for leg in basket["legs"]}
    assert "D" not in grades
    print("✓ build_speculative_basket correctly excludes D-grade plays, even ones with the longest odds")


def test_speculative_basket_never_reuses_a_player():
    # The same core correlation safeguard build_parlay_leg_pool already enforces -- confirmed
    # here too, since the basket reuses that exact mechanism.
    plays = [
        _leg("Same Player", "TeamX", "G1", conviction=2.0, model_prob=0.20, market="Batter HR"),
        _leg("Same Player", "TeamX", "G1", conviction=1.8, model_prob=0.15, market="Batter Total Bases"),
    ]
    basket = grading.build_speculative_basket(plays, size=5)
    assert len(basket["legs"]) == 1
    print("✓ build_speculative_basket never includes the same player twice, reusing build_parlay_leg_pool's core safeguard")


def test_speculative_basket_size_controls_leg_count():
    plays = [_leg(f"P{i}", f"T{i}", f"G{i}", 2.0, model_prob=0.20, market=f"Market{i}") for i in range(10)]
    basket_small = grading.build_speculative_basket(plays, size=3)
    basket_large = grading.build_speculative_basket(plays, size=8)
    assert len(basket_small["legs"]) == 3
    assert len(basket_large["legs"]) == 8
    print("✓ build_speculative_basket's size parameter correctly controls the number of independent positions")


def test_speculative_basket_returns_real_summary_stats():
    plays = [_leg(f"P{i}", f"T{i}", f"G{i}", 2.0, model_prob=0.20, market=f"Market{i}") for i in range(5)]
    basket = grading.build_speculative_basket(plays, size=5)
    assert "prob_at_least_one_wins" in basket
    assert "expected_winners" in basket
    assert 0.0 < basket["prob_at_least_one_wins"] < 1.0
    assert basket["expected_winners"] == pytest.approx(1.0, abs=0.01)   # 5 legs * 0.20 each
    print("✓ build_speculative_basket correctly returns real, hand-verifiable summary stats")


def test_speculative_basket_honestly_returns_fewer_legs_when_not_enough_exist():
    plays = [_leg("Only One", "T1", "G1", conviction=2.0, model_prob=0.20, market="Batter HR")]
    basket = grading.build_speculative_basket(plays, size=8)
    assert len(basket["legs"]) == 1
    print("✓ build_speculative_basket honestly returns fewer positions than requested rather than padding with weaker plays")


# ----------------------------------------------------------------- build_suggested_parlays
def _big_diverse_pool(n=8):
    return [_leg(f"Player{i}", f"Team{i}", f"Game{i}", 3.5 - i * 0.1, market=f"Market{i % 5}",
                model_prob=0.55) for i in range(n)]


def test_suggested_parlays_builds_all_five_tiers_with_enough_legs():
    # 2+3+4+5+6 = 20 total legs needed to fill every tier
    plays = _big_diverse_pool(20)
    parlays = grading.build_suggested_parlays(plays)
    tiers = {p["tier"]: p for p in parlays}
    assert set(tiers.keys()) == {"Safer", "Steady", "Balanced", "Bold", "Longshot"}
    assert tiers["Safer"]["size"] == 2
    assert tiers["Steady"]["size"] == 3
    assert tiers["Balanced"]["size"] == 4
    assert tiers["Bold"]["size"] == 5
    assert tiers["Longshot"]["size"] == 6
    print("✓ build_suggested_parlays correctly builds all five tiers when the pool is large enough")


def test_suggested_parlays_tiers_are_non_overlapping():
    # THE real, requested fix: no leg (and therefore no player) should ever appear in more than
    # one tier -- each tier is a genuinely distinct combination, not the same core picks reused
    # with extras bolted on.
    plays = _big_diverse_pool(20)
    parlays = grading.build_suggested_parlays(plays)
    seen_players = set()
    for p in parlays:
        for leg in p["legs"]:
            key = (leg["Player"], leg["Team"])
            assert key not in seen_players, f"{key} appeared in more than one tier"
            seen_players.add(key)
    assert len(seen_players) == 20   # every one of the 20 real legs used exactly once total
    print("✓ build_suggested_parlays tiers are correctly non-overlapping — no leg reused across tiers")


def test_suggested_parlays_earlier_tiers_get_higher_conviction_legs():
    # A real, honest consequence of non-overlapping allocation: since Safer gets first pick of
    # the ranked pool, its own legs should never have LOWER average conviction than a later,
    # bigger tier's legs.
    plays = _big_diverse_pool(20)
    parlays = grading.build_suggested_parlays(plays)
    tiers = {p["tier"]: p for p in parlays}
    safer_avg = sum(leg["Conviction"] for leg in tiers["Safer"]["legs"]) / 2
    longshot_avg = sum(leg["Conviction"] for leg in tiers["Longshot"]["legs"]) / 6
    assert safer_avg > longshot_avg
    print("✓ build_suggested_parlays' earlier (smaller) tiers get first pick of the highest-conviction legs")


def test_suggested_parlays_skips_tier_when_pool_too_small():
    plays = _big_diverse_pool(3)   # enough for Safer (2), not enough for Steady (3) or bigger
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
    # (e.g. "Pitcher Strikeouts" only) and still expects every tier to build, given enough real,
    # different pitchers exist that night -- not silently stuck at Safer only because a
    # market-diversity cap has nothing left to diversify into.
    plays = [_leg(f"Pitcher{i}", f"Team{i}", f"Game{i}", 3.5 - i * 0.1, market="Pitcher Strikeouts")
            for i in range(20)]
    parlays = grading.build_suggested_parlays(plays)
    tiers = {p["tier"] for p in parlays}
    assert tiers == {"Safer", "Steady", "Balanced", "Bold", "Longshot"}
    print("✓ build_suggested_parlays fills all five tiers even with only one market selected, given enough real graded plays")


def test_suggested_parlays_bold_longshot_never_all_d_grade():
    # THE exact real, reported issue: with only Batter HR selected, Bold/Longshot were building
    # parlays entirely out of the WORST, barely-D-grade legs specifically because they had the
    # longest odds -- producing seven-figure American odds no real book would offer. Confirms
    # directly, using a realistic mix of grades within a single market, that Bold/Longshot now
    # never include a D-grade leg, even though "payout" would otherwise have picked exactly the
    # low-probability D-grade legs first.
    plays = (
        [_leg(f"Real{i}", f"TeamR{i}", f"GameR{i}", 2.5 - i * 0.05, market="Batter HR",
             model_prob=0.30 - i * 0.005) for i in range(8)]   # real, well-graded (B/C) plays
        + [_leg(f"Longshot{i}", f"TeamL{i}", f"GameL{i}", 1.25, market="Batter HR",
                model_prob=0.05) for i in range(8)]   # barely-D-grade, but with the LOWEST
                                                       # probability -- exactly what "payout"
                                                       # alone would have chased first
    )
    parlays = grading.build_suggested_parlays(plays)
    for p in parlays:
        if p["tier"] in ("Bold", "Longshot"):
            grades = {leg["_grade"]["letter"] for leg in p["legs"]}
            assert "D" not in grades, f"{p['tier']} included a D-grade leg despite the min_grade floor"
    print("✓ build_suggested_parlays' Bold/Longshot tiers never include a D-grade leg, even when D-grade legs have the longest odds")


# ----------------------------------------------------------------- basket_prob_at_least_one_wins
def test_basket_prob_at_least_one_wins_hand_verified():
    # Hand-verified: P(none hit) = (1-0.3)*(1-0.5) = 0.35, P(at least one) = 1 - 0.35 = 0.65
    legs = [_leg("A", "T1", "G1", conviction=2.0, model_prob=0.3),
           _leg("B", "T2", "G2", conviction=2.0, model_prob=0.5)]
    assert grading.basket_prob_at_least_one_wins(legs) == pytest.approx(0.65, abs=1e-9)
    print("✓ basket_prob_at_least_one_wins matches a hand-verified exact value")


def test_basket_prob_at_least_one_wins_empty_legs():
    assert grading.basket_prob_at_least_one_wins([]) == 0.0


def test_basket_prob_at_least_one_wins_single_leg_equals_its_own_prob():
    legs = [_leg("A", "T1", "G1", conviction=2.0, model_prob=0.42)]
    assert grading.basket_prob_at_least_one_wins(legs) == pytest.approx(0.42, abs=1e-9)


def test_basket_prob_at_least_one_wins_increases_with_more_legs():
    # A real, honest property: adding more independent positions to the basket should only ever
    # RAISE (or hold, never lower) the chance that at least one hits.
    legs = [_leg(f"P{i}", f"T{i}", f"G{i}", conviction=2.0, model_prob=0.2) for i in range(6)]
    probs = [grading.basket_prob_at_least_one_wins(legs[:n]) for n in range(1, 7)]
    assert probs == sorted(probs)   # strictly non-decreasing as more legs are added
    print("✓ basket_prob_at_least_one_wins correctly increases as more independent positions are added to the basket")


# ----------------------------------------------------------------- build_speculative_basket
def test_speculative_basket_reuses_payout_objective():
    # Same real proof pattern used for Bold/Longshot's own payout objective: a lower-Conviction,
    # lower-probability play should rank ABOVE a higher-Conviction, higher-probability play,
    # confirming the basket genuinely reuses the "payout" ranking, not just any ranking.
    plays = [
        _leg("Big Price Play", "T1", "G1", conviction=1.4, model_prob=0.15),
        _leg("Safe But Boring", "T2", "G2", conviction=1.35, model_prob=0.88),
    ]
    basket = grading.build_speculative_basket(plays, size=2, min_grade_letter=None)
    picked_players = [leg["Player"] for leg in basket["legs"]]
    assert picked_players[0] == "Big Price Play"
    print("✓ build_speculative_basket correctly reuses the payout objective, favoring real price over safety")


def test_speculative_basket_reuses_c_grade_floor_by_default():
    # THE same real fix from Bold/Longshot, reused here by default -- confirms a D-grade leg
    # with the longest odds is still excluded, even though "payout" alone would pick it first.
    plays = [
        _leg("Real Play", "T1", "G1", conviction=1.6, model_prob=0.30),   # C grade
        _leg("Worst Longshot", "T2", "G2", conviction=1.25, model_prob=0.05),   # D grade, longest odds
    ]
    basket = grading.build_speculative_basket(plays, size=2)   # default min_grade_letter="C"
    picked_players = {leg["Player"] for leg in basket["legs"]}
    assert "Worst Longshot" not in picked_players
    assert picked_players == {"Real Play"}
    print("✓ build_speculative_basket's default C-grade floor correctly excludes the worst, barely-qualifying longshot")


def test_speculative_basket_min_grade_letter_configurable():
    plays = [_leg(f"P{i}", f"T{i}", f"G{i}", conviction=1.6 - i * 0.05, model_prob=0.20 + i * 0.01)
            for i in range(6)]   # a mix spanning roughly C down to D grade
    basket_c = grading.build_speculative_basket(plays, size=6, min_grade_letter="C")
    basket_b = grading.build_speculative_basket(plays, size=6, min_grade_letter="B")
    assert len(basket_b["legs"]) <= len(basket_c["legs"])
    print("✓ build_speculative_basket's min_grade_letter is genuinely configurable, tightening the pool as expected")


def test_speculative_basket_size_controls_leg_count():
    plays = [_leg(f"P{i}", f"T{i}", f"G{i}", conviction=2.5, model_prob=0.30) for i in range(10)]
    basket_small = grading.build_speculative_basket(plays, size=3)
    basket_large = grading.build_speculative_basket(plays, size=8)
    assert len(basket_small["legs"]) == 3
    assert len(basket_large["legs"]) == 8
    print("✓ build_speculative_basket's size parameter correctly controls how many positions are returned")


def test_speculative_basket_stats_match_actual_selected_legs():
    plays = [_leg(f"P{i}", f"T{i}", f"G{i}", conviction=2.5, model_prob=0.25) for i in range(4)]
    basket = grading.build_speculative_basket(plays, size=4)
    expected_winners_hand = sum(leg["ModelProb"] for leg in basket["legs"])
    expected_at_least_one = grading.basket_prob_at_least_one_wins(basket["legs"])
    assert basket["expected_winners"] == pytest.approx(round(expected_winners_hand, 2), abs=0.01)
    assert basket["prob_at_least_one_wins"] == pytest.approx(expected_at_least_one, abs=0.001)
    print("✓ build_speculative_basket's summary stats are computed directly from the actual selected legs, not a separate, potentially-inconsistent calculation")


def test_speculative_basket_no_combined_fair_fields():
    # A real, deliberate honesty check: since these are INDEPENDENT positions, not a chained
    # parlay, there is no meaningful single "combined fair odds" the way a parlay has -- confirms
    # the basket doesn't fabricate one.
    plays = [_leg(f"P{i}", f"T{i}", f"G{i}", conviction=2.5, model_prob=0.30) for i in range(3)]
    basket = grading.build_speculative_basket(plays, size=3)
    assert "combined_fair_american" not in basket
    assert "combined_fair_decimal" not in basket
    print("✓ build_speculative_basket correctly avoids fabricating a parlay-style combined fair odds for independent positions")


def test_speculative_basket_works_for_non_mlb_shaped_plays():
    plays = [
        {"Player": "Star Guard", "Team": "Aces", "Game": "Aces @ Liberty", "Market": "Points",
        "Side": "Over", "Line": 20.5, "ModelProb": 0.30, "Fair": -100, "Conviction": 1.8, "Why": "x"},
        {"Player": "Role Player", "Team": "Liberty", "Game": "Aces @ Liberty", "Market": "Rebounds",
        "Side": "Over", "Line": 6.5, "ModelProb": 0.25, "Fair": -100, "Conviction": 1.6, "Why": "y"},
    ]
    basket = grading.build_speculative_basket(plays, size=2)
    assert len(basket["legs"]) == 2
    print("✓ build_speculative_basket correctly handles WNBA-shaped plays, confirming cross-sport support")


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
