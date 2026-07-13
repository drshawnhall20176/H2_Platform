"""Tests for matchup_data — the pure aggregation logic, with mock pitch-level data shaped like
real Statcast. The network pull (refresh) can't be tested offline; these lock the math."""

import pandas as pd
import matchup_data as M


def _mock_pitches():
    """A tiny pitch-level frame with the real Statcast column names."""
    rows = []
    # Pitcher 100 throws 4-seam (FF) and slider (SL). Batter 200 sees both.
    # 40 four-seams: 20 swings, 5 whiffs. 40 sliders: 30 swings, 18 whiffs.
    for i in range(40):
        rows.append({"pitcher": 100, "batter": 200, "pitch_type": "FF", "release_speed": 95.0,
                     "strikes": i % 3, "description": "swinging_strike" if i < 5 else
                     ("foul" if i < 20 else "ball"),
                     "events": "home_run" if i == 0 else ("field_out" if i < 6 else ""),
                     "estimated_woba_using_speedangle": 0.4 if i < 6 else None})
    for i in range(40):
        rows.append({"pitcher": 100, "batter": 200, "pitch_type": "SL", "release_speed": 86.0,
                     "strikes": 2 if i < 20 else 0,
                     "description": "swinging_strike" if i < 18 else
                     ("hit_into_play" if i < 30 else "called_strike"),
                     "events": "strikeout" if i < 18 else ("single" if i < 24 else ""),
                     "estimated_woba_using_speedangle": 0.2 if i >= 18 and i < 30 else None})
    return pd.DataFrame(rows)


def test_pitcher_arsenal_usage_and_whiff():
    ars = M.build_pitcher_arsenal(_mock_pitches())
    ff = ars[(ars["pitcher"] == 100) & (ars["pitch_type"] == "FF")].iloc[0]
    sl = ars[(ars["pitcher"] == 100) & (ars["pitch_type"] == "SL")].iloc[0]
    # 80 total pitches, 40 each -> 50% usage each
    assert abs(ff["usage"] - 0.5) < 1e-6 and abs(sl["usage"] - 0.5) < 1e-6
    # FF: swings = 5 whiffs + 15 fouls = 20; whiffs = 5 -> 25%
    assert abs(ff["whiff"] - 0.25) < 1e-6
    # SL: swings = 18 whiffs + 12 in-play = 30; whiffs = 18 -> 60%
    assert abs(sl["whiff"] - 0.60) < 1e-6
    assert ff["family"] == "Fastball" and sl["family"] == "Breaking"
    assert ff["pitch_name"] == "4-Seam FB"
    print("✓ arsenal: usage, whiff-per-swing, family, name")


def test_pitcher_arsenal_min_pitches_filter():
    df = _mock_pitches()
    # add a rarely-thrown pitch (10 changeups) -> below MIN_PITCHES_ARSENAL, should be dropped
    extra = pd.DataFrame([{"pitcher": 100, "batter": 200, "pitch_type": "CH", "release_speed": 84,
                           "strikes": 0, "description": "ball", "events": "",
                           "estimated_woba_using_speedangle": None} for _ in range(10)])
    ars = M.build_pitcher_arsenal(pd.concat([df, extra], ignore_index=True))
    assert "CH" not in set(ars["pitch_type"])       # too few thrown
    print("✓ arsenal: rare pitches below the sample floor are dropped")


def test_hitter_splits_by_family():
    hs = M.build_hitter_splits(_mock_pitches())
    fb = hs[(hs["batter"] == 200) & (hs["family"] == "Fastball")].iloc[0]
    br = hs[(hs["batter"] == 200) & (hs["family"] == "Breaking")].iloc[0]
    # Fastball ABs: 1 HR (4 TB) + 5 field_out = 6 ABs, 4 TB -> SLG .667
    assert abs(fb["slg"] - (4 / 6)) < 1e-6
    # Breaking ABs: 18 strikeouts + 6 singles = 24 ABs, 6 TB -> SLG .250
    assert abs(br["slg"] - (6 / 24)) < 1e-6
    # Breaking whiff: 18 whiffs / 30 swings = 60%
    assert abs(br["whiff"] - 0.60) < 1e-6
    print("✓ hitter splits: SLG-against and whiff by family")


