"""Nov 21: college slates are never built inside the app (slate_store.persisted)."""
import slate_store as SS


def test_heavy_sport_in_app_reads_saved_or_returns_empty(monkeypatch):
    calls = []
    monkeypatch.setattr(SS, "_off", lambda: False)
    monkeypatch.setattr(SS, "_in_app", lambda: True)
    monkeypatch.setattr(SS, "load", lambda sport, d, max_age=None: None)
    f = SS.persisted("NCAAF")(lambda d: calls.append(d) or ([1], [2]))
    assert f("2026-11-21") == ([], []) and calls == []
    g = SS.persisted("NBA")(lambda d: calls.append(d) or ([1], [2]))
    monkeypatch.setattr(SS, "save", lambda *a: None)
    assert g("2026-11-21") == ([1], [2]) and calls == ["2026-11-21"]


def test_heavy_sport_in_app_takes_an_older_same_day_copy(monkeypatch):
    monkeypatch.setattr(SS, "_off", lambda: False)
    monkeypatch.setattr(SS, "_in_app", lambda: True)
    blob = SS.encode(([9], [8]))
    monkeypatch.setattr(SS, "load", lambda sport, d, max_age=None: blob if (max_age or 0) > SS.FRESH_S else None)
    f = SS.persisted("NCAAMB")(lambda d: (_ for _ in ()).throw(AssertionError("built")))
    assert f("2026-11-21") == ([9], [8])


def test_college_reads_in_the_app_come_from_the_saved_copy(monkeypatch):
    import best_bets_data as BBD
    monkeypatch.setattr(BBD, "_in_app", lambda: True)
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "k")
    monkeypatch.setattr(BBD, "saved_reads", lambda sp, d: {("1", "rec"): {"player": "A"}})
    monkeypatch.setattr(BBD, "slate_reads_for", lambda *a, **k: (_ for _ in ()).throw(AssertionError("computed")))
    assert BBD.load_slate_reads("NCAAF", "2026-11-21") == {("1", "rec"): {"player": "A"}}
    monkeypatch.setattr(BBD, "saved_reads", lambda sp, d: None)
    assert BBD.load_slate_reads("NCAAF", "2026-11-22") == {}           # (another date: the first is cached)
