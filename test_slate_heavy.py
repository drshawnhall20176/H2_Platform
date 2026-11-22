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
