"""
test_statcast.py — offline tests for the Statcast layer (no Savant, no pybaseball).

    python test_statcast.py     # or: pytest test_statcast.py
"""

import os
import tempfile

import numpy as np
import pandas as pd

import projections as P
import statcast_data as SC


def _write_cache(tmp):
    df = pd.DataFrame([
        dict(player_id=1, name="Elite Barrel", pa=600, brl_pa=0.115, brl_pct=0.22,
             hardhit=0.60, avg_ev=95.8, slg=0.620, xslg=0.640, xiso=0.330),
        dict(player_id=2, name="League Avg", pa=550, brl_pa=0.055, brl_pct=0.08,
             hardhit=0.40, avg_ev=89.0, slg=0.420, xslg=0.415, xiso=0.155),
        dict(player_id=3, name="Slap", pa=500, brl_pa=0.015, brl_pct=0.03,
             hardhit=0.25, avg_ev=86.0, slg=0.350, xslg=0.345, xiso=0.075),
        dict(player_id=4, name="Low PA Noise", pa=40, brl_pa=0.250, brl_pct=0.45,
             hardhit=0.70, avg_ev=99.0, slg=0.800, xslg=0.520, xiso=0.260),
    ])
    path = os.path.join(tmp, "statcast_batters.csv")
    df.to_csv(path, index=False)
    return path


def test_load_and_calibration():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_cache(tmp)
        lookup, k = SC.load(path)
        assert len(lookup) == 4
        assert k is not None and 0.4 < k < 0.8           # plausible barrel->HR factor
        # elite barrels map to a much higher expected HR rate than a slap hitter
        assert SC.expected_hr_rate(lookup[1]["brl_pa"], k) > SC.expected_hr_rate(lookup[3]["brl_pa"], k)


def test_low_pa_excluded_from_calibration():
    # The 40-PA noise guy's 0.25 brl_pa must not drag the league mean (and thus k).
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_cache(tmp)
        _, k = SC.load(path)
        # mean of qualified brl_pa = (0.115+0.055+0.015)/3 = 0.0617 -> k = 0.033/0.0617 ~ 0.535
        assert abs(k - 0.535) < 0.05


def test_missing_file_is_graceful():
    lookup, k = SC.load("/no/such/file.csv")
    assert lookup == {} and k is None


def test_xhr_from_statcast_lookup():
    sc = {99: {"brl_pa": 0.10}}
    assert abs(P.xhr_from_statcast(99, sc, 0.6) - 0.06) < 1e-9
    assert P.xhr_from_statcast(99, sc, None) is None      # no calibration
    assert P.xhr_from_statcast(7, sc, 0.6) is None         # not in lookup
    assert P.xhr_from_statcast(None, sc, 0.6) is None


def test_statcast_regresses_cold_masher_up():
    # Elite contact, cold HR results -> Statcast prior should raise HR probability.
    cold = dict(plateAppearances=500, atBats=450, hits=130, doubles=30, triples=1,
                homeRuns=12, baseOnBalls=45, strikeOuts=110)
    rng = np.random.default_rng(1)
    base = P.batter_pa_probs(cold, P.NEUTRAL_PARK)              # league prior
    juiced = P.batter_pa_probs(cold, P.NEUTRAL_PARK, xhr_pa=0.059)  # barrel-implied prior
    assert juiced[P.HR] > base[P.HR]


def test_statcast_regresses_lucky_hitter_down():
    lucky = dict(plateAppearances=500, atBats=450, hits=120, doubles=20, triples=0,
                 homeRuns=28, baseOnBalls=45, strikeOuts=120)
    base = P.batter_pa_probs(lucky, P.NEUTRAL_PARK)
    pulled = P.batter_pa_probs(lucky, P.NEUTRAL_PARK, xhr_pa=0.024)
    assert pulled[P.HR] < base[P.HR]


