from datetime import datetime, timezone
import football_weather as FW


def test_multiplier_buckets_and_indoor():
    assert FW.multiplier("Pass Yards", {"wind": 8, "temp": 60}) == 1.0
    assert FW.multiplier("Pass Yards", {"wind": 17, "temp": 60}) == 0.935
    assert round(FW.multiplier("Pass Yards", {"wind": 22, "temp": 30}), 4) == round(0.89 * 0.97, 4)
    assert FW.multiplier("Pass Yards", {"wind": 25, "temp": 10, "indoor": True}) == 1.0
    assert FW.multiplier("Solo Tackles", {"wind": 25}) == 1.0
    assert FW.multiplier("Rush Yards", {"wind": 21}) == 1.10
    assert "wind 17 mph" in FW.flag("Receiving Yards", {"wind": 17, "temp": 50})


def test_slate_and_match():
    sb = {"events": [{"date": "2026-11-08T18:00Z", "competitions": [{
        "venue": {"fullName": "Arrowhead", "indoor": False, "address": {"city": "Kansas City", "state": "MO"}},
        "competitors": [{"homeAway": "home", "team": {"abbreviation": "KC", "displayName": "Kansas City Chiefs"}},
                        {"homeAway": "away", "team": {"abbreviation": "NYJ", "displayName": "New York Jets"}}]}]}]}
    geo = {"results": [{"latitude": 39.1, "longitude": -94.6, "admin1": "Missouri"}]}
    fc = {"hourly": {"time": [f"2026-11-08T{h:02d}:00" for h in range(24)], "temperature_2m": [35.0] * 24,
                     "wind_speed_10m": [18.0] * 24}}

    def fetch(url, params):
        return sb if "scoreboard" in url else geo if "geocoding" in url else fc
    FW._CACHE.clear()
    sl = FW.slate("NFL", "2026-11-08", fetch=fetch)
    g = FW.for_game(sl, "KC", "NYJ")
    assert g and g["wind"] == 18.0 and g["temp"] == 35.0 and not g["indoor"]
    assert FW.for_game(sl, "BUF", "MIA") is None
    FW._CACHE.clear()


def test_failed_lookups_are_not_remembered():
    FW._CACHE.clear()
    calls = []

    def go():
        calls.append(1)
        return None
    FW._cached("k", go)
    FW._cached("k", go)
    assert len(calls) == 2
    FW._CACHE.clear()
