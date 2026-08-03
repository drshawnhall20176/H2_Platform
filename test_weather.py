"""
test_weather.py — offline tests for weather math and parsing (no network).

    python test_weather.py    # or: pytest test_weather.py
"""

import time
from pathlib import Path

import weather as W

_HERE = Path(__file__).parent


def test_wind_out_component():
    # CF due north (bearing 0). Wind FROM south blows straight out -> +full.
    assert round(W.wind_out_component(10, 180, 0), 1) == 10.0
    # Wind FROM north blows straight in -> -full.
    assert round(W.wind_out_component(10, 0, 0), 1) == -10.0
    # Wind FROM west is a crosswind -> ~0 out component.
    assert abs(W.wind_out_component(10, 270, 0)) < 0.01


def test_hr_factor():
    assert W.hr_factor(70, 0, "open") == 1.0                  # baseline neutral
    assert W.hr_factor(90, 0, "open") > 1.0                   # heat helps
    assert W.hr_factor(50, -10, "open") < 1.0                 # cold + wind in suppresses
    assert W.hr_factor(90, 10, "fixed") == 1.0               # dome ignores weather
    assert W.hr_factor(120, 40, "open") == W.HR_FACTOR_MAX    # clamp at the top
    assert W.hr_factor(20, -40, "open") == W.HR_FACTOR_MIN    # clamp at the bottom


def test_get_game_weather_parsing():
    def fake(lat, lon, date_str):
        return {"hourly": {
            "time": ["2026-06-28T21:00", "2026-06-28T22:00", "2026-06-28T23:00"],
            "temperature_2m": [78, 82, 85],
            "wind_speed_10m": [8, 12, 10],
            "wind_direction_10m": [180, 180, 200],
        }}
    wx = W.get_game_weather(12, "2026-06-28T22:00:00Z", fetcher=fake)  # Coors, cf_bearing 0
    assert wx["temp_f"] == 82 and wx["wind_mph"] == 12
    assert wx["out_wind_mph"] > 0          # wind from south = out to CF
    assert wx["hr_factor"] > 1.0


def test_graceful_degradation():
    assert W.get_game_weather(999999, "2026-06-28T22:00:00Z", fetcher=lambda *a: {}) is None
    assert W.get_game_weather(None, None) is None
    # fixed dome short-circuits without any fetch
    wx = W.get_game_weather(5325, "2026-06-28T22:00:00Z", fetcher=lambda *a: 1 / 0)
    assert wx["hr_factor"] == 1.0 and wx["dome"] is True


def test_no_duplicate_or_clobbered_parks():
    # the table should have distinct, populated parks (guards the placeholder-key bug)
    assert all("lat" in v for v in W.STADIUMS.values())
    assert W.STADIUMS[2]["name"] == "Chase Field"   # not clobbered by a placeholder


def test_full_table_complete():
    # All 30 current parks present, each fully populated, names unique (guards typos/clobbers).
    assert len(W._STATIC_STADIUMS) == 30
    for v in W._STATIC_STADIUMS.values():
        assert {"name", "lat", "lon", "roof", "cf_bearing"} <= set(v)
        assert v["roof"] in ("open", "fixed", "retractable")
    names = [v["name"] for v in W._STATIC_STADIUMS.values()]
    assert len(names) == len(set(names))


def test_name_fallback_resolves():
    # venue_id missing from table, but the name matches -> still resolves.
    def fake(lat, lon, date_str):
        return {"hourly": {"time": ["2026-06-28T22:00"], "temperature_2m": [80],
                           "wind_speed_10m": [5], "wind_direction_10m": [180]}}
    wx = W.get_game_weather(999999, "2026-06-28T22:00:00Z", venue_name="Wrigley Field", fetcher=fake)
    assert wx is not None and wx["park"] == "Wrigley Field"
    # garbage name and id -> None
    assert W.get_game_weather(999999, "2026-06-28T22:00:00Z", venue_name="Nowhere Park", fetcher=fake) is None


def test_json_override_loading():
    import json
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "stadiums.json")
        with open(p, "w") as f:
            json.dump({"2": {"name": "Chase Field", "lat": 33.4, "lon": -112.0,
                             "roof": "retractable", "cf_bearing": 0}}, f)
        ov = W._load_overrides(p)
        assert 2 in ov and ov[2]["name"] == "Chase Field"   # JSON string key -> int
    assert W._load_overrides("/no/such/file.json") == {}     # absent -> empty


def test_sponsor_tolerant_matching():
    # A sponsor-prefixed current name still resolves to the right park...
    k = W._best_name_key(W._norm("UNIQLO Field at Dodger Stadium"), W._BY_NAME)
    assert k and W._BY_NAME[k]["name"] == "Dodger Stadium"
    k2 = W._best_name_key(W._norm("Whatever Co Field at Wrigley Field"), W._BY_NAME)
    assert k2 and W._BY_NAME[k2]["name"] == "Wrigley Field"
    # ...but short generic tokens must NOT match anything.
    assert W._best_name_key("park", W._BY_NAME) is None
    assert W._best_name_key("field", W._BY_NAME) is None


def test_override_merge_corrects_defaulted_bearing():
    # A refreshed entry under a sponsor name with a defaulted 0 bearing should be corrected
    # back to the curated bearing via name match, while keeping the API's id + coords.
    overrides = {111: {"name": "UNIQLO Field at Dodger Stadium", "lat": 34.07, "lon": -118.24,
                       "roof": "open", "cf_bearing": 0}}
    merged = W._merge_overrides(W._STATIC_STADIUMS, overrides)
    assert merged[111]["cf_bearing"] == 25      # corrected from the defaulted 0
    assert merged[111]["lat"] == 34.07          # API coords retained


