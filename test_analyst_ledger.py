"""analyst_ledger.py — calls are locked at first publication, never back-dated, and graded with retro's own rules."""
from datetime import datetime, timedelta, timezone

import pytest

import analyst as A
import analyst_ledger as AL

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=timezone.utc)
FUTURE = "2026-10-09T00:15:00Z"          # 8:15 PM ET that evening
PAST = "2026-10-08T12:00:00Z"            # already kicked off at NOW


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "ledger.db")


def call(player="Pat Player", pid=11, date="2026-10-08", game_date=FUTURE, line=240.5, side="Over", market="Pass Yards", **kw):
    c = {"key": f"k-{player}", "sport": "NFL", "date": date, "player": player, "player_id": pid, "team": "DAL", "game": "TB @ DAL",
         "game_date": game_date, "market": market, "side": side, "line": line, "model_prob": 0.62, "conviction": 1.3,
         "price": -115, "price_book": "draftkings", "why": "w", "score": 1.7, "gem": True, "chalk": False,
         "cautions": ["c1"], "angles": [{"angle": "market_gap"}, {"angle": "team_surge"}]}
    c.update(kw)
    return c


def test_a_call_is_locked_at_first_publication_and_never_rewritten(db):
    assert AL.record_calls([call()], "2026-10-08", NOW, db) == 1
    moved = call(line=250.5, model_prob=0.9, angles=[{"angle": "form_run"}])
    assert AL.record_calls([moved, call()], "2026-10-08", NOW, db) == 0
    (row,) = AL.fetch_calls(db_path=db)
    assert row["line"] == 240.5 and row["model_prob"] == 0.62 and row["angles"] == ["market_gap", "team_surge"]
    assert row["gem"] is True and row["cautions"] == ["c1"] and row["date"] == "2026-10-08" and row["player_id"] == "11"


def test_the_other_side_of_a_market_or_another_day_is_a_separate_call(db):
    AL.record_calls([call(), call(side="Under"), call(date="2026-10-09")], "2026-10-08", NOW, db)
    assert len(AL.fetch_calls(db_path=db)) == 3


def test_past_dates_and_games_that_have_started_are_never_logged(db):
    stale = call(date="2026-10-07")
    started = call(player="Late", game_date=PAST)
    bare = call(player="Bare", game_date="2026-10-08")              # no kickoff clock: can't be checked, so it is allowed today
    assert AL.record_calls([stale, started, bare], "2026-10-08", NOW, db) == 1
    assert [r["player"] for r in AL.fetch_calls(db_path=db)] == ["Bare"]


def test_fetch_filters_by_sport_date_and_settled(db):
    AL.record_calls([call(), call(player="B", pid=12, date="2026-10-09")], "2026-10-08", NOW, db)
    assert len(AL.fetch_calls(sport="NFL", since="2026-10-09", db_path=db)) == 1
    assert AL.fetch_calls(sport="NBA", db_path=db) == []
    assert AL.fetch_calls(settled_only=True, db_path=db) == []


def test_settling_grades_with_the_platforms_own_rules_and_voids_a_player_who_did_not_play(db):
    AL.record_calls([call(), call(player="Miss", pid=12), call(player="Out", pid=13), call(player="Under", pid=14, side="Under")],
                    "2026-10-08", NOW, db)
    results = {11: {"passing_yards": 300}, 12: {"passing_yards": 100}, "14": {"passing_yards": 100}}
    out = AL.settle_day("NFL", "2026-10-08", results, db, NOW)
    assert out == {"settled": 4, "hits": 2, "voids": 1}
    got = {r["player"]: r for r in AL.fetch_calls(db_path=db)}
    assert got["Pat Player"]["hit"] == 1 and got["Pat Player"]["actual"] == 300
    assert got["Miss"]["hit"] == 0 and got["Under"]["hit"] == 1
    assert got["Out"]["hit"] is None and got["Out"]["settled_at"]                     # void, closed
    assert {r["player"] for r in AL.fetch_calls(settled_only=True, db_path=db)} == {"Pat Player", "Miss", "Under"}


def test_empty_results_mean_the_data_is_not_in_so_nothing_is_touched(db):
    AL.record_calls([call()], "2026-10-08", NOW, db)
    assert AL.settle_day("NFL", "2026-10-08", {}, db, NOW) == {"settled": 0, "hits": 0, "voids": 0}
    assert AL.unsettled_dates("NFL", "2026-10-09", db) == ["2026-10-08"]


