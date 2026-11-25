import pandas as pd

import nfl_engine as E


def test_schedule_falls_back_to_the_release_csv(monkeypatch):
    def boom(_):
        raise ConnectionError("404 games.parquet")
    monkeypatch.setattr(E.nfl, "load_schedules", boom)
    csv = pd.DataFrame([{"game_id": "2026_12_GB_LA", "season": 2026, "week": 12, "gameday": "2026-11-25",
                         "gametime": "20:00", "home_team": "LA", "away_team": "GB", "home_score": float("nan"),
                         "away_score": float("nan")},
                        {"game_id": "2025_12_X_Y", "season": 2025, "week": 12, "gameday": "2025-11-25",
                         "gametime": "20:00", "home_team": "Y", "away_team": "X", "home_score": 20, "away_score": 17}])
    df = E._schedule_frame(2026, csv_reader=lambda url: csv)
    assert list(df["game_id"]) == ["2026_12_GB_LA"] and df.iloc[0]["home_score"] is None
    monkeypatch.setattr(E, "_schedule_frame", lambda season: df)
    got = E.get_schedule(2026)
    assert got[0]["home_team"] == "LA" and got[0]["week"] == 12 and got[0]["home_score"] is None


def test_both_sources_failing_is_none(monkeypatch):
    monkeypatch.setattr(E.nfl, "load_schedules", lambda s: (_ for _ in ()).throw(ConnectionError("x")))
    assert E._schedule_frame(2026, csv_reader=lambda url: (_ for _ in ()).throw(OSError("y"))) is None