def test_matchup_score_direction():
    # A pitch the pitcher misses bats with (high p_whiff) vs a hitter who whiffs a lot and does
    # little damage should score HIGHER than the same pitch vs a hitter who crushes that family.
    weak = M.matchup_score(pitcher_whiff=0.35, hitter_whiff=0.40, hitter_slg=0.250)
    strong = M.matchup_score(pitcher_whiff=0.35, hitter_whiff=0.15, hitter_slg=0.600)
    assert weak > strong
    # Zero pitcher whiff -> zero score regardless of hitter
    assert M.matchup_score(0.0, 0.9, 0.1) == 0.0
    print("✓ matchup score: rewards weapons vs vulnerable hitters, direction correct")


def test_build_matchup_join_and_sort():
    arsenals = {100: [
        {"pitch_type": "SL", "pitch_name": "Slider", "family": "Breaking", "usage": 0.4,
         "whiff": 0.60, "putaway": 0.5, "velo": 86.0},
        {"pitch_type": "FF", "pitch_name": "4-Seam FB", "family": "Fastball", "usage": 0.6,
         "whiff": 0.20, "putaway": 0.2, "velo": 95.0},
    ]}
    hitter_splits = {200: {
        "Breaking": {"whiff": 0.45, "slg": 0.230, "xwoba": 0.250, "pitches": 120},
        "Fastball": {"whiff": 0.12, "slg": 0.580, "xwoba": 0.390, "pitches": 300},
    }}
    rows = M.build_matchup(100, 200, arsenals, hitter_splits)
    assert len(rows) == 2
    # Slider (high pitcher whiff, hitter weak vs breaking) should sort first
    assert rows[0]["pitch_type"] == "SL" and rows[0]["score"] >= rows[1]["score"]
    # Missing hitter -> scores are None, no crash
    empty = M.build_matchup(100, 999, arsenals, hitter_splits)
    assert all(r["score"] is None for r in empty)
    print("✓ build_matchup: joins arsenal to splits, sorts by score, handles missing hitter")


def test_empty_inputs_dont_crash():
    assert M.build_pitcher_arsenal(pd.DataFrame()).empty
    assert M.build_hitter_splits(pd.DataFrame()).empty
    assert M.build_matchup(1, 2, {}, {}) == []
    print("✓ empty inputs return empty, no crash")


def test_hitter_pitch_type_splits():
    ht = M.build_hitter_pitch_type_splits(_mock_pitches())
    # batter 200 saw 40 FF and 40 SL — both clear MIN_PITCHES_TYPE, so both should appear by type
    types = set(ht[ht["batter"] == 200]["pitch_type"])
    assert "FF" in types and "SL" in types
    sl = ht[(ht["batter"] == 200) & (ht["pitch_type"] == "SL")].iloc[0]
    # SL whiff = 18/30 swings = 60%; SLG = 6 TB / 24 ABs = .250 (same as the breaking family here)
    assert abs(sl["whiff"] - 0.60) < 1e-6 and abs(sl["slg"] - 0.25) < 1e-6
    assert sl["pitch_name"] == "Slider" and sl["family"] == "Breaking"
    # a pitch below MIN_PITCHES_TYPE should be dropped
    extra = pd.DataFrame([{"batter": 200, "pitcher": 100, "pitch_type": "KN", "release_speed": 70,
                           "strikes": 0, "description": "ball", "events": "",
                           "estimated_woba_using_speedangle": None} for _ in range(10)])
    ht2 = M.build_hitter_pitch_type_splits(pd.concat([_mock_pitches(), extra], ignore_index=True))
    assert "KN" not in set(ht2["pitch_type"])
    print("✓ hitter pitch-type splits: per-pitch whiff/SLG, sample floor, names")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t(); passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