def test_settling_is_idempotent_and_closes_the_day(db):
    AL.record_calls([call()], "2026-10-08", NOW, db)
    AL.settle_day("NFL", "2026-10-08", {11: {"passing_yards": 100}}, db, NOW)
    again = AL.settle_day("NFL", "2026-10-08", {11: {"passing_yards": 999}}, db, NOW)
    assert again["settled"] == 0
    assert AL.fetch_calls(db_path=db)[0]["hit"] == 0                                    # first verdict stands
    assert AL.unsettled_dates("NFL", "2026-10-09", db) == []
    assert AL.unsettled_dates("NFL", "2026-10-08", db) == []                            # only days BEFORE the cut-off


def test_ledger_rows_feed_the_scoreboard_directly(db):
    AL.record_calls([call()], "2026-10-08", NOW, db)
    AL.settle_day("NFL", "2026-10-08", {11: {"passing_yards": 300}}, db, NOW)
    board = {r["angle"]: r for r in A.scoreboard(AL.fetch_calls(settled_only=True, db_path=db))}
    assert board["ALL"]["n"] == 1 and board["market_gap"]["hits"] == 1 and board["gem"]["n"] == 1 and board["form_run"]["n"] == 0


# ------------------------------------------------- pre-game marks (Build 232)
def _posted(**kw):
    return call(book_state="posted", **kw)


def test_marks_record_the_latest_pregame_line_and_price_without_touching_the_lock(db):
    AL.record_calls([call()], "2026-10-08", NOW, db)
    later = NOW + timedelta(hours=2)
    assert AL.mark_calls([_posted(price=-135)], "2026-10-08", later, db) == 1
    (row,) = AL.fetch_calls(db_path=db)
    assert row["last_line"] == 240.5 and row["last_price"] == -135 and row["marked_at"] == later.isoformat(timespec="seconds")
    assert row["price"] == -115 and row["line"] == 240.5 and row["model_prob"] == 0.62          # the lock is untouched
    AL.mark_calls([_posted(price=-150)], "2026-10-08", later, db)                              # the newest mark replaces the last
    assert AL.fetch_calls(db_path=db)[0]["last_price"] == -150


def test_a_moved_line_is_marked_at_the_nearest_posted_line_with_no_price(db):
    AL.record_calls([call()], "2026-10-08", NOW, db)
    c = call(book_state="other_line", book_lines=["238.5", "250.5"], price=-110)               # a stale price must not be carried over
    assert AL.mark_calls([c], "2026-10-08", NOW, db) == 1
    row = AL.fetch_calls(db_path=db)[0]
    assert row["last_line"] == 238.5 and row["last_price"] is None


def test_marks_only_apply_to_open_pregame_calls_at_the_same_book(db):
    AL.record_calls([call()], "2026-10-08", NOW, db)
    assert AL.mark_calls([_posted(game_date=PAST)], "2026-10-08", NOW, db) == 0                # the game has started
    assert AL.mark_calls([_posted(price_book="fanduel")], "2026-10-08", NOW, db) == 0          # a different book's price
    assert AL.mark_calls([call(book_state="not_posted")], "2026-10-08", NOW, db) == 0          # pulled: nothing to mark
    assert AL.mark_calls([_posted(player="Never Locked")], "2026-10-08", NOW, db) == 0         # not in the ledger
    assert AL.fetch_calls(db_path=db)[0]["last_line"] is None
    AL.settle_day("NFL", "2026-10-08", {"11": {"passing_yards": 300}}, db, NOW)
    assert AL.mark_calls([_posted()], "2026-10-08", NOW, db) == 0                              # graded rows are frozen


def test_an_existing_database_without_the_mark_columns_is_upgraded(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE analyst_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, logged_at TEXT NOT NULL, call_date TEXT NOT NULL, "
                "sport TEXT NOT NULL, game TEXT, game_date TEXT, player TEXT NOT NULL, player_id TEXT, team TEXT, market TEXT NOT NULL, "
                "side TEXT NOT NULL, line REAL, model_prob REAL, conviction REAL, price REAL, price_book TEXT, angles TEXT, cautions TEXT, "
                "score REAL, gem INTEGER, chalk INTEGER, why TEXT, hit INTEGER, actual REAL, settled_at TEXT)")
    con.execute("INSERT INTO analyst_calls (logged_at, call_date, sport, player, market, side, line, price_book) "
                "VALUES ('x','2026-10-08','NFL','Old Timer','Pass Yards','Over',200.5,'draftkings')")
    con.commit()
    con.close()
    rows = AL.fetch_calls(db_path=path)
    assert rows[0]["player"] == "Old Timer" and rows[0]["last_line"] is None
    assert AL.mark_calls([call(player="Old Timer", line=200.5, book_state="posted", price=-110)], "2026-10-08", NOW, path) == 1
    assert AL.fetch_calls(db_path=path)[0]["last_price"] == -110


