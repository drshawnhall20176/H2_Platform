"""
test_grading_history.py — offline tests for grading_history.py (temp SQLite, no network).

    python test_grading_history.py     # or: pytest test_grading_history.py
"""

import os
import tempfile
from pathlib import Path

import grading_history as GH
import retro as R


def _play(market="Batter HR", side="Over", line=0.5, model_prob=0.35, conviction=1.9,
         player="Test Slugger", player_id=501, hit=True, actual=1):
    return {"Market": market, "Side": side, "Line": line, "ModelProb": model_prob,
           "Conviction": conviction, "Player": player, "PlayerId": player_id,
           "Hit": hit, "Actual": actual}


def test_record_graded_slate_writes_rows():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "grading_history.db")
        n = GH.record_graded_slate("2026-07-18", "MLB", [_play()], db_path=db)
        assert n == 1
        rows = GH.fetch_graded_plays("MLB", db_path=db)
        assert len(rows) == 1
        assert rows[0]["Player"] == "Test Slugger" and rows[0]["Market"] == "Batter HR"
        print("✓ record_graded_slate writes a real row, fetch_graded_plays reads it back")


def test_hit_true_false_none_round_trips_exactly():
    # The stored column is an integer (SQLite/Postgres both need a real type for it), but every
    # caller (retro._calibration, retro.player_calibration, grade_slate's own output) works in
    # real True/False/None -- this is the one place that translation must be exactly right in
    # both directions, or a real "no result yet" (None) silently becomes a real "miss" (False).
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "grading_history.db")
        plays = [_play(player="Hit Guy", player_id=1, hit=True),
                 _play(player="Miss Guy", player_id=2, hit=False),
                 _play(player="No Result Guy", player_id=3, hit=None)]
        GH.record_graded_slate("2026-07-18", "MLB", plays, db_path=db)
        rows = {r["Player"]: r["Hit"] for r in GH.fetch_graded_plays("MLB", db_path=db)}
        assert rows["Hit Guy"] is True
        assert rows["Miss Guy"] is False
        assert rows["No Result Guy"] is None
        print("✓ Hit round-trips exactly as True/False/None through storage, no state collapses into another")


def test_record_graded_slate_replaces_existing_day_not_appends():
    # THE core idempotency behavior this module exists for: Command Center/Retrospective
    # recompute yesterday's grading fresh on every visit, with nothing stopping a person from
    # visiting the same date's grading five times in a day. Without real replace-on-write
    # semantics, every one of those visits would silently multiply the same real outcomes,
    # corrupting every calibration count built on top with no error anywhere to reveal it.
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "grading_history.db")
        GH.record_graded_slate("2026-07-18", "MLB", [_play(player="A", player_id=1)], db_path=db)
        GH.record_graded_slate("2026-07-18", "MLB", [_play(player="A", player_id=1)], db_path=db)
        GH.record_graded_slate("2026-07-18", "MLB", [_play(player="A", player_id=1)], db_path=db)
        rows = GH.fetch_graded_plays("MLB", db_path=db)
        assert len(rows) == 1, f"expected 1 row after 3 identical re-gradings of the same day, got {len(rows)}"
        print("✓ record_graded_slate replaces (not appends to) an existing day — revisiting the same date repeatedly doesn't multiply rows")


def test_record_graded_slate_second_call_reflects_fresh_data_not_a_merge():
    # A later re-grading might have genuinely different plays (a late-added market, a corrected
    # result) -- the SECOND call's data should be what's actually stored, not a union of both.
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "grading_history.db")
        GH.record_graded_slate("2026-07-18", "MLB",
                               [_play(player="A", player_id=1), _play(player="B", player_id=2)],
                               db_path=db)
        GH.record_graded_slate("2026-07-18", "MLB", [_play(player="C", player_id=3)], db_path=db)
        players = {r["Player"] for r in GH.fetch_graded_plays("MLB", db_path=db)}
        assert players == {"C"}, f"expected only the second call's data, got {players}"
        print("✓ a second record_graded_slate call for the same day fully replaces the first, not merges with it")


