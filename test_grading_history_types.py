"""Nov 27: Retrospective crashed saving NFL plays -- string player ids into Postgres' INTEGER column."""
import grading_history as GH


def test_values_fit_their_columns():
    assert GH._typed("player_id", "00-0036355") is None          # an NFL gsis id
    assert GH._typed("player_id", "2544") == 2544 and GH._typed("player_id", 2544.0) == 2544
    assert GH._typed("line", "24.5") == 24.5 and GH._typed("line", float("nan")) is None
    assert GH._typed("actual_value", "—") is None and GH._typed("hit", True) == 1
    assert GH._typed("player", "Josh Allen") == "Josh Allen" and GH._typed("rank", None) is None


def test_postgres_insert_gets_clean_values(monkeypatch):
    got = {}

    class Cur:
        def execute(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Con:
        def cursor(self, **k):
            return Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    from contextlib import contextmanager

    @contextmanager
    def conn():
        yield Con()
    import psycopg2.extras as PX
    monkeypatch.setattr(GH, "_pg_conn", conn)
    monkeypatch.setattr(PX, "execute_values", lambda cur, q, vals, page_size=0: got.setdefault("vals", vals))
    GH._pg_replace_day("2026-11-26", "NFL", [{"graded_at": "t", "slate_date": "2026-11-26", "sport": "NFL",
                                              "market": "Receptions", "player": "X", "player_id": "00-0036355",
                                              "line": 4.5, "hit": 1}])
    row = dict(zip(GH._FIELDS, got["vals"][0]))
    assert row["player_id"] is None and row["line"] == 4.5 and row["player"] == "X"