# ------------------------------------------------- published card + fingerprint (Build 234)
def test_publishing_stamps_only_ledger_rows_once_and_changes_nothing_else(db):
    AL.record_calls([call(), call(player="Other Guy", pid=12)], "2026-10-08", NOW, db)
    first = NOW + timedelta(hours=1)
    assert AL.mark_published([call(), call(player="Never Locked")], first, db) == 1
    rows = {r["player"]: r for r in AL.fetch_calls(db_path=db)}
    assert rows["Pat Player"]["published_at"] == first.isoformat(timespec="seconds") and rows["Other Guy"]["published_at"] is None
    assert rows["Pat Player"]["line"] == 240.5 and rows["Pat Player"]["model_prob"] == 0.62          # the lock is untouched
    assert AL.mark_published([call()], NOW + timedelta(hours=5), db) == 0                              # the first publication time stands
    assert AL.fetch_calls(db_path=db)[0]["published_at"] == first.isoformat(timespec="seconds")


def _fp_rows():
    return [{"logged_at": "2026-10-08T18:00:00+00:00", "call_date": "2026-10-08", "sport": "NFL", "player": "A", "market": "Pass Yards",
             "side": "Over", "line": 240.5, "model_prob": 0.62, "price": -115, "price_book": "draftkings", "hit": 1, "last_price": -140},
            {"logged_at": "2026-10-08T18:00:00+00:00", "call_date": "2026-10-08", "sport": "NFL", "player": "B", "market": "Rush Yards",
             "side": "Under", "line": 60.5, "model_prob": 0.58, "price": None, "price_book": None}]


def test_the_fingerprint_is_stable_order_free_and_covers_only_the_locked_fields():
    rows = _fp_rows()
    fp = AL.record_fingerprint(rows)
    assert len(fp) == 16 and fp == AL.record_fingerprint(list(reversed(rows)))
    later = [dict(r, hit=0, actual=5, settled_at="x", last_price=+120, last_line=1.0, marked_at="y", published_at="z") for r in rows]
    assert AL.record_fingerprint(later) == fp                                                       # results/marks/publication don't change it
    for field, new in (("line", 241.5), ("model_prob", 0.63), ("price", -110), ("player", "C"), ("logged_at", "2026-10-08T19:00:00+00:00"),
                       ("side", "Under"), ("market", "Points"), ("sport", "NBA"), ("call_date", "2026-10-09"), ("price_book", "fanduel")):
        changed = [dict(rows[0], **{field: new}), rows[1]]
        assert AL.record_fingerprint(changed) != fp, field
    assert AL.record_fingerprint(rows[:1]) != fp and AL.record_fingerprint([]) == ""


def test_the_fingerprint_can_be_recomputed_by_anyone_from_the_published_table():
    import hashlib
    table = AL.fingerprint_rows(_fp_rows())
    assert table[0][:4] == ["2026-10-08T18:00:00+00:00", "2026-10-08", "NFL", "A"] and table[1][-2:] == ["", ""]      # blanks for None
    text = "\n".join("|".join(t) for t in table)
    assert AL.record_fingerprint(_fp_rows()) == hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def test_an_existing_database_gets_the_published_column_too(tmp_path):
    import sqlite3
    path = str(tmp_path / "old2.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE analyst_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, logged_at TEXT NOT NULL, call_date TEXT NOT NULL, "
                "sport TEXT NOT NULL, game TEXT, game_date TEXT, player TEXT NOT NULL, player_id TEXT, team TEXT, market TEXT NOT NULL, "
                "side TEXT NOT NULL, line REAL, model_prob REAL, conviction REAL, price REAL, price_book TEXT, angles TEXT, cautions TEXT, "
                "score REAL, gem INTEGER, chalk INTEGER, why TEXT, hit INTEGER, actual REAL, settled_at TEXT, last_line REAL, last_price REAL, marked_at TEXT)")
    con.commit()
    con.close()
    assert AL.fetch_calls(db_path=path) == []
    AL.record_calls([call()], "2026-10-08", NOW, path)
    assert AL.mark_published([call()], NOW, path) == 1


