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


def test_slate_reads_build_only_posted_games_on_a_big_slate(monkeypatch):
    """Nov 18: the Pick'em Board hung on college basketball -- load_slate_reads built all 71 games (2,200 roster spots)."""
    import best_bets_data as BBD
    BBD.load_slate_reads.clear()
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "K")
    seen = {}
    monkeypatch.setattr(BBD, "_big_slate_props_games", lambda *a: seen.setdefault("big", ([], [{"label": "g"}])))
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a: [])
    monkeypatch.setattr(BBD, "slate_reads_for", lambda *a: {"ok": 1})

    eng = BBD.sports.get("NCAAMB").engine
    monkeypatch.setattr(eng, "build_slate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("full slate built")))
    assert BBD.load_slate_reads("NCAAMB", "2026-11-18", "draftkings") == {"ok": 1} and "big" in seen
    BBD.load_slate_reads.clear()


def test_extra_fetch_asks_only_for_given_games(monkeypatch):
    import odds_api as O
    monkeypatch.setattr(O, "fetch_events_all", lambda *a, **k: [{"id": "a", "commence_time": "2026-11-19T00:00:00Z"},
                                                                 {"id": "b", "commence_time": "2026-11-19T00:00:00Z"}])
    asked = []
    monkeypatch.setattr(O, "fetch_event_props", lambda eid, *a, **k: asked.append(eid) or ({"bookmakers": []}, {}))
    O.fetch_slate_props("2026-11-18", "K", ["m"], sport="basketball_ncaab", bookmakers=["novig"], event_ids=["b"])
    assert asked == ["b"]
