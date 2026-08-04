"""
test_backfill_grading_history.py — offline tests for backfill_grading_history.py's real logic.

No network, no real database — grading_history calls point at real temp SQLite files, never the
module-level default path. BBD.build_mlb_board/E.get_player_results are mocked at the module
level (the exact same real functions load_retro_mlb calls) so backfill_one_date's own real
sequencing (build board -> grade -> rank -> persist) is exercised directly, not reimplemented.

    python test_backfill_grading_history.py    # or: pytest test_backfill_grading_history.py
"""

import os
import tempfile
from unittest.mock import patch

import backfill_grading_history as BG
import grading_history as GH


def _play(market="Batter HR", side="Over", line=0.5, model_prob=0.35, player="P", player_id=1):
    return {"Market": market, "Side": side, "Line": line, "ModelProb": model_prob,
           "Conviction": 1.5, "Player": player, "PlayerId": player_id}


def test_real_recent_dates_produces_the_correct_window():
    dates = BG.real_recent_dates(10, end_date="2026-07-20")
    assert dates[0] == "2026-07-20"
    assert dates[-1] == "2026-07-11"
    assert len(dates) == 10
    print("✓ real_recent_dates produces the correct real N-day window, most recent first")


def test_real_recent_dates_defaults_to_yesterday_when_no_end_given():
    from datetime import datetime, timedelta, timezone
    dates = BG.real_recent_dates(1)
    expected_yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    assert dates == [expected_yesterday]
    print("✓ real_recent_dates defaults to ending yesterday — today's own games have no final results yet")


def test_backfill_one_date_grades_ranks_and_persists():
    # Real, exact, hand-verifiable construction: 2 real plays in the same market, ranked by
    # ModelProb, both graded and persisted with real rank data.
    plays = [_play(player="Low Conf", player_id=1, model_prob=0.30), _play(player="High Conf", player_id=2, model_prob=0.60)]
    results = {1: {"hr": 0}, 2: {"hr": 2}}

    with tempfile.TemporaryDirectory() as tmp:
        GH.DB_PATH = os.path.join(tmp, "gh.db")
        with patch("best_bets_data.build_mlb_board", return_value=([], [{"label": "A @ B"}], plays, {})), \
             patch("mlb_engine.get_player_results", return_value=results):
            n = BG.backfill_one_date("2026-07-18")

        assert n == 2
        history = GH.fetch_graded_plays("MLB", db_path=GH.DB_PATH)
        by_player = {r["Player"]: r for r in history}
        assert by_player["High Conf"]["Rank"] == 1   # real higher ModelProb -> real rank 1
        assert by_player["Low Conf"]["Rank"] == 2
        assert by_player["High Conf"]["OfTotal"] == 2
    print("✓ backfill_one_date grades, ranks, and persists real plays using the real shared pipeline")


def test_backfill_one_date_skips_a_real_off_day():
    with tempfile.TemporaryDirectory() as tmp:
        GH.DB_PATH = os.path.join(tmp, "gh.db")
        with patch("best_bets_data.build_mlb_board", return_value=([], [], [], {})):   # empty meta -- no real games
            n = BG.backfill_one_date("2026-07-18")
        assert n is None
        assert GH.fetch_graded_plays("MLB", db_path=GH.DB_PATH) == []
    print("✓ backfill_one_date honestly skips a real off-day (no games), doesn't error or fabricate a row")


def test_backfill_one_date_skips_when_no_real_results_yet():
    plays = [_play(player_id=1)]
    with tempfile.TemporaryDirectory() as tmp:
        GH.DB_PATH = os.path.join(tmp, "gh.db")
        with patch("best_bets_data.build_mlb_board", return_value=([], [{"label": "A @ B"}], plays, {})), \
             patch("mlb_engine.get_player_results", return_value={}):   # real games exist, no real results yet
            n = BG.backfill_one_date("2026-07-18")
        assert n is None
        assert GH.fetch_graded_plays("MLB", db_path=GH.DB_PATH) == []
    print("✓ backfill_one_date honestly skips a real date with no final results yet, doesn't fabricate a grade")


def test_backfill_one_date_is_idempotent_across_repeated_runs():
    # Real, confirmed reuse of grading_history.record_graded_slate's own real REPLACE semantics
    # -- re-running the backfill for the same real date must not duplicate rows.
    plays = [_play(player_id=1)]
    results = {1: {"hr": 1}}
    with tempfile.TemporaryDirectory() as tmp:
        GH.DB_PATH = os.path.join(tmp, "gh.db")
        with patch("best_bets_data.build_mlb_board", return_value=([], [{"label": "A @ B"}], plays, {})), \
             patch("mlb_engine.get_player_results", return_value=results):
            BG.backfill_one_date("2026-07-18")
            BG.backfill_one_date("2026-07-18")
            BG.backfill_one_date("2026-07-18")
        history = GH.fetch_graded_plays("MLB", db_path=GH.DB_PATH)
        assert len(history) == 1, f"expected 1 real row after 3 identical backfill runs, got {len(history)}"
    print("✓ backfill_one_date is idempotent — re-running the same real date replaces, never duplicates")


def test_backfill_workflow_yaml_is_valid_and_calls_the_real_script():
    # No existing workflow file in this repo has test coverage (confirmed: none of refresh-
    # calibration.yml/refresh-statcast.yml/etc. are referenced anywhere in this test suite) --
    # this is a real, new, lightweight addition: parse the YAML for real syntax validity, and
    # confirm it actually calls the real script this file tests, not a typo'd path.
    import yaml
    from pathlib import Path
    workflow_path = Path(__file__).parent / ".github" / "workflows" / "backfill-grading-history.yml"
    assert workflow_path.exists()
    parsed = yaml.safe_load(workflow_path.read_text())
    assert parsed is not None, "the workflow file must be real, valid YAML"
    assert "workflow_dispatch" in parsed.get(True, parsed.get("on", {})), (
        "must be manually triggerable -- workflow_dispatch, no schedule, see the file's own comment for why")
    assert "cron" not in workflow_path.read_text(), (
        "this must stay manual-trigger-only, not scheduled, like refresh-calibration.yml is")
    assert "backfill_grading_history.py" in workflow_path.read_text()
    print("✓ backfill-grading-history.yml is valid YAML, manual-trigger-only, and calls the real script")


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
