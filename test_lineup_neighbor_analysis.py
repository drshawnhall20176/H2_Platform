"""
test_lineup_neighbor_analysis.py — offline tests for lineup_neighbor_analysis.py (mocked
grading_history and mlb_engine calls, no network, no real database).

    python test_lineup_neighbor_analysis.py     # or: pytest test_lineup_neighbor_analysis.py
"""

from unittest.mock import patch

import lineup_neighbor_analysis as L


def _play(player_id=1, slate_date="2026-07-14", hit=True, market="Batter Total Hits"):
    return {"PlayerId": player_id, "SlateDate": slate_date, "Hit": hit, "Market": market,
           "Player": "Test Player"}


def test_neighbor_had_a_big_game_true_on_real_hr():
    assert L._neighbor_had_a_big_game({"h": 0, "hr": 1}, big_game_hits=2) is True
    print("✓ a real HR alone counts as a real big game, even with zero other hits")


def test_neighbor_had_a_big_game_true_on_real_hit_threshold():
    assert L._neighbor_had_a_big_game({"h": 2, "hr": 0}, big_game_hits=2) is True
    assert L._neighbor_had_a_big_game({"h": 1, "hr": 0}, big_game_hits=2) is False
    print("✓ _neighbor_had_a_big_game correctly applies the real hit threshold")


def test_neighbor_had_a_big_game_none_when_no_neighbor():
    assert L._neighbor_had_a_big_game(None, big_game_hits=2) is None
    print("✓ _neighbor_had_a_big_game honestly returns None when there's no real neighbor to check")


def test_run_analysis_classifies_hot_and_cold_correctly():
    plays = [_play(player_id=1, hit=True), _play(player_id=2, hit=False)]

    with patch.object(L.GH, "fetch_graded_plays", return_value=plays), \
         patch.object(L.E, "find_hitter_game_pk", side_effect=lambda pid, d: 100 + pid), \
         patch.object(L.E, "get_lineup_neighbor_result", side_effect=lambda pid, gp:
                     {"slot": 3, "neighbor_above": {"h": 2, "hr": 0}, "neighbor_below": None}
                     if pid == 1 else
                     {"slot": 3, "neighbor_above": {"h": 0, "hr": 0}, "neighbor_below": None}):
        result = L.run_analysis(markets=["Batter Total Hits"])

    assert result["hot_neighbor"]["n"] == 1 and result["hot_neighbor"]["hit_rate"] == 1.0
    assert result["cold_neighbor"]["n"] == 1 and result["cold_neighbor"]["hit_rate"] == 0.0
    print("✓ run_analysis correctly classifies plays into hot/cold neighbor buckets and computes real hit rates")


def test_run_analysis_dedupes_gamepk_lookups_per_player_date():
    # Same real player, same real date, appearing across TWO different real markets -- must
    # only trigger ONE real find_hitter_game_pk call, not two.
    plays_hits = [_play(player_id=1, slate_date="2026-07-14", market="Batter Total Hits")]
    plays_hr = [_play(player_id=1, slate_date="2026-07-14", market="Batter HR")]

    def fake_fetch(sport, market=None):
        return plays_hits if market == "Batter Total Hits" else plays_hr

    calls = []

    def fake_find_game_pk(pid, date):
        calls.append((pid, date))
        return 100

    with patch.object(L.GH, "fetch_graded_plays", side_effect=fake_fetch), \
         patch.object(L.E, "find_hitter_game_pk", side_effect=fake_find_game_pk), \
         patch.object(L.E, "get_lineup_neighbor_result",
                      return_value={"slot": 3, "neighbor_above": {"h": 2, "hr": 0}, "neighbor_below": None}):
        L.run_analysis(markets=["Batter Total Hits", "Batter HR"])

    assert len(calls) == 1, f"expected exactly one real find_hitter_game_pk call (deduped), got {len(calls)}: {calls}"
    print("✓ run_analysis dedupes find_hitter_game_pk calls for the same real player+date across markets")


def test_run_analysis_dedupes_neighbor_lookups_per_player_gamepk():
    plays = [_play(player_id=1, slate_date="2026-07-14", market="Batter Total Hits"),
            _play(player_id=1, slate_date="2026-07-15", market="Batter HR")]   # different real dates -> different gamePk

    def fake_fetch(sport, market=None):
        return [p for p in plays if p["Market"] == market]

    calls = []

    def fake_neighbor(pid, gp):
        calls.append((pid, gp))
        return {"slot": 3, "neighbor_above": {"h": 2, "hr": 0}, "neighbor_below": None}

    with patch.object(L.GH, "fetch_graded_plays", side_effect=fake_fetch), \
         patch.object(L.E, "find_hitter_game_pk", side_effect=lambda pid, d: 100 if d == "2026-07-14" else 200), \
         patch.object(L.E, "get_lineup_neighbor_result", side_effect=fake_neighbor):
        L.run_analysis(markets=["Batter Total Hits", "Batter HR"])

    assert len(calls) == 2, f"expected two real neighbor lookups (different games), got {len(calls)}: {calls}"
    print("✓ run_analysis correctly makes separate neighbor lookups for genuinely different real games")


def test_run_analysis_honestly_counts_plays_with_no_findable_game():
    plays = [_play(player_id=1)]
    with patch.object(L.GH, "fetch_graded_plays", return_value=plays), \
         patch.object(L.E, "find_hitter_game_pk", return_value=None):   # a real off day / DFA / fetch gap
        result = L.run_analysis(markets=["Batter Total Hits"])
    assert result["skipped_no_game"] == 1
    assert result["hot_neighbor"]["n"] == 0 and result["cold_neighbor"]["n"] == 0
    print("✓ run_analysis honestly counts (not silently drops) plays where no real game could be found")


def test_run_analysis_honestly_counts_plays_with_no_real_neighbor_at_all():
    # A real leadoff hitter with no one below him tracked, or a real fetch gap -- either way,
    # this must be counted separately from a genuine hot/cold classification, not folded into
    # "cold" by default (that would misrepresent a real absence of data as a real negative result).
    plays = [_play(player_id=1)]
    with patch.object(L.GH, "fetch_graded_plays", return_value=plays), \
         patch.object(L.E, "find_hitter_game_pk", return_value=100), \
         patch.object(L.E, "get_lineup_neighbor_result",
                      return_value={"slot": 1, "neighbor_above": None, "neighbor_below": None}):
        result = L.run_analysis(markets=["Batter Total Hits"])
    assert result["no_neighbor_data"] == 1
    assert result["hot_neighbor"]["n"] == 0 and result["cold_neighbor"]["n"] == 0
    print("✓ run_analysis honestly counts plays with genuinely no real neighbor data, never folding them into 'cold' by default")


def test_run_analysis_hot_wins_if_either_real_neighbor_is_hot():
    # Deezy's own framing was about being NEAR a hot hitter generally (either side) -- pooling
    # both real neighbors, not requiring both to agree.
    plays = [_play(player_id=1, hit=True)]
    with patch.object(L.GH, "fetch_graded_plays", return_value=plays), \
         patch.object(L.E, "find_hitter_game_pk", return_value=100), \
         patch.object(L.E, "get_lineup_neighbor_result",
                      return_value={"slot": 5, "neighbor_above": {"h": 0, "hr": 0},
                                   "neighbor_below": {"h": 0, "hr": 1}}):   # only the BELOW neighbor is hot
        result = L.run_analysis(markets=["Batter Total Hits"])
    assert result["hot_neighbor"]["n"] == 1
    print("✓ run_analysis correctly classifies as hot when EITHER real adjacent neighbor had a big game")


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