# ------------------------------------------------------------------ post claims (the scheduled publisher posts once)
def test_a_post_can_be_claimed_once_released_and_claimed_again(db):
    assert not AL.posted("picks", "NBA", "2026-10-08", db_path=db)
    assert AL.claim_post("picks", "NBA", "2026-10-08", now=NOW, db_path=db) is True
    assert AL.posted("picks", "NBA", "2026-10-08", db_path=db)
    assert AL.claim_post("picks", "NBA", "2026-10-08", now=NOW, db_path=db) is False       # the second caller loses
    assert AL.claim_post("recap", "NBA", "2026-10-08", db_path=db) is True                 # another kind is its own claim
    assert AL.claim_post("picks", "NFL", "2026-10-08", db_path=db) is True                 # …and another sport
    assert AL.claim_post("picks", "NBA", "2026-10-09", db_path=db) is True                 # …and another day
    AL.release_post("picks", "NBA", "2026-10-08", db_path=db)
    assert not AL.posted("picks", "NBA", "2026-10-08", db_path=db)
    assert AL.posted("recap", "NBA", "2026-10-08", db_path=db) and AL.posted("picks", "NFL", "2026-10-08", db_path=db)
    assert AL.claim_post("picks", "NBA", "2026-10-08", db_path=db) is True


# ------------------------------------------------------------------ Postgres: no schema change per query, no deadlocks
class _PgWorld:
    """A stand-in for psycopg2 that records every statement, so the connection logic can be checked without a server."""

    class DeadlockDetected(Exception):
        pass

    class SerializationFailure(Exception):
        pass

    def __init__(self, columns=(), posts=True):
        self.columns, self.posts = list(columns), posts
        self.log, self.connects, self.fail_next = [], 0, []

    def install(self, monkeypatch):
        import sys
        import types
        world = self

        class Cur:
            def __init__(self, factory=None):
                self.rows = []

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params=None):
                world.log.append(sql)
                if world.fail_next and sql.startswith("SELECT 1"):
                    raise world.fail_next.pop(0)()
                if "information_schema" in sql:
                    self.rows = [(c,) for c in world.columns]
                elif "to_regclass" in sql:
                    self.rows = [("analyst_posts" if world.posts else None,)]
                elif sql.startswith("SELECT 1"):
                    self.rows = [{"x": 1}]
                else:
                    self.rows = []
                self.rowcount = 1

            def fetchall(self):
                return self.rows

            def fetchone(self):
                return self.rows[0]

        class Con:
            def cursor(self, cursor_factory=None):
                return Cur(cursor_factory)

            def commit(self):
                world.log.append("COMMIT")

            def close(self):
                world.log.append("CLOSE")

        def connect(dsn, **kw):
            world.connects += 1
            return Con()
        pg = types.ModuleType("psycopg2")
        pg.connect = connect
        pg.errors = types.SimpleNamespace(DeadlockDetected=world.DeadlockDetected, SerializationFailure=world.SerializationFailure)
        pg.extras = types.SimpleNamespace(RealDictCursor=object)
        monkeypatch.setitem(sys.modules, "psycopg2", pg)
        monkeypatch.setitem(sys.modules, "psycopg2.errors", pg.errors)
        monkeypatch.setitem(sys.modules, "psycopg2.extras", pg.extras)
        monkeypatch.setattr(AL, "USING_POSTGRES", True)
        monkeypatch.setattr(AL, "_DATABASE_URL", "postgres://u:p@h/db")
        monkeypatch.setattr(AL, "_PG_READY", False)
        monkeypatch.setattr("time.sleep", lambda s: None)

    def ddl(self):
        return [s for s in self.log if s.lstrip().upper().startswith(("CREATE", "ALTER"))]


ALL_COLS = ["id", "logged_at", "last_line", "last_price", "marked_at", "published_at"]


def test_an_up_to_date_database_is_never_altered_so_sessions_cannot_deadlock(monkeypatch):
    w = _PgWorld(columns=ALL_COLS)
    w.install(monkeypatch)
    for _ in range(3):
        AL._run(None, "SELECT 1 AS x", fetch=True)
    assert w.connects == 3 and w.ddl() == []                                  # reads the catalog once, changes nothing
    assert sum(1 for s in w.log if "information_schema" in s) == 1             # …and only once per process
    assert not any("advisory" in s for s in w.log)


def test_a_missing_column_or_table_is_added_under_an_advisory_lock_and_only_once(monkeypatch):
    for kw, creates in (({"columns": ALL_COLS[:-1]}, True), ({"columns": ALL_COLS, "posts": False}, True), ({"columns": []}, True)):
        w = _PgWorld(**kw)
        w.install(monkeypatch)
        AL._run(None, "SELECT 1 AS x", fetch=True)
        assert any(s.lstrip().upper().startswith("CREATE") for s in w.log) == creates
        assert w.log.index("COMMIT") < w.log.index("SELECT 1 AS x")             # the schema change is committed before the query runs
        lock = next(i for i, s in enumerate(w.log) if "pg_advisory_xact_lock" in s)
        changes = [i for i, s in enumerate(w.log) if s.lstrip().upper().startswith(("CREATE", "ALTER"))]
        assert changes and all(i > lock for i in changes)                       # every change happens after the lock is taken
        assert w.log.index("COMMIT") > changes[-1]                              # …and is committed before the query runs
        AL._run(None, "SELECT 1 AS x", fetch=True)
        assert [i for i, s in enumerate(w.log) if s.lstrip().upper().startswith(("CREATE", "ALTER"))] == changes   # none added