def test_record_graded_slate_different_sports_dont_collide():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "grading_history.db")
        GH.record_graded_slate("2026-07-18", "MLB", [_play(player="MLB Guy", player_id=1)], db_path=db)
        GH.record_graded_slate("2026-07-18", "WNBA", [_play(player="WNBA Guy", player_id=2)], db_path=db)
        mlb_rows = GH.fetch_graded_plays("MLB", db_path=db)
        wnba_rows = GH.fetch_graded_plays("WNBA", db_path=db)
        assert len(mlb_rows) == 1 and mlb_rows[0]["Player"] == "MLB Guy"
        assert len(wnba_rows) == 1 and wnba_rows[0]["Player"] == "WNBA Guy"
        print("✓ the same slate_date for two different sports doesn't collide — replacement is scoped to (slate_date, sport)")


def test_record_graded_slate_missing_fields_dont_crash():
    # A real, honest partial play dict (a sport/market combination missing some optional field)
    # must store safely as NULL, not raise.
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "grading_history.db")
        sparse = {"Market": "Points", "Hit": True}   # missing Side, Line, ModelProb, Player, etc.
        n = GH.record_graded_slate("2026-07-18", "WNBA", [sparse], db_path=db)
        assert n == 1
        row = GH.fetch_graded_plays("WNBA", db_path=db)[0]
        assert row["Market"] == "Points" and row["Hit"] is True
        assert row["Player"] is None and row["Line"] is None
        print("✓ a play dict missing optional fields stores safely as NULL instead of raising")


def test_fetch_graded_plays_filters_by_market():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "grading_history.db")
        GH.record_graded_slate("2026-07-18", "MLB",
                               [_play(market="Batter HR", player="A", player_id=1),
                                _play(market="Pitcher Strikeouts", player="B", player_id=2)],
                               db_path=db)
        hr_only = GH.fetch_graded_plays("MLB", market="Batter HR", db_path=db)
        assert len(hr_only) == 1 and hr_only[0]["Player"] == "A"
        print("✓ fetch_graded_plays correctly narrows to one market when asked")


def test_fetch_graded_plays_filters_by_since_date():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "grading_history.db")
        GH.record_graded_slate("2026-07-01", "MLB", [_play(player="Old", player_id=1)], db_path=db)
        GH.record_graded_slate("2026-07-20", "MLB", [_play(player="New", player_id=2)], db_path=db)
        recent = GH.fetch_graded_plays("MLB", since_date="2026-07-15", db_path=db)
        assert len(recent) == 1 and recent[0]["Player"] == "New"
        print("✓ fetch_graded_plays correctly narrows to slates on/after since_date")


def test_fetch_graded_plays_oldest_first():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "grading_history.db")
        GH.record_graded_slate("2026-07-20", "MLB", [_play(player="Later", player_id=2)], db_path=db)
        GH.record_graded_slate("2026-07-01", "MLB", [_play(player="Earlier", player_id=1)], db_path=db)
        rows = GH.fetch_graded_plays("MLB", db_path=db)
        assert [r["Player"] for r in rows] == ["Earlier", "Later"]
        print("✓ fetch_graded_plays returns rows oldest slate first, regardless of write order")


