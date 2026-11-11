"""Nov 11: college basketball boards build only the games the books posted player props for (memory)."""
import types

import best_bets_data as BBD


def test_only_posted_games_are_built(monkeypatch):
    games = [{"home_name": "Michigan Wolverines", "away_name": "Marquette Golden Eagles"},
             {"home_name": "Duke Blue Devils", "away_name": "Army Black Knights"}]
    seen = {}

    def build_slate(date_str, keep=None):
        seen["kept"] = [g for g in games if keep is None or keep(g)]
        return [{"player": "x"}], [{"label": "Marquette Golden Eagles @ Michigan Wolverines"}]
    sport = types.SimpleNamespace(markets=["player_points"], engine=types.SimpleNamespace(build_slate=build_slate))
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a: [
        {"home_team": "Michigan Wolverines", "away_team": "Marquette Golden Eagles", "player": "A"}])
    rows, meta = BBD._big_slate_props_games(sport, "NCAAMB", "2026-11-11", "key")
    assert [g["home_name"] for g in seen["kept"]] == ["Michigan Wolverines"] and rows


def test_nothing_built_without_posted_props(monkeypatch):
    called = []
    sport = types.SimpleNamespace(markets=["player_points"],
                                  engine=types.SimpleNamespace(build_slate=lambda *a, **k: called.append(1)))
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a: [])
    assert BBD._big_slate_props_games(sport, "NCAAMB", "2026-11-11", "key") == ([], [])
    assert BBD._big_slate_props_games(sport, "NCAAMB", "2026-11-11", None) == ([], []) and not called


def test_ncaamb_build_slate_honours_keep(monkeypatch):
    import ncaamb_engine as E
    monkeypatch.setattr(E, "get_schedule", lambda d: [{"home_name": "A", "away_name": "B", "home_id": 1, "away_id": 2}])
    monkeypatch.setattr(E, "get_team_roster", lambda tid: (_ for _ in ()).throw(AssertionError("built anyway")))
    assert E.build_slate("2026-11-11", keep=lambda g: False) == ([], [])
