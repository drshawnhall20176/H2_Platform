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
