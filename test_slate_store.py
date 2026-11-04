"""slate_store: a built slate is saved once and read back while fresh (Nov 4)."""
import time

import model_store as MS
import slate_store as SS


def test_saved_slate_is_reused_and_expires(tmp_path, monkeypatch):
    db = str(tmp_path / "m.db")
    monkeypatch.setattr(SS, "_off", lambda: False)
    monkeypatch.setattr(MS, "load_slate", lambda sport, date, db_path=None, _l=MS.load_slate: _l(sport, date, db))
    monkeypatch.setattr(MS, "save_slate", lambda sport, date, payload, db_path=None, _s=MS.save_slate: _s(sport, date, payload, db))
    SS._mem.clear()
    calls = []

    def build(date_str, min_minutes=10):
        calls.append(date_str)
        return [{"player": "A", "log": [1, 2, 3]}], [{"game": "X @ Y"}]

    wrapped = SS.persisted("NBA")(build)
    today = SS._today_et()
    rows, meta = wrapped(today)
    rows[0]["player"] = "edited"                       # a caller editing its copy doesn't change the saved one
    assert wrapped(today)[0][0]["player"] == "A" and calls == [today]
    SS._mem.clear()                                    # a restarted app: read back from the database
    assert wrapped(today)[1] == [{"game": "X @ Y"}] and calls == [today]
    wrapped(today, 5)                                  # other arguments: built as before, not cached
    assert len(calls) == 2
    SS._mem.clear()
    monkeypatch.setattr(SS, "FRESH_S", 0)              # stale today -> rebuilt
    time.sleep(0.01)
    wrapped(today)
    assert len(calls) == 3
    SS._mem.clear()
    wrapped("2020-01-01")
    wrapped("2020-01-01")                              # a past slate never goes stale
    assert calls.count("2020-01-01") == 1


def test_empty_slate_is_never_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(SS, "_off", lambda: False)
    monkeypatch.setattr(MS, "load_slate", lambda *a, **k: None)
    saved = []
    monkeypatch.setattr(MS, "save_slate", lambda *a, **k: saved.append(a))
    SS._mem.clear()
    SS.persisted("NHL")(lambda d: ([], []))("2026-11-04")
    assert saved == [] and not SS._mem


def test_finished_box_scores_are_fetched_once(tmp_path, monkeypatch):
    db = str(tmp_path / "m.db")
    monkeypatch.setattr(SS, "_off", lambda: False)
    monkeypatch.setattr(MS, "load_blobs", lambda kind, keys, db_path=None, _l=MS.load_blobs: _l(kind, keys, db))
    monkeypatch.setattr(MS, "save_blobs", lambda kind, items, db_path=None, _s=MS.save_blobs: _s(kind, items, db))
    SS._blob_mem.clear()
    fetched = []

    def one(g):
        fetched.append(g)
        return {} if g == "3" else {101: [{"pts": 20}]}       # game 3: empty (not final) -> not kept

    out = SS.cached_many("lines:nba", ["1", "2", "3"], one)
    assert out["1"] == {101: [{"pts": 20}]} and sorted(fetched) == ["1", "2", "3"]
    SS._blob_mem.clear()                                      # restarted app: read back from the database
    out = SS.cached_many("lines:nba", ["1", "2", "3"], one)
    assert sorted(fetched) == ["1", "2", "3", "3"] and out["2"] == {101: [{"pts": 20}]}