# ----------------------------------------------------------------- woba/xwoba + regression table
def _write_cache_with_woba(tmp):
    df = pd.DataFrame([
        # Underperforming his contact quality (wOBA well below xwOBA) -> "due for positive regression"
        dict(player_id=10, name="Cold But Crushing It", pa=300, brl_pa=0.10, brl_pct=0.20,
            hardhit=0.55, avg_ev=93.0, slg=0.400, xslg=0.480, xiso=0.180,
            woba=0.310, xwoba=0.365),
        # Overperforming his contact quality (wOBA well above xwOBA) -> "due for negative regression"
        dict(player_id=11, name="Hot But Empty Contact", pa=300, brl_pa=0.03, brl_pct=0.05,
            hardhit=0.25, avg_ev=87.0, slg=0.380, xslg=0.330, xiso=0.090,
            woba=0.360, xwoba=0.300),
        # Results in line with contact quality -> no real signal
        dict(player_id=12, name="Steady", pa=300, brl_pa=0.07, brl_pct=0.12,
            hardhit=0.40, avg_ev=90.0, slg=0.420, xslg=0.415, xiso=0.150,
            woba=0.330, xwoba=0.328),
        # Below the PA floor -> excluded regardless of how extreme the delta looks
        dict(player_id=13, name="Small Sample", pa=40, brl_pa=0.20, brl_pct=0.35,
            hardhit=0.65, avg_ev=96.0, slg=0.700, xslg=0.500, xiso=0.250,
            woba=0.420, xwoba=0.310),
    ])
    path = os.path.join(tmp, "statcast_batters.csv")
    df.to_csv(path, index=False)
    return path


def test_load_extracts_woba_and_xwoba():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_cache_with_woba(tmp)
        lookup, _k = SC.load(path)
    assert lookup[10]["woba"] == 0.310 and lookup[10]["xwoba"] == 0.365
    print("✓ load() correctly extracts both actual and expected wOBA")


def test_regression_table_flags_underperforming_hitter_for_positive_regression():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_cache_with_woba(tmp)
        lookup, _k = SC.load(path)
    rows = [{"Hitter": "Cold But Crushing It", "_pid": 10, "Team": "NYY"}]
    table = SC.build_hitter_regression_table(rows, lookup)
    assert len(table) == 1
    assert table[0]["Delta"] < 0
    assert "positive regression" in table[0]["Tag"]
    print("✓ a hitter underperforming his contact quality is correctly flagged for positive regression")


def test_regression_table_flags_overperforming_hitter_for_negative_regression():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_cache_with_woba(tmp)
        lookup, _k = SC.load(path)
    rows = [{"Hitter": "Hot But Empty Contact", "_pid": 11, "Team": "BOS"}]
    table = SC.build_hitter_regression_table(rows, lookup)
    assert table[0]["Delta"] > 0
    assert "negative regression" in table[0]["Tag"]
    print("✓ a hitter outperforming his contact quality is correctly flagged for negative regression")


def test_regression_table_steady_hitter_no_signal():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_cache_with_woba(tmp)
        lookup, _k = SC.load(path)
    rows = [{"Hitter": "Steady", "_pid": 12, "Team": "LAD"}]
    table = SC.build_hitter_regression_table(rows, lookup)
    assert "in line" in table[0]["Tag"]


def test_regression_table_excludes_below_pa_floor():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_cache_with_woba(tmp)
        lookup, _k = SC.load(path)
    rows = [{"Hitter": "Small Sample", "_pid": 13, "Team": "SF"}]
    table = SC.build_hitter_regression_table(rows, lookup)
    assert table == []   # 40 PA < MIN_PA_QUALIFIED, correctly excluded despite the extreme delta
    print("✓ build_hitter_regression_table correctly excludes hitters below the PA floor")


def test_regression_table_excludes_hitter_with_no_statcast_data():
    rows = [{"Hitter": "Not In Cache", "_pid": 999, "Team": "SEA"}]
    assert SC.build_hitter_regression_table(rows, {}) == []


def test_regression_table_excludes_stale_cache_missing_woba_field():
    # A cache written BEFORE this feature existed has no woba/xwoba columns at all — load()
    # defaults those to 0.0, and this must be treated as "no real data" (skip), not a fabricated
    # 0.000 vs 0.000 "perfectly in line" or a nonsensical extreme delta.
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_cache(tmp)   # the OLD helper, no woba/xwoba columns
        lookup, _k = SC.load(path)
    rows = [{"Hitter": "Elite Barrel", "_pid": 1, "Team": "NYY"}]
    assert SC.build_hitter_regression_table(rows, lookup) == []
    print("✓ build_hitter_regression_table correctly skips a pre-refresh cache instead of fabricating a 0.000 signal")


