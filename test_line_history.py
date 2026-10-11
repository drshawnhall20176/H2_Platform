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


def test_sport_index_reads_a_whole_sport_in_one_query_grouped_by_player_and_market():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "line_history.db")
        for player, price, when in (("A", -110, "2026-10-01T10:00:00"), ("A", -125, "2026-10-02T10:00:00"),
                                    ("B", +100, "2026-10-02T11:00:00")):
            LH.record_snapshot("NBA", player, "Points", "Over", 20.5, price, "fanduel", db_path=db, captured_at=when)
        LH.record_snapshot("NFL", "A", "Points", "Over", 20.5, -110, "fanduel", db_path=db, captured_at="2026-10-02T10:00:00")
        idx = LH.sport_index("NBA", db_path=db)
        assert set(idx) == {("A", "Points"), ("B", "Points")}                        # the NFL row is not in it
        assert [r["price"] for r in idx[("A", "Points")]] == [-110, -125]            # oldest first
        recent = LH.sport_index("NBA", since="2026-10-02", db_path=db)
        assert [r["price"] for r in recent[("A", "Points")]] == [-125] and ("B", "Points") in recent
        assert LH.sport_index("MLB", db_path=db) == {}


def test_the_cloud_table_is_created_once_per_process_not_once_per_query(monkeypatch):
    import sys
    import types
    log = []

    class Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            log.append(sql.strip().split()[0])

        def fetchall(self):
            return []

    class Con:
        def cursor(self, cursor_factory=None):
            return Cur()

        def commit(self):
            pass

        def close(self):
            pass
    pg = types.ModuleType("psycopg2")
    pg.connect = lambda dsn, **kw: Con()
    pg.extras = types.SimpleNamespace(RealDictCursor=object)
    monkeypatch.setitem(sys.modules, "psycopg2", pg)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", pg.extras)
    monkeypatch.setattr(LH, "USING_POSTGRES", True)
    monkeypatch.setattr(LH, "_DATABASE_URL", "postgres://u:p@h/db")
    monkeypatch.setattr(LH, "_PG_READY", False)
    for _ in range(3):
        assert LH.sport_index("NBA") == {}
    assert log.count("CREATE") == 1 and log.count("SELECT") == 3
