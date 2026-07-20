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


def _mock_pitches_with_zone_and_ev():
    """30 pitches (clears MIN_PITCHES_ARSENAL) for pitcher 300, pitch FF, with explicit real
    Statcast zone/launch_speed values to hand-verify zone%, contact%, and exit velo against.
    18 in-zone (Statcast zone codes 1-9), 12 out-of-zone (codes 11-14) -> zone% = 0.6.
    15 swings (5 whiff, 6 foul, 4 hit_into_play), 15 non-swings -> whiff = 5/15, contact = 10/15.
    4 balls in play with launch_speed 90/95/100/105 -> avg exit velo = 97.5."""
    zones = ([1, 2, 3, 4, 5, 6, 7, 8, 9] * 2) + ([11, 12, 13, 14] * 3)
    descs = (["swinging_strike"] * 5 + ["foul"] * 6 + ["hit_into_play"] * 4) + (["ball"] * 10 + ["called_strike"] * 5)
    launch_speeds = [None] * 11 + [90.0, 95.0, 100.0, 105.0] + [None] * 15
    rows = [{"pitcher": 300, "batter": 400, "pitch_type": "FF", "release_speed": 94.0,
            "strikes": 0, "zone": zones[i], "description": descs[i], "launch_speed": launch_speeds[i]}
           for i in range(30)]
    return pd.DataFrame(rows)


def test_pitcher_arsenal_zone_pct():
    ars = M.build_pitcher_arsenal(_mock_pitches_with_zone_and_ev())
    row = ars.iloc[0]
    assert abs(row["zone_pct"] - 0.6) < 1e-9
    print("✓ arsenal: zone% correctly computed from Statcast's own zone codes (1-9 in-zone)")


def test_pitcher_arsenal_contact_pct_is_complement_of_whiff():
    ars = M.build_pitcher_arsenal(_mock_pitches_with_zone_and_ev())
    row = ars.iloc[0]
    assert abs(row["whiff"] - 5 / 15) < 1e-9
    assert abs(row["contact_pct"] - 10 / 15) < 1e-9
    assert abs((row["whiff"] + row["contact_pct"]) - 1.0) < 1e-9   # internally consistent by design
    print("✓ arsenal: contact% is the real, internally-consistent complement of whiff%")


def test_pitcher_arsenal_exit_velo():
    ars = M.build_pitcher_arsenal(_mock_pitches_with_zone_and_ev())
    row = ars.iloc[0]
    assert abs(row["exit_velo"] - 97.5) < 1e-9
    print("✓ arsenal: exit velo correctly averages launch_speed on real balls in play only")


def test_pitcher_arsenal_exit_velo_nan_when_no_balls_in_play():
    # A real, honest edge case: a pitch type with real swings/whiffs but zero balls actually put
    # in play must show NaN (no fabricated 0.0 exit velocity), since 0.0 mph would misleadingly
    # read as "hit weakly" rather than "no real sample at all."
    rows = [{"pitcher": 301, "batter": 400, "pitch_type": "SL", "release_speed": 85.0,
            "strikes": 0, "zone": 5, "description": "swinging_strike" if i < 10 else "ball",
            "launch_speed": None} for i in range(30)]
    ars = M.build_pitcher_arsenal(pd.DataFrame(rows))
    row = ars.iloc[0]
    assert pd.isna(row["exit_velo"])
    print("✓ arsenal: exit velo is honestly NaN, never a fabricated 0.0, when there's no real batted-ball sample")


def test_pitcher_arsenal_zone_and_contact_drift_safe_when_columns_missing():
    # The established "drift-safe" pattern this whole file already follows: real Statcast column
    # names occasionally shift between pybaseball versions. zone/launch_speed missing entirely
    # (as in the original _mock_pitches fixture, which predates this feature) must not crash.
    ars = M.build_pitcher_arsenal(_mock_pitches())
    assert "zone_pct" in ars.columns and "contact_pct" in ars.columns and "exit_velo" in ars.columns
    ff = ars[(ars["pitcher"] == 100) & (ars["pitch_type"] == "FF")].iloc[0]
    assert ff["zone_pct"] == 0.0    # no zone data at all -> correctly 0 in-zone pitches, not a crash
    assert pd.isna(ff["exit_velo"])  # no launch_speed data at all -> honestly NaN, not a crash
    print("✓ arsenal: zone%/contact%/exit velo stay drift-safe when the underlying Statcast columns are entirely absent")


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


def test_build_matchup_passes_through_zone_contact_exit_velo():
    arsenals = {100: [
        {"pitch_type": "FF", "pitch_name": "4-Seam FB", "family": "Fastball", "usage": 1.0,
         "whiff": 0.20, "putaway": 0.2, "velo": 95.0,
         "zone_pct": 0.58, "contact_pct": 0.80, "exit_velo": 92.3},
    ]}
    rows = M.build_matchup(100, 999, arsenals, {})   # no hitter splits needed for this check
    assert rows[0]["zone_pct"] == 0.58
    assert rows[0]["contact_pct"] == 0.80
    assert rows[0]["exit_velo"] == 92.3
    print("✓ build_matchup correctly passes through zone%/contact%/exit velo from the arsenal into its own rows")