def test_regression_table_sorted_by_absolute_delta_both_directions():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_cache_with_woba(tmp)
        lookup, _k = SC.load(path)
    rows = [
        {"Hitter": "Steady", "_pid": 12, "Team": "LAD"},
        {"Hitter": "Cold But Crushing It", "_pid": 10, "Team": "NYY"},
        {"Hitter": "Hot But Empty Contact", "_pid": 11, "Team": "BOS"},
    ]
    table = SC.build_hitter_regression_table(rows, lookup)
    names = [t["Hitter"] for t in table]
    assert names[0] in ("Cold But Crushing It", "Hot But Empty Contact")   # biggest |delta| first
    assert names[-1] == "Steady"   # smallest |delta| last
    print("✓ build_hitter_regression_table sorts by absolute delta, surfacing both directions' extremes first")


# ----------------------------------------------------------------- catcher framing
def _write_catcher_framing_cache(tmp):
    df = pd.DataFrame([
        dict(player_id=1, name="Good Framer", team="NYY", called_pitches=4000,
            strike_rate=0.550, framing_runs=15.0),
        dict(player_id=2, name="Backup Catcher", team="NYY", called_pitches=800,
            strike_rate=0.480, framing_runs=1.0),
        dict(player_id=3, name="Bad Framer", team="BOS", called_pitches=3500,
            strike_rate=0.470, framing_runs=-12.0),
        dict(player_id=4, name="Unqualified", team="LAD", called_pitches=0,
            strike_rate=0.0, framing_runs=0.0),
    ])
    path = os.path.join(tmp, "catcher_framing.csv")
    df.to_csv(path, index=False)
    return path


def test_load_catcher_framing_reads_cache():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_catcher_framing_cache(tmp)
        lookup = SC.load_catcher_framing(path)
    assert lookup[1]["name"] == "Good Framer"
    assert lookup[1]["framing_runs"] == 15.0
    print("✓ load_catcher_framing correctly reads a cached CSV")


def test_load_catcher_framing_missing_file_graceful():
    assert SC.load_catcher_framing("/nonexistent/path.csv") == {}


def test_team_catcher_framing_weights_by_called_pitches():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_catcher_framing_cache(tmp)
        lookup = SC.load_catcher_framing(path)
    result = SC.team_catcher_framing(lookup, "NYY")
    assert result is not None
    # weighted average: (0.550*4000 + 0.480*800) / 4800
    expected = (0.550 * 4000 + 0.480 * 800) / 4800
    assert abs(result["strike_rate"] - round(expected, 4)) < 1e-6
    assert result["framing_runs"] == 16.0   # 15.0 + 1.0, summed not averaged
    assert len(result["catchers"]) == 2
    print("✓ team_catcher_framing correctly weights strike rate by called-pitch volume across the whole corps")


def test_team_catcher_framing_none_when_team_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_catcher_framing_cache(tmp)
        lookup = SC.load_catcher_framing(path)
    assert SC.team_catcher_framing(lookup, "SEA") is None
    print("✓ team_catcher_framing returns None rather than a fabricated average for an unmatched team")


def test_team_catcher_framing_none_when_all_unqualified():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_catcher_framing_cache(tmp)
        lookup = SC.load_catcher_framing(path)
    assert SC.team_catcher_framing(lookup, "LAD") is None   # only catcher has 0 called_pitches
    print("✓ team_catcher_framing returns None when every matching catcher has zero real sample")


def test_build_catcher_frame_resilient_to_column_names():
    # Confirms the resilient _series-based parsing handles the confirmed real column (rv_tot)
    # alongside hedged candidates for the less-certain ones.
    raw = pd.DataFrame([
        {"player_id": 5, "last_name, first_name": "Realmuto, J.T.", "team": "PHI",
        "n_called_pitches": 5000, "strike_rate": 0.52, "rv_tot": 10.0},
    ])
    out = SC._build_catcher_frame(raw)
    assert out.iloc[0]["player_id"] == 5
    assert out.iloc[0]["framing_runs"] == 10.0
    print("✓ _build_catcher_frame correctly parses the confirmed real rv_tot column alongside hedged candidates")


def test_build_catcher_frame_handles_nan_player_id_without_crashing():
    # A real, plausible crash found by re-reading the code, not just a guess: a raw NaN in the
    # player_id column would have crashed astype(int) outright before the fillna(0) fix.
    raw = pd.DataFrame([
        {"player_id": 5, "last_name, first_name": "Real, Player", "team": "PHI",
        "n_called_pitches": 5000, "strike_rate": 0.52, "rv_tot": 10.0},
        {"player_id": None, "last_name, first_name": "No Id, Player", "team": "PHI",
        "n_called_pitches": 10, "strike_rate": 0.50, "rv_tot": 0.1},
    ])
    out = SC._build_catcher_frame(raw)
    assert len(out) == 1   # the NaN-id row is correctly dropped by the player_id > 0 filter
    assert out.iloc[0]["player_id"] == 5
    print("✓ _build_catcher_frame handles a raw NaN player_id without crashing, dropping that row instead")


