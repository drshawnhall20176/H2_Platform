"""
test_line_history.py — offline tests for line_history.py (temp SQLite, no network).

    python test_line_history.py     # or: pytest test_line_history.py
"""

import os
import tempfile

import line_history as LH


def test_record_snapshot_writes_first_observation():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "line_history.db")
        wrote = LH.record_snapshot(sport="WNBA", player="A. Player", market="Points", side="over",
                                   line=12.5, price=-110, book="fanduel", game="Team A @ Team B",
                                   db_path=db)
        assert wrote is True
        series = LH.line_series("WNBA", "A. Player", "Points", db_path=db)
        assert len(series) == 1
        assert series[0]["line"] == 12.5 and series[0]["price"] == -110
        print("✓ record_snapshot writes the first observation for a new (sport, player, market, side, book)")


def test_record_snapshot_skips_unchanged_line_and_price():
    # THE core behavior this module exists for: an unchanged (line, price) at the next capture
    # must NOT add a redundant row — without this, a script run several times a day would mostly
    # write identical repeats.
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "line_history.db")
        LH.record_snapshot(sport="WNBA", player="A. Player", market="Points", side="over",
                           line=12.5, price=-110, book="fanduel", db_path=db)
        wrote_again = LH.record_snapshot(sport="WNBA", player="A. Player", market="Points",
                                         side="over", line=12.5, price=-110, book="fanduel", db_path=db)
        assert wrote_again is False
        assert len(LH.line_series("WNBA", "A. Player", "Points", db_path=db)) == 1
        print("✓ record_snapshot correctly skips an unchanged (line, price) — no redundant row written")


def test_record_snapshot_writes_new_row_when_line_moves():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "line_history.db")
        LH.record_snapshot(sport="WNBA", player="A. Player", market="Points", side="over",
                           line=12.5, price=-110, book="fanduel", db_path=db)
        wrote = LH.record_snapshot(sport="WNBA", player="A. Player", market="Points", side="over",
                                   line=13.5, price=-115, book="fanduel", db_path=db)   # line moved
        assert wrote is True
        series = LH.line_series("WNBA", "A. Player", "Points", db_path=db)
        assert len(series) == 2
        assert [s["line"] for s in series] == [12.5, 13.5]   # oldest first, real movement captured
        print("✓ record_snapshot writes a new row when the line genuinely moves, oldest-first order preserved")


def test_record_snapshot_writes_new_row_when_only_price_moves():
    # A line staying the SAME (e.g. still 12.5) but the PRICE shortening/lengthening (e.g. -110 ->
    # -120, the book adjusting its juice without moving the number) is still real movement worth
    # capturing — this must not be treated as "unchanged" just because the line itself is identical.
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "line_history.db")
        LH.record_snapshot(sport="WNBA", player="A. Player", market="Points", side="over",
                           line=12.5, price=-110, book="fanduel", db_path=db)
        wrote = LH.record_snapshot(sport="WNBA", player="A. Player", market="Points", side="over",
                                   line=12.5, price=-120, book="fanduel", db_path=db)
        assert wrote is True
        assert len(LH.line_series("WNBA", "A. Player", "Points", db_path=db)) == 2
        print("✓ record_snapshot treats a price-only change as real movement too, not just line changes")


def test_different_books_tracked_independently():
    # The same player/market/line at two DIFFERENT books are separate series — a line moving at
    # FanDuel doesn't count as "the same" observation as DraftKings' own price for the same prop.
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "line_history.db")
        LH.record_snapshot(sport="WNBA", player="A. Player", market="Points", side="over",
                           line=12.5, price=-110, book="fanduel", db_path=db)
        wrote = LH.record_snapshot(sport="WNBA", player="A. Player", market="Points", side="over",
                                   line=12.5, price=-110, book="draftkings", db_path=db)
        assert wrote is True   # different book -> not a duplicate, even with identical line/price
        assert len(LH.line_series("WNBA", "A. Player", "Points", db_path=db)) == 2
        fd_only = LH.line_series("WNBA", "A. Player", "Points", book="fanduel", db_path=db)
        assert len(fd_only) == 1 and fd_only[0]["book"] == "fanduel"
        print("✓ different books are tracked as independent series, and line_series can narrow to one")


def test_different_sides_tracked_independently():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "line_history.db")
        LH.record_snapshot(sport="WNBA", player="A. Player", market="Points", side="over",
                           line=12.5, price=-110, book="fanduel", db_path=db)
        wrote = LH.record_snapshot(sport="WNBA", player="A. Player", market="Points", side="under",
                                   line=12.5, price=-110, book="fanduel", db_path=db)
        assert wrote is True   # different side -> not a duplicate
        assert len(LH.line_series("WNBA", "A. Player", "Points", db_path=db)) == 2
        under_only = LH.line_series("WNBA", "A. Player", "Points", side="under", db_path=db)
        assert len(under_only) == 1 and under_only[0]["side"] == "under"


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
