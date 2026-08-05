"""
test_statcast.py — offline tests for the Statcast layer (no Savant, no pybaseball).

    python test_statcast.py     # or: pytest test_statcast.py
"""

import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

import projections as P
import statcast_data as SC

_HERE = Path(__file__).parent


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


# ----------------------------------------------------------------- load_cached
def test_load_cached_returns_same_shape_as_load():
    # load_cached is a thin @st.cache_data wrapper around load() -- confirms it actually
    # delegates correctly, not just that it exists.
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_cache(tmp)
        lookup, k = SC.load_cached(path)
        assert len(lookup) == 4
        assert k is not None and 0.4 < k < 0.8
    print("✓ load_cached delegates to load() correctly, same real return shape")


def test_load_cached_is_genuinely_cached():
    # THE regression test for the real, confirmed finding this function exists to fix: this
    # exact @st.cache_data(ttl=3600) wrapper around SC.load() used to be independently redefined
    # as a local nested closure in 6 separate places platform-wide (best_bets_data.build_mlb_
    # board, and the views for Pitching Lab, Media Room, Edge Board, Podcast Studio, Dinger
    # Engine) -- Streamlit keys cache_data on a function's own identity, so those 6 identical-
    # bodied wrappers were 6 UNSHARED cache entries, and a single real session visiting several
    # of those pages in a row re-read and re-parsed the same statcast_batters.csv from disk up to
    # 6 separate times. Proven here directly, not just asserted from the decorator being present:
    # call once, then rewrite the SAME path with different content and call again with the
    # IDENTICAL path arg -- a genuine cache hit must return the ORIGINAL (now stale) result.
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_cache(tmp)
        first_lookup, first_k = SC.load_cached(path)
        assert len(first_lookup) == 4

        # Overwrite the same path with a genuinely different dataset (2 rows instead of 4, a
        # different calibration k) -- same file path, so this is purely a caching question.
        df = pd.DataFrame([
            dict(player_id=9, name="New Guy", pa=600, brl_pa=0.100, brl_pct=0.20,
                 hardhit=0.55, avg_ev=94.0, slg=0.500, xslg=0.510, xiso=0.220),
        ])
        df.to_csv(path, index=False)
        second_lookup, second_k = SC.load_cached(path)

    assert len(second_lookup) == 4          # still the FIRST call's 4 rows, not the new 1 row
    assert 9 not in second_lookup           # the new player was never actually read
    assert second_k == first_k              # same k as the first call, not recomputed
    print("✓ load_cached is genuinely cached — a repeated call with the identical path doesn't "
         "re-read the file from disk, confirmed by the file's real content changing underneath it")


def test_every_former_duplicate_call_site_now_uses_load_cached():
    # Regression guard for the consolidation itself, not just that load_cached works in
    # isolation -- a real risk otherwise: load_cached could be perfectly correct and simply not
    # actually adopted everywhere, leaving some pages still paying their own separate, unshared
    # SC.load() cost exactly as before. Checks every one of the 6 real call sites this session
    # confirmed were independently redefining the identical wrapper: best_bets_data.py (the
    # shared board-building pipeline every other page funnels through) and the views for
    # Pitching Lab, Media Room, Edge Board, Podcast Studio, and Dinger Engine. Game Watch's own
    # load_statcast_pitchers is deliberately NOT checked here -- it wraps load_pitchers(), a
    # real, different dataset, correctly left as its own separate cache.
    call_sites = [
        _HERE / "best_bets_data.py",
        _HERE / "views" / "7_#L01f3af_Pitching_Lab.py",
        _HERE / "views" / "21_Media_Room.py",
        _HERE / "views" / "15_#L01f4c8_Edge_Board.py",
        _HERE / "views" / "22_Podcast_Studio.py",
        _HERE / "views" / "8_#L01f4a3_Dinger_Engine.py",
    ]
    for path in call_sites:
        src = path.read_text()
        assert "SC.load_cached(" in src, f"{path.name} must call the shared SC.load_cached(), not a local wrapper"
        assert "def load_statcast():" not in src, f"{path.name} still defines its own local load_statcast wrapper"
    print(f"✓ all {len(call_sites)} former duplicate call sites now use the one shared "
         "statcast_data.load_cached(), none still define their own local wrapper")


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
        dict(player_id=1, name="Good Framer", team_id=147, team="New York Yankees", called_pitches=4000,
            strike_rate=0.550, framing_runs=15.0),
        dict(player_id=2, name="Backup Catcher", team_id=147, team="New York Yankees", called_pitches=800,
            strike_rate=0.480, framing_runs=1.0),
        dict(player_id=3, name="Bad Framer", team_id=111, team="Boston Red Sox", called_pitches=3500,
            strike_rate=0.470, framing_runs=-12.0),
        dict(player_id=4, name="Unqualified", team_id=119, team="Los Angeles Dodgers", called_pitches=0,
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
    assert lookup[1]["team_id"] == 147
    print("✓ load_catcher_framing correctly reads a cached CSV, including the enriched team_id")


def test_load_catcher_framing_missing_file_graceful():
    assert SC.load_catcher_framing("/nonexistent/path.csv") == {}


def test_load_catcher_framing_team_id_none_when_column_absent():
    # A cache written BEFORE the team-enrichment step ran (or before this feature existed) has
    # no team_id column at all — must come back as None, not a fabricated 0 that could
    # coincidentally match some real team's id.
    df = pd.DataFrame([dict(player_id=1, name="No Team Yet", called_pitches=500,
                           strike_rate=0.50, framing_runs=1.0)])
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "catcher_framing.csv")
        df.to_csv(path, index=False)
        lookup = SC.load_catcher_framing(path)
    assert lookup[1]["team_id"] is None
    print("✓ load_catcher_framing gives an honest None team_id, not a fabricated 0, for a pre-enrichment cache")


