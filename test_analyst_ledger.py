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
