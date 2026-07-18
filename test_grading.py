"""
test_grading.py — offline tests for grading.py, the shared sport-agnostic letter-grade/tier
logic used by Graded Picks and Retrospective across every sport on this platform.

    python test_grading.py     # or: pytest test_grading.py
"""

import grading


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