def test_refresh_catcher_framing_parse_failure_includes_response_preview(monkeypatch):
    # Regression guard for the real production failure this fix addresses: a parse failure must
    # surface WHAT Savant actually sent back, not just an opaque pandas tokenizing error, so a
    # future failure is diagnosable from the exception message alone.
    #
    # Mocks pd.read_csv directly to fail, rather than trying to construct fake CSV content that
    # organically reproduces pandas' exact "Expected N fields... saw M" C-parser error — that
    # error depends on the C engine's internal chunking behavior in ways that proved genuinely
    # hard to trigger deterministically with synthetic content during test-writing (confirmed by
    # trying — a naive "1-field header then a multi-field row" case did NOT raise on this
    # pandas version). This tests what actually matters: does THIS code's own try/except around
    # read_csv correctly wrap whatever exception occurs with the real response content attached.
    class FakeResponse:
        content = b"Not Found - Baseball Savant returned something other than a CSV this time"
        def raise_for_status(self):
            pass

    import requests as _requests
    monkeypatch.setattr(_requests, "get", lambda *a, **k: FakeResponse())
    monkeypatch.setattr(pd, "read_csv", lambda *a, **k: (_ for _ in ()).throw(
        __import__("pandas").errors.ParserError("Error tokenizing data. C error: Expected 1 fields in line 38, saw 4")))

    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "catcher_framing.csv")
        try:
            SC.refresh_catcher_framing(2026, out_path=out_path)
            raised = False
            msg = ""
        except ValueError as e:
            raised = True
            msg = str(e)
    assert raised
    assert "Not Found" in msg   # the actual response content is visible in the exception
    assert "First 500 chars" in msg
    assert "Expected 1 fields" in msg   # the original pandas error is preserved too
    print("✓ refresh_catcher_framing's parse failure includes a real preview of Savant's actual response")


def test_refresh_catcher_framing_uses_numeric_min_by_default(monkeypatch):
    # Regression guard for the real fix: min_called_p must default to a real number (0), not
    # pybaseball's own "q" string default, which is the prime suspect for the original failure.
    captured = {}

    class FakeResponse:
        content = b"player_id,name,team,n_called_pitches,strike_rate,rv_tot\n1,Test Catcher,NYY,5000,0.52,10.0\n"
        def raise_for_status(self):
            pass

    def fake_get(url, timeout=30):
        captured["url"] = url
        return FakeResponse()

    import requests as _requests
    monkeypatch.setattr(_requests, "get", fake_get)

    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "catcher_framing.csv")
        SC.refresh_catcher_framing(2026, out_path=out_path)
    assert "min=0" in captured["url"]
    assert "min=q" not in captured["url"]
    print("✓ refresh_catcher_framing requests a numeric min_called_p by default, not the string 'q'")


def test_refresh_catcher_framing_warns_on_column_mismatch_data_loss(monkeypatch, capsys):
    # Regression guard for the SECOND real production issue found (after the parse-failure fix
    # resolved the first one): the fetch and CSV parse can both succeed while almost every row
    # still gets silently dropped, if the actual response's column names don't match any of
    # _build_catcher_frame's hedged candidates. A green checkmark run wouldn't reveal this on its
    # own — this test confirms the diagnostic actually fires and includes the REAL column names,
    # not just a generic "something's wrong" message.
    csv_with_unrecognized_columns = "some_id_field,player_name,squad\n" + "\n".join(
        f"{i},Player {i},NYY" for i in range(15)
    )

    class FakeResponse:
        content = csv_with_unrecognized_columns.encode("utf-8")
        def raise_for_status(self):
            pass

    import requests as _requests
    monkeypatch.setattr(_requests, "get", lambda *a, **k: FakeResponse())

    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "catcher_framing.csv")
        SC.refresh_catcher_framing(2026, out_path=out_path, min_called_p=0)
    captured = capsys.readouterr()
    assert "::warning::" in captured.out
    assert "column mapping" in captured.out
    assert "some_id_field" in captured.out   # the REAL raw column names are surfaced, not hidden
    assert "player_name" in captured.out
    print("✓ refresh_catcher_framing warns on silent column-mismatch data loss, surfacing the real raw column names")


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
