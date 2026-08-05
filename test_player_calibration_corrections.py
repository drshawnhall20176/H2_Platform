"""
test_player_calibration_corrections.py — offline tests for player_calibration_corrections.py
(temp SQLite, no network).

    python test_player_calibration_corrections.py     # or: pytest test_player_calibration_corrections.py
"""

import os
import tempfile

import player_calibration_corrections as PCC


def _fit(player="Test Guy", n=25, weight=0.556, raw_gap=0.15, shrunk_gap=0.083):
    return {"player": player, "n": n, "weight": weight, "raw_gap": raw_gap, "shrunk_gap": shrunk_gap}


def test_record_fit_writes_a_row_and_latest_fit_reads_it_back():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "pcc.db")
        row_id = PCC.record_fit("MLB", 501, _fit(), min_n_used=20, db_path=db)
        assert row_id == 1
        latest = PCC.latest_fit("MLB", 501, db_path=db)
        assert latest is not None
        assert latest["player"] == "Test Guy" and latest["shrunk_gap"] == 0.083
        print("✓ record_fit writes a real row, latest_fit reads it back correctly")


def test_latest_fit_returns_none_when_nothing_recorded_yet():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "pcc.db")
        assert PCC.latest_fit("MLB", 501, db_path=db) is None
        print("✓ latest_fit returns None (an honest 'no real fit exists yet') for a player never fit")


def test_record_fit_is_append_only_not_replace():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "pcc.db")
        PCC.record_fit("MLB", 501, _fit(n=20), db_path=db)
        PCC.record_fit("MLB", 501, _fit(n=45), db_path=db)
        PCC.record_fit("MLB", 501, _fit(n=70), db_path=db)
        history = PCC.fit_history("MLB", 501, db_path=db)
        assert len(history) == 3, f"expected all 3 real fits to be kept as separate rows, got {len(history)}"
        assert [h["n"] for h in history] == [20, 45, 70]   # oldest first
        print("✓ record_fit is append-only — every real refit stays a separate, permanent audit row")


def test_latest_fit_returns_the_most_recent_one():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "pcc.db")
        PCC.record_fit("MLB", 501, _fit(shrunk_gap=0.05), db_path=db)
        PCC.record_fit("MLB", 501, _fit(shrunk_gap=0.09), db_path=db)   # the real, current one
        latest = PCC.latest_fit("MLB", 501, db_path=db)
        assert latest["shrunk_gap"] == 0.09
        print("✓ latest_fit returns the most recently recorded fit, not the first one ever made")


def test_different_players_dont_collide():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "pcc.db")
        PCC.record_fit("MLB", 501, _fit(player="Player A", shrunk_gap=0.10), db_path=db)
        PCC.record_fit("MLB", 502, _fit(player="Player B", shrunk_gap=-0.20), db_path=db)
        assert PCC.latest_fit("MLB", 501, db_path=db)["shrunk_gap"] == 0.10
        assert PCC.latest_fit("MLB", 502, db_path=db)["shrunk_gap"] == -0.20
        print("✓ separate players are stored and looked up independently, no cross-contamination")


def test_different_sports_dont_collide():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "pcc.db")
        PCC.record_fit("MLB", 501, _fit(shrunk_gap=0.10), db_path=db)
        PCC.record_fit("WNBA", 501, _fit(shrunk_gap=-0.20), db_path=db)   # same real player_id, different sport
        assert PCC.latest_fit("MLB", 501, db_path=db)["shrunk_gap"] == 0.10
        assert PCC.latest_fit("WNBA", 501, db_path=db)["shrunk_gap"] == -0.20
        print("✓ the same player_id in two different sports is stored and looked up independently")


def test_latest_fits_for_sport_returns_every_player_in_one_call():
    # THE real, necessary addition this module exists for -- a full slate needs every player's
    # own latest real correction in ONE query, not one query per player.
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "pcc.db")
        PCC.record_fit("MLB", 501, _fit(player="A", shrunk_gap=0.10), db_path=db)
        PCC.record_fit("MLB", 502, _fit(player="B", shrunk_gap=-0.05), db_path=db)
        PCC.record_fit("MLB", 503, _fit(player="C", shrunk_gap=0.20), db_path=db)
        all_fits = PCC.latest_fits_for_sport("MLB", db_path=db)
        assert set(all_fits.keys()) == {501, 502, 503}
        assert all_fits[501]["shrunk_gap"] == 0.10
        assert all_fits[503]["player"] == "C"
        print("✓ latest_fits_for_sport returns every real player's own latest fit in one call")


def test_latest_fits_for_sport_returns_only_the_most_recent_per_player():
    # Real proof this isn't just "every row" -- a player refit multiple times must show up
    # exactly once, with their real CURRENT correction, not their first or all of them.
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "pcc.db")
        PCC.record_fit("MLB", 501, _fit(shrunk_gap=0.05), db_path=db)
        PCC.record_fit("MLB", 501, _fit(shrunk_gap=0.05), db_path=db)
        PCC.record_fit("MLB", 501, _fit(shrunk_gap=0.15), db_path=db)   # the real, current one
        PCC.record_fit("MLB", 502, _fit(shrunk_gap=-0.10), db_path=db)
        all_fits = PCC.latest_fits_for_sport("MLB", db_path=db)
        assert len(all_fits) == 2, f"expected exactly 2 real players (deduped to their latest fit each), got {len(all_fits)}"
        assert all_fits[501]["shrunk_gap"] == 0.15
        print("✓ latest_fits_for_sport correctly dedupes to each real player's own most recent fit, not every historical row")


def test_latest_fits_for_sport_empty_when_nothing_recorded_yet():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "pcc.db")
        assert PCC.latest_fits_for_sport("MLB", db_path=db) == {}
        print("✓ latest_fits_for_sport returns a real, honest empty dict when no player has been fit yet")


def test_fit_history_narrows_to_one_player_when_asked():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "pcc.db")
        PCC.record_fit("MLB", 501, _fit(), db_path=db)
        PCC.record_fit("MLB", 502, _fit(), db_path=db)
        one = PCC.fit_history("MLB", player_id=501, db_path=db)
        assert len(one) == 1 and one[0]["player_id"] == 501
        print("✓ fit_history correctly narrows to one real player when asked")


def test_record_fit_stores_raw_gap_and_weight_for_audit():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "pcc.db")
        PCC.record_fit("MLB", 501, _fit(raw_gap=0.30, weight=0.556, shrunk_gap=0.167),
                       min_n_used=20, db_path=db)
        row = PCC.latest_fit("MLB", 501, db_path=db)
        assert row["raw_gap"] == 0.30 and row["weight"] == 0.556
        assert row["min_n_used"] == 20
        print("✓ record_fit persists the raw (unshrunk) gap and shrinkage weight too, not just the final applied correction — the real audit trail")


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
