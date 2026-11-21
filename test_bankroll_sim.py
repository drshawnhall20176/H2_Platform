import bankroll_sim as BS


def test_day_cap_and_simulation():
    days = {f"2026-11-{i:02d}": [(2.0, 1.91, i % 2 == 0)] * 8 for i in range(1, 21)}
    for k, v in list(days.items()):
        tot = sum(u for u, _, _ in v)
        if tot > BS.DAILY_CAP:
            days[k] = [(u * BS.DAILY_CAP / tot, d, h) for u, d, h in v]
    s = BS.simulate(days, paths=300)
    assert s and 0 <= s["p_up"] <= 1 and s["bad_end"] <= s["median_end"] <= s["good_end"]
    z = BS.simulate(days, no_edge=True, paths=300)
    assert z["median_dd"] >= 0


def test_too_few_days():
    assert BS.simulate({"a": [(1, 2.0, True)]}, paths=10) is None


def test_games_rows_are_counted(monkeypatch):
    games = [{"money": True, "money_result": "win", "money_price": -110, "money_chance": 0.6, "_day": f"d{i}"}
             for i in range(6)]
    d = BS.day_picks({}, games)
    assert len(d) == 6