def test_team_catcher_framing_weights_by_called_pitches():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_catcher_framing_cache(tmp)
        lookup = SC.load_catcher_framing(path)
    result = SC.team_catcher_framing(lookup, 147)
    assert result is not None
    # weighted average: (0.550*4000 + 0.480*800) / 4800
    expected = (0.550 * 4000 + 0.480 * 800) / 4800
    assert abs(result["strike_rate"] - round(expected, 4)) < 1e-6
    assert result["framing_runs"] == 16.0   # 15.0 + 1.0, summed not averaged
    assert len(result["catchers"]) == 2
    assert result["team"] == "New York Yankees"   # display name still correctly surfaced
    print("✓ team_catcher_framing correctly weights strike rate by called-pitch volume across the whole corps")


def test_team_catcher_framing_none_when_team_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_catcher_framing_cache(tmp)
        lookup = SC.load_catcher_framing(path)
    assert SC.team_catcher_framing(lookup, 999) is None
    print("✓ team_catcher_framing returns None rather than a fabricated average for an unmatched team")


def test_team_catcher_framing_none_when_all_unqualified():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_catcher_framing_cache(tmp)
        lookup = SC.load_catcher_framing(path)
    assert SC.team_catcher_framing(lookup, 119) is None   # only catcher has 0 called_pitches
    print("✓ team_catcher_framing returns None when every matching catcher has zero real sample")


def test_team_catcher_framing_none_when_team_id_falsy():
    # Regression guard for the real bug: pitcher.get("_team_id") can legitimately be None if
    # that field isn't populated — must not silently match against everything.
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_catcher_framing_cache(tmp)
        lookup = SC.load_catcher_framing(path)
    assert SC.team_catcher_framing(lookup, None) is None
    print("✓ team_catcher_framing returns None for a falsy team_id rather than matching everything")


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


def test_build_pitcher_statcast_frame_basic():
    xs = pd.DataFrame([
        dict(player_id=501, name="Ace, Real", pa=650, era=2.80, xera=3.10, woba=0.280, xwoba=0.295),
        dict(player_id=502, name="Lucky, Guy", pa=600, era=3.20, xera=4.40, woba=0.300, xwoba=0.360),
    ])
    out = SC._build_pitcher_statcast_frame(xs)
    assert len(out) == 2
    row = out[out["player_id"] == 501].iloc[0]
    assert row["name"] == "Real Ace"   # "Last, First" flipped, same _build_name convention as batters
    assert abs(row["era"] - 2.80) < 1e-9 and abs(row["xera"] - 3.10) < 1e-9
    print("✓ _build_pitcher_statcast_frame parses a real-shaped expected-stats leaderboard correctly")


