"""Nov 26: game picks for every league in one query (Today's soccer section took ~12 s one league at a time)."""
import os
import sqlite3

import model_store as MS


def test_batch_matches_one_at_a_time(tmp_path, monkeypatch):
    db = str(tmp_path / "m.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE game_picks (sport TEXT, game_id TEXT, kickoff TEXT, payload TEXT, final_home REAL, "
                "final_away REAL, result TEXT, ts TEXT)")
    rows = [("EPL", "1", "2026-11-26T15:00Z", '{"home": "A"}', None, None, None),
            ("EPL", "2", "2026-11-26T17:00Z", '{"home": "B"}', 1, 0, "home"),
            ("MLS", "3", "2026-11-27T01:00Z", '{"home": "C"}', None, None, None)]
    con.executemany("INSERT INTO game_picks VALUES (?,?,?,?,?,?,?,'')", rows)
    con.commit()
    con.close()
    monkeypatch.setattr(MS, "DB_PATH", db)
    monkeypatch.setattr(MS, "available", lambda: True)
    monkeypatch.setattr(MS, "_pg", lambda: False)
    got = MS.game_picks_by_sport(["EPL", "MLS", "BUND"], ungraded=True)
    assert [p["home"] for p in got["EPL"]] == ["A"] and [p["home"] for p in got["MLS"]] == ["C"] and got["BUND"] == []
    assert [p["home"] for p in MS.game_picks_by_sport(["EPL"])["EPL"]] == ["A", "B"]


def test_fallback_keeps_each_leagues_error(monkeypatch):
    monkeypatch.setattr(MS, "_load_many", lambda sports, ungraded: None)

    def one(sp, ungraded=False):
        if sp == "BAD":
            raise RuntimeError("down")
        return [{"home": sp}]
    monkeypatch.setattr(MS, "load_game_picks", one)
    got = MS.game_picks_by_sport(["EPL", "BAD"])
    assert MS.picks_of(got, "EPL") == [{"home": "EPL"}]
    try:
        MS.picks_of(got, "BAD")
        raise AssertionError("should raise")
    except RuntimeError:
        pass