def test_fetch_graded_plays_feeds_retro_calibration_directly():
    # THE real design goal, proven end to end, not just asserted: this module does no statistical
    # work of its own -- real accumulated history has to be usable by retro._calibration with
    # ZERO translation, or the whole point of keeping storage and grading logic separate falls
    # apart. Builds a real multi-day history with a genuine, deliberate miscalibration (every
    # ~40% play hits ~80% of the time) and confirms _calibration surfaces exactly that gap when
    # run directly against fetch_graded_plays' own output.
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "grading_history.db")
        day1 = [_play(player=f"P{i}", player_id=i, model_prob=0.42, hit=(i % 5 != 0)) for i in range(10)]
        day2 = [_play(player=f"Q{i}", player_id=100 + i, model_prob=0.44, hit=(i % 5 != 0)) for i in range(10)]
        GH.record_graded_slate("2026-07-18", "MLB", day1, db_path=db)
        GH.record_graded_slate("2026-07-19", "MLB", day2, db_path=db)

        history = GH.fetch_graded_plays("MLB", db_path=db)
        assert len(history) == 20
        cal = R._calibration(history, n_bins=5)   # zero translation -- real proof of the design
        bucket = next(c for c in cal if c["lo"] <= 0.42 < c["hi"])
        assert bucket["n"] == 20
        assert bucket["predicted"] < 0.45         # the model said ~43%
        assert bucket["actual"] > 0.75             # but these actually hit ~80% of the time
        print("✓ fetch_graded_plays' real output feeds directly into retro._calibration with zero "
             "translation, and a genuine miscalibration across two persisted days is correctly surfaced")


def test_fetch_graded_plays_feeds_player_calibration_directly():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "grading_history.db")
        # Same player, same real market, across two different days -- exactly the cross-day
        # pooling this module exists to make possible.
        GH.record_graded_slate("2026-07-18", "MLB",
                               [_play(player="Curtis M.", player_id=77, model_prob=0.55, hit=False)],
                               db_path=db)
        GH.record_graded_slate("2026-07-19", "MLB",
                               [_play(player="Curtis M.", player_id=77, model_prob=0.55, hit=False)],
                               db_path=db)
        history = GH.fetch_graded_plays("MLB", db_path=db)
        gaps = R.player_calibration(history, min_plays=2)
        curtis = next(g for g in gaps if g["player_id"] == 77)
        assert curtis["n"] == 2
        assert curtis["actual_hit_rate"] == 0.0
        print("✓ fetch_graded_plays' real output feeds directly into retro.player_calibration too, pooled across real persisted days")


def test_retrospective_persists_both_mlb_and_generic_branches():
    # Regression guard confirming the gate is actually WIRED IN, matching the same class of check
    # already done for statcast_data.load_cached and weather.load_slate_weather -- record_graded_
    # slate could be perfectly correct and simply never called from the one page it was built for.
    src = (Path(__file__).parent / "views" / "16_#L01f50d_Retrospective.py").read_text()
    assert src.count("GH.record_graded_slate(") == 2, (
        "expected exactly 2 calls -- one in the MLB branch, one in the generic/WNBA branch")
    print("✓ Retrospective calls GH.record_graded_slate in both the MLB and generic branches")


def test_retrospective_persistence_call_is_not_inside_a_cached_function():
    # THE real, confirmed bug class this specifically guards against, already documented in this
    # exact codebase for a different function (best_bets_data.ensure_mlb_offers_session_state's
    # own docstring): a side effect (a real DB write, here) placed INSIDE an @st.cache_data-
    # wrapped function only fires on an actual cache MISS -- a second visit to the same date
    # within the 600s TTL would silently skip persisting at all, with no error anywhere to reveal
    # it. Confirmed directly by source position: the call must appear AFTER load_retro_mlb/load_
    # retro_generic's own function bodies end (i.e. in top-level page code), not inside either one.
    src = (Path(__file__).parent / "views" / "16_#L01f50d_Retrospective.py").read_text()
    generic_fn_end = src.index("if _active.key ==")     # both loaders' bodies end before this point
    calls = [i for i in range(len(src)) if src.startswith("GH.record_graded_slate(", i)]
    assert len(calls) == 2
    assert all(c > generic_fn_end for c in calls), (
        "GH.record_graded_slate must be called from top-level page code, never from inside "
        "load_retro_mlb or load_retro_generic (both @st.cache_data-wrapped)")
    print("✓ GH.record_graded_slate is called from genuinely uncached top-level page code, "
         "not from inside either @st.cache_data-wrapped loader")


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