def test_build_pitcher_statcast_frame_missing_id_column_raises():
    xs = pd.DataFrame([dict(name="No Id Guy", era=3.00, xera=3.20)])
    try:
        SC._build_pitcher_statcast_frame(xs)
        assert False, "should have raised KeyError for a missing player-id column"
    except KeyError as e:
        assert "player-id column not found" in str(e)
    print("✓ _build_pitcher_statcast_frame raises a real, informative error on a missing id column rather than silently returning empty")


def test_build_pitcher_statcast_frame_empty_raises():
    xs = pd.DataFrame([dict(player_id=None, name="Bad Row", era=3.00, xera=3.20)])
    try:
        SC._build_pitcher_statcast_frame(xs)
        assert False, "should have raised ValueError for zero valid rows"
    except ValueError as e:
        assert "no valid player_id rows" in str(e)


def test_load_pitchers_missing_file_is_graceful():
    assert SC.load_pitchers("/no/such/pitcher/file.csv") == {}
    print("✓ load_pitchers returns {} (not a crash) when the cache file doesn't exist yet")


def test_load_pitchers_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        df = pd.DataFrame([
            dict(player_id=501, name="Real Ace", pa=650, era=2.80, xera=3.10, woba=0.280, xwoba=0.295),
        ])
        path = os.path.join(tmp, "statcast_pitchers.csv")
        df.to_csv(path, index=False)
        lookup = SC.load_pitchers(path)
        assert len(lookup) == 1
        assert lookup[501]["name"] == "Real Ace"
        assert abs(lookup[501]["era"] - 2.80) < 1e-9
        assert abs(lookup[501]["xera"] - 3.10) < 1e-9
    print("✓ load_pitchers round-trips a real cached CSV correctly")


def test_load_pitchers_empty_file_is_graceful():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "empty.csv")
        pd.DataFrame([]).to_csv(path, index=False)
        assert SC.load_pitchers(path) == {}


def test_statcast_data_importable_without_streamlit():
    # THE real, confirmed production incident this guards against directly: refresh_statcast.py
    # (a standalone script, run by refresh-statcast.yml's own real, deliberately minimal
    # environment -- pybaseball/pandas/requests/pytz only, "the app stays lightweight" per that
    # workflow's own real comment) imports statcast_data, which used to unconditionally `import
    # streamlit as st` at module level -- added later for load_cached's own real @st.cache_data
    # decorator, but never made optional. Confirmed directly from a real cron failure:
    # ModuleNotFoundError: No module named 'streamlit', before a single line of this module's
    # own real Statcast logic ever ran.
    #
    # Reproduced directly here, not just asserted from source text -- genuinely blocks the real
    # streamlit import (the same failure mode refresh-statcast's own minimal environment hits)
    # and confirms the module still imports cleanly, with its real, actually-used functions
    # (load/refresh, what refresh_statcast.py itself calls) still real and callable, and
    # load_cached (streamlit-only, never called by refresh_statcast.py) correctly absent rather
    # than crashing the whole module.
    import builtins
    import sys

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "streamlit" or name.startswith("streamlit."):
            raise ImportError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    saved_modules = {m: sys.modules[m] for m in list(sys.modules)
                     if "streamlit" in m or m == "statcast_data"}
    for m in saved_modules:
        del sys.modules[m]
    builtins.__import__ = _blocked_import
    try:
        import statcast_data as SC_no_streamlit
        assert SC_no_streamlit.st is None, "st must be honestly None when streamlit isn't installed, not crash the import"
        assert not hasattr(SC_no_streamlit, "load_cached"), (
            "load_cached must not be defined at all without streamlit -- it's never called by "
            "refresh_statcast.py, and referencing st.cache_data without a real st would crash")
        assert callable(SC_no_streamlit.load), "load() -- what refresh_statcast.py actually calls -- must still work"
        assert callable(SC_no_streamlit.refresh), "refresh() -- what refresh_statcast.py actually calls -- must still work"
    finally:
        builtins.__import__ = real_import
        for m in list(sys.modules):
            if "streamlit" in m or m == "statcast_data":
                del sys.modules[m]
        sys.modules.update(saved_modules)
        import statcast_data  # noqa: F401 -- restore the real, normal module for every test after this one
    print("✓ statcast_data.py imports cleanly without streamlit installed, with its real, "
         "actually-used functions intact — the exact real production failure this guards against")


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