def test_build_matchup_exit_velo_none_when_arsenal_lacks_it():
    # A real, honest default: an arsenal entry with no zone_pct/contact_pct/exit_velo keys at
    # all (e.g. an older cached CSV, per load()'s own backward-compatibility handling) must
    # surface ALL THREE as None here, not crash and not fabricate a misleading 0.0 -- a real,
    # confirmed bug found via an actual screenshot: a fabricated 0.0 doesn't just look wrong, it
    # actively misleads once styled (0% contact rate reads as excellent for the pitcher under
    # the reversed colormap, the exact opposite of "no data").
    arsenals = {100: [
        {"pitch_type": "FF", "pitch_name": "4-Seam FB", "family": "Fastball", "usage": 1.0,
         "whiff": 0.20, "putaway": 0.2, "velo": 95.0},   # no zone_pct/contact_pct/exit_velo keys
    ]}
    rows = M.build_matchup(100, 999, arsenals, {})
    assert rows[0]["exit_velo"] is None
    assert rows[0]["zone_pct"] is None
    assert rows[0]["contact_pct"] is None
    print("✓ build_matchup honestly surfaces zone_pct/contact_pct/exit_velo as None when an arsenal entry lacks them, never a fabricated 0.0")


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


# ----------------------------------------------------------------- load() -- no prior direct coverage
def test_load_reads_zone_contact_exit_velo_from_a_real_csv():
    import tempfile
    import os
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "arsenal.csv")
        pd.DataFrame([{"pitcher": 500, "pitch_type": "FF", "pitch_name": "4-Seam FB",
                      "family": "Fastball", "pitches": 100, "usage": 1.0, "whiff": 0.25,
                      "putaway": 0.3, "velo": 95.0, "zone_pct": 0.55, "contact_pct": 0.75,
                      "exit_velo": 91.5}]).to_csv(path, index=False)
        arsenals, _ = M.load(arsenal_path=path, hitter_path="/nonexistent")
        row = arsenals[500][0]
        assert row["zone_pct"] == 0.55
        assert row["contact_pct"] == 0.75
        assert row["exit_velo"] == 91.5
    print("✓ load() correctly reads real zone%/contact%/exit velo values from a real CSV")


def test_load_backward_compatible_with_older_csv_missing_new_columns():
    # A REAL, CONFIRMED regression guard: a cache file written BEFORE this feature existed (no
    # zone_pct/contact_pct/exit_velo columns at all) must still load without crashing, AND must
    # surface all three as honest None -- not the fabricated 0.0 an earlier version of this fix
    # produced, confirmed as a real, live bug via an actual screenshot (Zone%/Contact% showing
    # 0% and getting colored as if that were real, excellent data for the pitcher, when it
    # actually meant "no data at all"). Same drift-safe posture this whole module already
    # follows for pybaseball's own occasional column drift, now applied honestly to values too.
    import tempfile
    import os
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "old_arsenal.csv")
        pd.DataFrame([{"pitcher": 501, "pitch_type": "SL", "pitch_name": "Slider",
                      "family": "Breaking", "pitches": 80, "usage": 1.0, "whiff": 0.40,
                      "putaway": 0.5, "velo": 86.0}]).to_csv(path, index=False)   # OLD schema
        arsenals, _ = M.load(arsenal_path=path, hitter_path="/nonexistent")
        row = arsenals[501][0]
        assert row["zone_pct"] is None   # honestly absent, never a fabricated 0.0
        assert row["contact_pct"] is None
        assert row["exit_velo"] is None
    print("✓ load() stays backward-compatible with a cached CSV written before this feature existed")


def test_load_exit_velo_none_when_csv_has_real_nan():
    # Distinguishes the TWO real reasons exit_velo could be missing: an old CSV (tested above,
    # -> None) vs a current-schema CSV where THIS specific pitch genuinely had no batted-ball
    # sample (a real NaN value present in the column) -- both should surface as None to the
    # caller, since the distinction between "column absent" and "column present but empty for
    # this row" isn't meaningful once it reaches the view layer.
    import tempfile
    import os
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "arsenal.csv")
        pd.DataFrame([{"pitcher": 502, "pitch_type": "CU", "pitch_name": "Curveball",
                      "family": "Breaking", "pitches": 90, "usage": 1.0, "whiff": 0.35,
                      "putaway": 0.4, "velo": 78.0, "zone_pct": 0.5, "contact_pct": 0.65,
                      "exit_velo": float("nan")}]).to_csv(path, index=False)
        arsenals, _ = M.load(arsenal_path=path, hitter_path="/nonexistent")
        row = arsenals[502][0]
        assert row["exit_velo"] is None
    print("✓ load() correctly surfaces a real, current-schema NaN exit_velo as None too")


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