# ----------------------------------------------------------------- load_slate_weather
def test_load_slate_weather_dedupes_by_venue():
    # A doubleheader shares one park -- two games, same venue_id, must be ONE real fetch.
    calls = []

    def fake_get_game_weather(vid, gdate, vname=None):
        calls.append(vid)
        return {"venue_id": vid, "temp_f": 75}

    orig = W.get_game_weather
    W.get_game_weather = fake_get_game_weather
    try:
        meta_keys = ((12, "2026-06-28", "Coors Field"), (12, "2026-06-28", "Coors Field"))
        result = W.load_slate_weather(meta_keys)
    finally:
        W.get_game_weather = orig

    assert calls == [12]                       # fetched ONCE, not twice
    assert result[12]["temp_f"] == 75
    print("\u2713 load_slate_weather fetches each unique venue only once, even if it appears twice in meta_keys")


def test_load_slate_weather_skips_none_venue_id():
    calls = []

    def fake_get_game_weather(vid, gdate, vname=None):
        calls.append(vid)
        return {"venue_id": vid}

    orig = W.get_game_weather
    W.get_game_weather = fake_get_game_weather
    try:
        meta_keys = ((None, "2026-06-28", None), (12, "2026-06-28", "Coors Field"))
        result = W.load_slate_weather(meta_keys)
    finally:
        W.get_game_weather = orig

    assert calls == [12]            # None venue never fetched
    assert None not in result       # and never added to the output dict either
    assert 12 in result
    print("\u2713 load_slate_weather skips a missing venue_id entirely, same as every former local wrapper")


def test_load_slate_weather_one_game_failure_doesnt_break_the_slate():
    def flaky_get_game_weather(vid, gdate, vname=None):
        if vid == 13:
            raise ValueError("simulated real fetch failure")
        return {"venue_id": vid, "temp_f": 80}

    orig = W.get_game_weather
    W.get_game_weather = flaky_get_game_weather
    try:
        meta_keys = ((12, "2026-06-28", "Coors Field"), (13, "2026-06-28", "Some Park"))
        result = W.load_slate_weather(meta_keys)
    finally:
        W.get_game_weather = orig

    assert result[12]["temp_f"] == 80    # the good game is unaffected
    assert result[13] is None            # the failing game degrades to None, not a crash
    print("\u2713 load_slate_weather isolates one game's real fetch failure \u2014 the rest of the slate still loads")


def test_load_slate_weather_is_genuinely_parallel():
    # THE regression test for the real, confirmed performance finding this function exists to
    # fix: the 3 former local wrappers fetched one game at a time, sequentially. Proven here
    # directly with real wall-clock timing, not just asserted from ThreadPoolExecutor being
    # present in the source -- a simulated per-call delay across several "games" must complete in
    # roughly ONE delay's worth of time (fanned out concurrently), not N delays' worth (run one
    # after another). 8 games, 100ms simulated delay each: sequential would be ~800ms; parallel
    # (max_workers=8) should land close to 100ms, generously bounded at 400ms to stay reliable on
    # a loaded CI box without weakening the real point being proven.
    def slow_get_game_weather(vid, gdate, vname=None):
        time.sleep(0.1)
        return {"venue_id": vid}

    orig = W.get_game_weather
    W.get_game_weather = slow_get_game_weather
    try:
        meta_keys = tuple((vid, "2026-06-28", f"Park {vid}") for vid in range(1, 9))   # 8 unique venues
        t0 = time.perf_counter()
        result = W.load_slate_weather(meta_keys)
        elapsed = time.perf_counter() - t0
    finally:
        W.get_game_weather = orig

    assert len(result) == 8
    assert elapsed < 0.4, (f"took {elapsed:.2f}s for 8 games at 0.1s each \u2014 should be ~0.1s "
                           "fanned out concurrently, not ~0.8s run one at a time")
    print(f"\u2713 load_slate_weather is genuinely parallel \u2014 8 simulated 0.1s fetches completed in "
         f"{elapsed:.2f}s, not the ~0.8s a sequential loop (the exact bug this fixes) would take")


def test_load_slate_weather_is_cached():
    calls = []

    def counting_get_game_weather(vid, gdate, vname=None):
        calls.append(vid)
        return {"venue_id": vid, "temp_f": 70}

    orig = W.get_game_weather
    W.get_game_weather = counting_get_game_weather
    try:
        meta_keys = ((21, "2026-06-28", "Park A"),)
        W.load_slate_weather(meta_keys)
        W.load_slate_weather(meta_keys)   # identical args -- should be a cache hit, no new call
    finally:
        W.get_game_weather = orig

    assert calls == [21]   # only ONE real underlying fetch across both calls
    print("\u2713 load_slate_weather is genuinely cached \u2014 a repeated call with identical meta_keys doesn't re-fetch")


def test_every_former_weather_call_site_now_uses_load_slate_weather():
    # Regression guard for the consolidation itself, matching the same class of check already
    # done for statcast_data.load_cached \u2014 confirms load_slate_weather is actually ADOPTED
    # everywhere it needs to be, not just that it works correctly in isolation.
    call_sites = [
        _HERE / "best_bets_data.py",
        _HERE / "views" / "15_#L01f4c8_Edge_Board.py",
        _HERE / "views" / "8_#L01f4a3_Dinger_Engine.py",
    ]
    for path in call_sites:
        src = path.read_text()
        assert "load_slate_weather(" in src, f"{path.name} must call the shared weather.load_slate_weather()"
        assert "def load_weather(meta_keys" not in src, f"{path.name} still defines its own local sequential load_weather wrapper"
    print(f"\u2713 all {len(call_sites)} former duplicate weather call sites now use the one shared, "
         "parallelized weather.load_slate_weather(), none still define their own local sequential wrapper")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}"); passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
