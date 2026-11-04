import analyst_ledger as AL
import settle_analyst as S


def test_grades_open_days_for_every_sport(monkeypatch, capsys):
    rows = [{"sport": "NBA", "date": "2026-10-20", "settled_at": None}, {"sport": "NFL", "date": "2026-11-01", "settled_at": None},
            {"sport": "NFL", "date": "2026-10-25", "settled_at": "x"}]
    monkeypatch.setattr(AL, "fetch_calls", lambda **k: rows)
    seen = []

    def settle(sport, days, fn, **k):
        seen.append((sport, days))
        return {"settled": 3, "hits": 2, "voids": 0, "days": [(days[0], {})], "waiting": []}
    monkeypatch.setattr(AL, "settle_open_days", settle)
    assert S.main([]) == 0
    assert sorted(seen) == [("NBA", ["2026-10-20"]), ("NFL", ["2026-11-01"])]
    assert "total graded: 6" in capsys.readouterr().out