def test_a_query_that_loses_a_deadlock_is_retried_and_other_errors_are_not_hidden(monkeypatch):
    w = _PgWorld(columns=ALL_COLS)
    w.install(monkeypatch)
    w.fail_next = [w.DeadlockDetected, w.SerializationFailure]
    assert AL._run(None, "SELECT 1 AS x", fetch=True) == [{"x": 1}]
    assert w.connects == 3 and w.log.count("CLOSE") == 3                       # each attempt used (and closed) its own connection
    w.fail_next = [w.DeadlockDetected] * 3
    with pytest.raises(_PgWorld.DeadlockDetected):
        AL._run(None, "SELECT 1 AS x", fetch=True)                             # gives up after PG_RETRIES attempts
    w.fail_next = [KeyError]
    with pytest.raises(KeyError):
        AL._run(None, "SELECT 1 AS x", fetch=True)


# --- one connection per batch (each connection is a network handshake on the cloud database) -------------
def _posted_call(player, **kw):
    return call(player=player, book_state="posted", **kw)


def test_a_whole_card_is_written_on_one_connection_not_one_per_call(monkeypatch):
    w = _PgWorld(columns=ALL_COLS)
    w.install(monkeypatch)
    cards = [_posted_call(f"P{i}", pid=i) for i in range(6)]
    assert AL.record_calls(cards, "2026-10-08", NOW) == 6
    assert w.connects == 1
    assert AL.mark_calls(cards, "2026-10-08", NOW) == 6 and w.connects == 2
    assert AL.mark_published(cards) == 6 and w.connects == 3
    assert sum(1 for s in w.log if s.startswith("INSERT INTO analyst_calls")) == 6      # every call still gets its own statement


def test_an_empty_batch_opens_no_connection(monkeypatch):
    w = _PgWorld(columns=ALL_COLS)
    w.install(monkeypatch)
    assert AL.record_calls([], "2026-10-08", NOW) == 0 and AL.mark_calls([], "2026-10-08", NOW) == 0 and AL.mark_published([]) == 0
    assert AL._run_many(None, []) == [] and w.connects == 0


def test_a_batch_that_loses_a_deadlock_is_retried_as_a_whole(monkeypatch):
    w = _PgWorld(columns=ALL_COLS)
    w.install(monkeypatch)
    w.fail_next = [w.DeadlockDetected]
    assert AL._run_many(None, [("SELECT 1 AS x", ()), ("SELECT 1 AS y", ())]) == [1, 1]
    assert w.connects == 2
    w.fail_next = [w.DeadlockDetected] * 3
    with pytest.raises(_PgWorld.DeadlockDetected):
        AL._run_many(None, [("SELECT 1 AS x", ())])


def test_the_batched_writes_give_the_same_results_on_the_local_database(db):
    cards = [_posted_call("A", pid=1), _posted_call("B", pid=2)]
    assert AL.record_calls(cards, "2026-10-08", NOW, db) == 2
    assert AL.record_calls(cards + [_posted_call("C", pid=3)], "2026-10-08", NOW, db) == 1     # only the new one counts
    assert AL.mark_calls(cards, "2026-10-08", NOW, db) == 2
    assert AL.mark_published(cards[:1], NOW, db) == 1 and AL.mark_published(cards[:1], NOW, db) == 0
    rows = {r["player"]: r for r in AL.fetch_calls(db_path=db)}
    assert rows["A"]["published_at"] and not rows["B"]["published_at"] and rows["A"]["last_price"] == -115


def test_settling_a_day_grades_every_call_in_one_batch(db, monkeypatch):
    AL.record_calls([call(player=f"P{i}", pid=i) for i in range(1, 4)], "2026-10-08", NOW, db)
    seen = []
    real = AL._run_many
    monkeypatch.setattr(AL, "_run_many", lambda p, jobs: seen.append(len(jobs)) or real(p, jobs))
    out = AL.settle_day("NFL", "2026-10-08", {1: {"passing_yards": 300}, 2: {"passing_yards": 100}}, db)
    assert out["settled"] == 3 and out["voids"] == 1 and seen == [3]
