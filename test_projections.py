"""
test_projections.py — offline tests for the projection engine (seeded, deterministic).

    python test_projections.py     # or: pytest test_projections.py
"""

import numpy as np
import projections as P


def _slugger():
    return dict(plateAppearances=600, atBats=540, hits=165, doubles=34, triples=2,
                homeRuns=38, baseOnBalls=55, strikeOuts=140)


def test_pa_probs_sum_to_one():
    probs = P.batter_pa_probs(_slugger(), P.NEUTRAL_PARK)
    assert probs is not None
    assert abs(probs.sum() - 1.0) < 1e-9
    assert (probs >= 0).all()


def test_low_sample_returns_none():
    assert P.batter_pa_probs(dict(plateAppearances=10), P.NEUTRAL_PARK) is None


def test_park_boosts_hr_rate():
    neutral = P.batter_pa_probs(_slugger(), P.NEUTRAL_PARK)[P.HR]
    coors = P.batter_pa_probs(_slugger(), P.PARK_FACTORS[7])[P.HR]
    assert coors > neutral  # Coors (venue 7) inflates HR


def test_probabilities_in_range():
    rng = np.random.default_rng(0)
    probs = P.batter_pa_probs(_slugger(), P.NEUTRAL_PARK)
    sim = P.simulate_batter(probs, 4.4, 20000, rng)
    for arr, line in ((sim["tb"], 1.5), (sim["hits"], 0.5), (sim["k"], 0.5)):
        p = float(np.mean(arr > line))
        assert 0.0 <= p <= 1.0
    hr_p = float(np.mean(sim["hr"] >= 1))
    assert 0.15 < hr_p < 0.40  # a 38-HR bat sits in a believable anytime-HR band


def test_pitcher_projection_sane():
    ace = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29,
               strikeOuts=235, baseOnBalls=42)
    proj = P.project_pitcher(ace)
    assert 5.0 < proj["exp_ip"] < 7.0
    assert proj["exp_k"] > proj["exp_bb"]


def test_fair_odds_roundtrip():
    assert P.prob_to_american(0.5) == -100
    assert P.prob_to_decimal(0.5) == 2.0
    # favorite gets negative american, dog positive
    assert P.prob_to_american(0.62) < 0
    assert P.prob_to_american(0.30) > 0


def test_build_signals_shape():
    row = {"Hitter": "X", "Team": "T", "GameLabel": "A @ B", "Opp Pitcher": "P",
           "Lineup": "Confirmed", "_stat": _slugger(), "_exp_pa": 4.4, "_venue_id": None}

    class PM:
        id = 1; name = "Ace"
        stat = dict(battersFaced=700, inningsPitched="170.0", gamesStarted=28,
                    strikeOuts=200, baseOnBalls=50)
    meta = [{"label": "A @ B", "home_name": "B", "away_name": "A", "home_pm": PM(), "away_pm": PM()}]
    sigs = P.build_signals([row], meta, sims=8000, seed=1)
    # 4 batter markets + 3 pitcher markets * 2 pitchers = 10
    assert len(sigs) == 10
    for s in sigs:
        assert 0.0 <= s["ModelProb"] <= 1.0
        assert s["FairDec"] is None or s["FairDec"] >= 1.0


def test_starter_gate_skips_relievers():
    # Pure reliever (no starts) listed as a probable -> must be skipped, not projected.
    assert P.project_pitcher(dict(battersFaced=45, inningsPitched="11.0",
                                  gamesStarted=0, strikeOuts=18, baseOnBalls=9)) is None
    # Too-thin starter sample -> skipped.
    assert P.project_pitcher(dict(battersFaced=50, inningsPitched="12.0",
                                  gamesStarted=2, strikeOuts=17, baseOnBalls=8)) is None


def test_shrinkage_tames_hot_small_sample():
    # 3 starts, 15 IP, 40% raw K rate. Pre-fix this exploded toward ~8.5+ K.
    proj = P.project_pitcher(dict(battersFaced=63, inningsPitched="15.0",
                                  gamesStarted=3, strikeOuts=25, baseOnBalls=4))
    assert proj is not None
    assert proj["exp_k"] < 7.0   # regressed, not inflated
    # And never above the clamp ceiling.
    assert proj["exp_k"] <= 0.45 * proj["exp_bf"] + 1e-9


def test_real_ace_stays_sane():
    proj = P.project_pitcher(dict(battersFaced=720, inningsPitched="180.0",
                                  gamesStarted=29, strikeOuts=235, baseOnBalls=42))
    assert 5.5 < proj["exp_ip"] < 7.0
    assert 6.0 < proj["exp_k"] < 9.5      # believable ace strikeout projection
    assert proj["exp_bb"] < 3.0


def test_batter_shrinkage_pulls_small_samples():
    # A 40-PA hot callup's HR rate must regress well below its raw 0.125.
    hot = P.batter_pa_probs(dict(plateAppearances=40, atBats=36, hits=16, doubles=4,
                                 triples=0, homeRuns=5, baseOnBalls=4, strikeOuts=6),
                            P.NEUTRAL_PARK)
    assert hot[P.HR] < 0.07          # far below raw 5/40 = 0.125
    # A full-season slugger barely moves.
    slug = P.batter_pa_probs(dict(plateAppearances=600, atBats=540, hits=165, doubles=34,
                                  triples=2, homeRuns=38, baseOnBalls=55, strikeOuts=140),
                             P.NEUTRAL_PARK)
    assert slug[P.HR] > 0.05         # still clearly an above-average power bat


def test_odds_ratio_identity():
    # League bat vs league pitcher at league rate must return league rate.
    assert abs(P.odds_ratio(0.033, 0.033, 0.033) - 0.033) < 1e-6
    # Better pitcher (lower allowed) pushes the matchup probability down.
    assert P.odds_ratio(0.065, 0.020, 0.033) < P.odds_ratio(0.065, 0.045, 0.033)


def test_matchup_moves_hr_with_pitcher_quality():
    slug = _slugger()
    hr_prone = dict(battersFaced=700, homeRuns=28, strikeOuts=120, baseOnBalls=70, hits=180)
    ace = dict(battersFaced=700, homeRuns=10, strikeOuts=210, baseOnBalls=40, hits=130)
    p_easy = P.batter_pa_probs(slug, P.NEUTRAL_PARK, opp_allowed=P.pitcher_allowed_rates(hr_prone))
    p_hard = P.batter_pa_probs(slug, P.NEUTRAL_PARK, opp_allowed=P.pitcher_allowed_rates(ace))
    # Same hitter projects for MORE HR vs the homer-prone arm, FEWER vs the ace.
    assert p_easy[P.HR] > p_hard[P.HR]
    # And more strikeouts vs the high-K ace.
    assert p_hard[P.K] > p_easy[P.K]


def test_pitcher_allowed_rates_guards():
    assert P.pitcher_allowed_rates(None) is None
    assert P.pitcher_allowed_rates(dict(battersFaced=10)) is None  # too thin


def test_handedness_split_applies():
    slug = _slugger()
    vs_r = dict(plateAppearances=420, atBats=380, hits=130, doubles=28, triples=1,
                homeRuns=32, baseOnBalls=35, strikeOuts=80)
    vs_l = dict(plateAppearances=180, atBats=165, hits=35, doubles=6, triples=0,
                homeRuns=6, baseOnBalls=12, strikeOuts=55)
    p_vsR = P.batter_pa_probs(slug, P.NEUTRAL_PARK, split_stat=vs_r)
    p_vsL = P.batter_pa_probs(slug, P.NEUTRAL_PARK, split_stat=vs_l)
    assert p_vsR[P.HR] > p_vsL[P.HR]   # mashes RHP
    assert p_vsL[P.K] > p_vsR[P.K]     # whiffs vs LHP
    # A tiny split sample barely moves the season rate (shrinkage).
    tiny = dict(plateAppearances=8, atBats=7, hits=5, doubles=2, triples=0,
                homeRuns=3, baseOnBalls=1, strikeOuts=1)
    base = P.batter_pa_probs(slug, P.NEUTRAL_PARK)
    p_tiny = P.batter_pa_probs(slug, P.NEUTRAL_PARK, split_stat=tiny)
    assert abs(p_tiny[P.HR] - base[P.HR]) < 0.01


def test_lineup_k_bb_rates():
    whiff = [dict(plateAppearances=600, strikeOuts=180, baseOnBalls=45) for _ in range(9)]
    rates = P.lineup_k_bb_rates(whiff)
    assert 0.25 < rates["k"] < 0.32          # ~30% K lineup
    # thin lineup data -> None (falls back to neutral)
    assert P.lineup_k_bb_rates([dict(plateAppearances=10, strikeOuts=3, baseOnBalls=1)]) is None


def test_pitcher_matchup_moves_strikeouts():
    ace = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29, strikeOuts=235, baseOnBalls=42)
    whiff = P.lineup_k_bb_rates([dict(plateAppearances=600, strikeOuts=180, baseOnBalls=45) for _ in range(9)])
    contact = P.lineup_k_bb_rates([dict(plateAppearances=600, strikeOuts=90, baseOnBalls=45) for _ in range(9)])
    k_vs_whiff = P.project_pitcher(ace, whiff)["exp_k"]
    k_neutral = P.project_pitcher(ace)["exp_k"]
    k_vs_contact = P.project_pitcher(ace, contact)["exp_k"]
    assert k_vs_whiff > k_neutral > k_vs_contact


def test_pitcher_matchup_moves_walks():
    ace = dict(battersFaced=720, inningsPitched="180.0", gamesStarted=29, strikeOuts=235, baseOnBalls=42)
    patient = P.lineup_k_bb_rates([dict(plateAppearances=600, strikeOuts=120, baseOnBalls=80) for _ in range(9)])
    hacker = P.lineup_k_bb_rates([dict(plateAppearances=600, strikeOuts=120, baseOnBalls=25) for _ in range(9)])
    assert P.project_pitcher(ace, patient)["exp_bb"] > P.project_pitcher(ace, hacker)["exp_bb"]


def test_lineup_rate_map():
    rows = [
        {"GameLabel": "A @ B", "Team": "A", "_stat": dict(plateAppearances=600, strikeOuts=150, baseOnBalls=50)},
        {"GameLabel": "A @ B", "Team": "A", "_stat": dict(plateAppearances=600, strikeOuts=120, baseOnBalls=60)},
    ]
    m = P.build_lineup_rate_map(rows)
    assert ("A @ B", "A") in m
    assert m[("A @ B", "A")] is None or "k" in m[("A @ B", "A")]


def test_favored_side():
    # over above reference -> Over; below -> Under (with complemented prob/ref)
    assert P._favored_side(0.30, 0.11)[0] == "Over"
    side, sp, refs = P._favored_side(0.30, 0.62)   # 30% over a 62% baseline -> Under is the lean
    assert side == "Under" and abs(sp - 0.70) < 1e-9 and abs(refs - 0.38) < 1e-9


def test_build_best_bets_ranks_and_reasons():
    hitters = [
        dict(Hitter="Slugger", Team="A", GameLabel="A @ B", Hand="L",
             **{"Opp Hand": "R", "Opp Pitcher": "Ace"}, Advantage="Advantage",
             _weather_hr=1.12, Due=0.03, **{"HR%": 0.22, "TB1.5%": 0.49, "Hit%": 0.70, "SO Prob": 0.55}),
    ]
    pitchers = [
        dict(Pitcher="Whiff Ace", Team="B", Opp="A",
             **{"K over%": 0.74, "Outs over%": 0.58, "BB over%": 0.30},
             **{"Proj K": 9.2, "Proj BB": 1.6, "Proj IP": 6.2, "Proj Outs": 18.6},
             _opp_k=0.265, _opp_bb=0.07, _game="A @ B"),
    ]
    plays = P.build_best_bets(hitters, pitchers)
    assert plays, "should produce plays"
    # sorted by conviction descending
    convs = [p["Conviction"] for p in plays]
    assert convs == sorted(convs, reverse=True)
    # the slugger HR over should be the top conviction play and carry reasoning
    top = plays[0]
    assert top["Market"] == "Batter HR" and top["Side"] == "Over"
    assert "platoon" in top["Why"] and "weather" in top["Why"]
    # no "won't homer" plays
    assert not any(p["Market"] == "Batter HR" and p["Side"] == "Under" for p in plays)


# ----------------------------------------------------------------- build_bullpen_matchup_rows
def _hitter_row_for_bullpen_test(team, opp_stat):
    return {
        "Hitter": "Test Slugger", "Team": team, "_pid": 1, "_stat": _slugger(),
        "_opp_stat": opp_stat, "_venue_id": None, "_split_stat": None,
        "_exp_pa": 4.25, "_weather_hr": 1.0,
    }


def test_bullpen_matchup_rows_only_touches_the_target_teams_rows():
    home_row = _hitter_row_for_bullpen_test("Home", dict(battersFaced=700, homeRuns=15,
                                                         strikeOuts=150, baseOnBalls=50, hits=150))
    away_row = _hitter_row_for_bullpen_test("Away", dict(battersFaced=700, homeRuns=15,
                                                         strikeOuts=150, baseOnBalls=50, hits=150))
    bullpen_stat = dict(battersFaced=700, homeRuns=10, strikeOuts=210, baseOnBalls=40, hits=130)
    out = P.build_bullpen_matchup_rows([home_row, away_row], "Away", bullpen_stat, seed=1)
    assert len(out) == 1 and out[0]["Team"] == "Away"   # Home's row never appears in the output
    print("✓ build_bullpen_matchup_rows only recomputes rows for the requested opponent team")


def test_bullpen_matchup_rows_never_mutates_original_rows():
    starter_stat = dict(battersFaced=700, homeRuns=28, strikeOuts=120, baseOnBalls=70, hits=180)
    away_row = _hitter_row_for_bullpen_test("Away", starter_stat)
    bullpen_stat = dict(battersFaced=700, homeRuns=10, strikeOuts=210, baseOnBalls=40, hits=130)
    P.build_bullpen_matchup_rows([away_row], "Away", bullpen_stat, seed=1)
    assert away_row["_opp_stat"] is starter_stat   # original row's _opp_stat untouched
    assert "HR%" not in away_row   # enrich_hitter_rows mutates in place — the COPY, not the original
    print("✓ build_bullpen_matchup_rows works on copies, never mutating the original slate rows")


def test_bullpen_matchup_rows_produces_a_genuinely_different_read_than_the_starter():
    # THE actual point of the toggle: a hitter who looks tough to homer against the ace should
    # look like a real, different (easier) matchup once the bullpen_stat is a homer-prone pen.
    away_row = _hitter_row_for_bullpen_test(
        "Away", dict(battersFaced=700, homeRuns=10, strikeOuts=210, baseOnBalls=40, hits=130))  # vs ace
    bullpen_stat = dict(battersFaced=700, homeRuns=28, strikeOuts=120, baseOnBalls=70, hits=180)  # homer-prone pen
    starter_read = P.enrich_hitter_rows([dict(away_row)], seed=1)
    bullpen_read = P.build_bullpen_matchup_rows([away_row], "Away", bullpen_stat, seed=1)
    assert bullpen_read[0]["HR%"] > starter_read[0]["HR%"]
    print("✓ build_bullpen_matchup_rows produces a genuinely different (and correctly higher, "
         "vs. a homer-prone pen) HR% than the same hitter's vs-starter read")


# ----------------------------------------------------------------- times_through_order
def test_times_through_order_basic():
    assert P.times_through_order(27.0) == 3.0    # exactly 3 full trips through a 9-batter lineup
    assert P.times_through_order(18.0) == 2.0
    assert P.times_through_order(22.5) == 2.5     # partial trip, a real fractional read


def test_times_through_order_custom_lineup_size():
    assert P.times_through_order(24.0, lineup_size=8) == 3.0


def test_times_through_order_zero_lineup_size_safe():
    assert P.times_through_order(20.0, lineup_size=0) == 0.0


# ----------------------------------------------------------------- build_pitcher_projection_rows
def _fake_pm(pid, name, hand, era, fip, stat):
    from types import SimpleNamespace
    return SimpleNamespace(id=pid, name=name, hand=hand, era=era, fip=fip, stat=stat)


def test_build_pitcher_projection_rows_includes_tto_and_team_id():
    ace_stat = dict(gamesStarted=20, inningsPitched="120.0", battersFaced=480,
                    strikeOuts=140, baseOnBalls=35)
    hp = _fake_pm(111, "Home Ace", "R", 3.20, 3.10, ace_stat)
    ap = _fake_pm(222, "Away Ace", "L", 3.80, 3.70, ace_stat)
    meta = [{"label": "Away @ Home", "home_name": "Home", "away_name": "Away",
            "home_id": 117, "away_id": 111, "home_pm": hp, "away_pm": ap, "game_date": None}]
    rows = []   # empty lineup rate map -> neutral matchup, still projects fine
    out = P.build_pitcher_projection_rows(rows, meta, sims=2000, seed=1)
    assert len(out) == 2
    home_row = next(r for r in out if r["Pitcher"] == "Home Ace")
    assert "Proj TTO" in home_row
    assert home_row["Proj TTO"] == round(home_row["Proj BF"] / 9, 2)
    assert home_row["_team_id"] == 117   # the home pitcher's OWN team id, not the opponent's
    away_row = next(r for r in out if r["Pitcher"] == "Away Ace")
    assert away_row["_team_id"] == 111
    print("✓ build_pitcher_projection_rows includes Proj TTO (matching Proj BF / 9) and each pitcher's own _team_id")


# ----------------------------------------------------------------- hitter_starter_exposures
def test_hitter_starter_exposures_leadoff_sees_starter_multiple_times():
    # Leadoff (idx=0) comes up as batter #1, #10, #19, #28... A starter projecting 27 BF means
    # the leadoff hitter faces him 3 full times (batters 1, 10, 19 all <= 27).
    exp = P.hitter_starter_exposures(lineup_idx=0, starter_proj_bf=27.0, exp_pa=4.25)
    assert exp["vs_starter"] == 3.0
    assert round(exp["vs_starter"] + exp["vs_bullpen"], 2) == 4.25
    print("✓ hitter_starter_exposures correctly gives the leadoff hitter 3 starter exposures at 27 projected BF")


def test_hitter_starter_exposures_bottom_of_order_sees_starter_less():
    # 9-hole (idx=8) comes up as batter #9, #18, #27... Same 27 BF starter -> only reaches him
    # for the 3rd time right at the edge (batter 27), still 3, but with much less BUFFER than
    # the leadoff hitter — the real, well-known "bottom of the order sees the starter less" effect
    # should show up as LESS bullpen-vs-starter margin, not necessarily a different raw count here.
    top = P.hitter_starter_exposures(lineup_idx=0, starter_proj_bf=20.0, exp_pa=4.25)
    bottom = P.hitter_starter_exposures(lineup_idx=8, starter_proj_bf=20.0, exp_pa=4.25)
    assert top["vs_starter"] > bottom["vs_starter"]
    print("✓ hitter_starter_exposures correctly gives a bottom-of-the-order hitter fewer starter looks than a leadoff hitter, same starter")


def test_hitter_starter_exposures_short_start_means_mostly_bullpen():
    # A starter projecting only 12 BF still reaches the leadoff hitter's SECOND PA (batter #10,
    # since 10 <= 12) — a real, correct consequence of the math, not a bug: even a short-ish start
    # gives the top of the order a second look. A genuinely short start (6 BF) is needed before
    # someone at the bottom of the order (8th spot, batter #8) gets zero starter exposure at all.
    leadoff = P.hitter_starter_exposures(lineup_idx=0, starter_proj_bf=12.0, exp_pa=4.25)
    assert leadoff["vs_starter"] == 2.0   # batters 1 and 10 both <= 12
    late = P.hitter_starter_exposures(lineup_idx=7, starter_proj_bf=6.0, exp_pa=4.25)
    assert late["vs_starter"] == 0.0 and late["vs_bullpen"] == 4.25
    print("✓ hitter_starter_exposures correctly sends a hitter entirely to the bullpen when the starter's own projected work doesn't reach them at all")


def test_hitter_starter_exposures_caps_at_exp_pa():
    # vs_starter can never exceed the hitter's own total expected PA, even if the arithmetic
    # would otherwise suggest more exposures than plate appearances physically available.
    exp = P.hitter_starter_exposures(lineup_idx=0, starter_proj_bf=999.0, exp_pa=4.25)
    assert exp["vs_starter"] == 4.25 and exp["vs_bullpen"] == 0.0


def test_hitter_starter_exposures_always_sums_to_exp_pa():
    for idx in range(9):
        for bf in (12.0, 18.0, 22.5, 27.0, 33.0):
            exp = P.hitter_starter_exposures(lineup_idx=idx, starter_proj_bf=bf, exp_pa=4.25)
            assert round(exp["vs_starter"] + exp["vs_bullpen"], 2) == 4.25
    print("✓ hitter_starter_exposures' two components always sum back to the hitter's own exp_pa")


def test_hitter_starter_exposures_zero_exp_pa_safe():
    exp = P.hitter_starter_exposures(lineup_idx=0, starter_proj_bf=27.0, exp_pa=0.0)
    assert exp == {"vs_starter": 0.0, "vs_bullpen": 0.0}


# ----------------------------------------------------------------- add_starter_exposure_context
def _ace_stat():
    return dict(gamesStarted=20, inningsPitched="120.0", battersFaced=480,
               strikeOuts=140, baseOnBalls=35)


def test_add_starter_exposure_context_adds_vs_sp_and_vs_pen():
    row = {"Hitter": "Leadoff Guy", "_opp_stat": _ace_stat(), "_exp_pa": 4.25, "_lineup_idx": 0}
    out = P.add_starter_exposure_context([row])
    assert "vs SP" in out[0] and "vs Pen" in out[0]
    assert round(out[0]["vs SP"] + out[0]["vs Pen"], 2) == 4.25
    print("✓ add_starter_exposure_context adds vs SP / vs Pen fields that sum to the hitter's own exp_pa")


def test_add_starter_exposure_context_shares_projection_across_same_opponent():
    # Two hitters facing the SAME starter (same stat dict) should get project_pitcher called
    # only ONCE, not once per hitter — confirmed via a real call-count check, not just asserted.
    shared_stat = _ace_stat()
    rows = [
        {"Hitter": "Leadoff", "_opp_stat": shared_stat, "_exp_pa": 4.25, "_lineup_idx": 0},
        {"Hitter": "Cleanup", "_opp_stat": shared_stat, "_exp_pa": 4.25, "_lineup_idx": 3},
    ]
    calls = {"n": 0}
    real_project_pitcher = P.project_pitcher

    def counting_project_pitcher(stat, opp_lineup=None):
        calls["n"] += 1
        return real_project_pitcher(stat, opp_lineup)

    orig = P.project_pitcher
    P.project_pitcher = counting_project_pitcher
    try:
        P.add_starter_exposure_context(rows)
    finally:
        P.project_pitcher = orig
    assert calls["n"] == 1
    print("✓ add_starter_exposure_context computes the starter projection once per opponent, not once per hitter")


def test_add_starter_exposure_context_skips_rows_missing_data():
    rows = [
        {"Hitter": "No Opp Stat", "_exp_pa": 4.25, "_lineup_idx": 0},
        {"Hitter": "No Exp PA", "_opp_stat": _ace_stat(), "_lineup_idx": 0},
        {"Hitter": "No Lineup Idx", "_opp_stat": _ace_stat(), "_exp_pa": 4.25},
    ]
    out = P.add_starter_exposure_context(rows)
    for r in out:
        assert "vs SP" not in r and "vs Pen" not in r
    print("✓ add_starter_exposure_context leaves rows with missing data honestly unset, no fabricated split")


def test_add_starter_exposure_context_skips_when_not_a_real_starter():
    thin_stat = dict(gamesStarted=1, inningsPitched="2.0", battersFaced=10, strikeOuts=2, baseOnBalls=1)
    row = {"Hitter": "Test", "_opp_stat": thin_stat, "_exp_pa": 4.25, "_lineup_idx": 0}
    out = P.add_starter_exposure_context([row])
    assert "vs SP" not in out[0]   # project_pitcher's own starter gate correctly returns None here


# ----------------------------------------------------------------- blend_hitter_probs_with_bullpen
def _blendable_row(lineup_idx=0, exp_pa=4.25, opp_stat=None, weather_hr=1.0):
    return {
        "Hitter": "Test Slugger", "_pid": 1, "_stat": _slugger(), "_venue_id": None,
        "_opp_stat": opp_stat or dict(gamesStarted=20, inningsPitched="120.0", battersFaced=480,
                                     strikeOuts=140, baseOnBalls=35, homeRuns=8, hits=95),
        "_split_stat": None, "_exp_pa": exp_pa, "_weather_hr": weather_hr, "_lineup_idx": lineup_idx,
    }


def test_blend_reproduces_real_slate_direction_ace_starter_weak_pen():
    # A rough reproduction of the real, reported scenario: a genuinely BAD starter (high HR/K
    # allowed) with a short projected outing, and a MUCH BETTER bullpen. The blended HR%
    # should come out LOWER than a starter-only read would show, not higher and not identical —
    # confirming the correction moves in the right direction on a case shaped like the real one.
    bad_starter_stat = dict(gamesStarted=15, inningsPitched="70.0", battersFaced=380,
                            strikeOuts=55, baseOnBalls=40, homeRuns=22, hits=110)  # ~7+ ERA shape
    good_pen_stat = dict(strikeOuts=300, baseOnBalls=90, hitByPitch=10, homeRuns=35,
                         battersFaced=1800, hits=380, atBats=1600, earnedRuns=180,
                         inningsPitched="450.0")  # a much better run-prevention shape
    row = _blendable_row(lineup_idx=0, exp_pa=4.55, opp_stat=bad_starter_stat)

    starter_only = P.enrich_hitter_rows([dict(row)], seed=7)[0]
    blended = P.blend_hitter_probs_with_bullpen(row, good_pen_stat, seed=7)

    assert blended is not None
    assert blended["HR%"] < starter_only["HR%"]
    print(f"✓ blend_hitter_probs_with_bullpen correctly lowers HR% ({starter_only['HR%']:.3f} -> "
         f"{blended['HR%']:.3f}) when the real bullpen is meaningfully better than a bad starter, "
         f"matching the direction of the real reported case")


def test_blend_returns_none_when_no_bullpen_exposure():
    # A leadoff hitter with a LOW exp_pa (3.0, artificially trimmed for this test) against a
    # starter genuinely projected to cover the whole game (exp_bf=30, well past 3 full trips
    # through a 9-batter lineup) leaves zero real bullpen exposure — hand-verified via
    # hitter_starter_exposures directly: exposures_to_starter = floor((30-0-1)/9)+1 = 4, capped
    # at min(4, 3.0) = 3.0, so vs_pen = 3.0 - 3.0 = 0. Nothing to blend, starter-only is correct.
    workhorse_stat = dict(gamesStarted=30, inningsPitched="220.0", battersFaced=900,
                          strikeOuts=200, baseOnBalls=50, homeRuns=15, hits=180)
    row = _blendable_row(lineup_idx=0, exp_pa=3.0, opp_stat=workhorse_stat)
    pen_stat = dict(strikeOuts=300, baseOnBalls=90, hitByPitch=10, homeRuns=35,
                    battersFaced=1800, hits=380, atBats=1600, earnedRuns=180, inningsPitched="450.0")
    result = P.blend_hitter_probs_with_bullpen(row, pen_stat, seed=1)
    assert result is None
    print("✓ blend_hitter_probs_with_bullpen correctly returns None when there's no real bullpen exposure to blend")


def test_blend_none_when_row_not_projectable():
    row = _blendable_row()
    row["_stat"] = None   # can't project this hitter at all
    pen_stat = dict(strikeOuts=300, baseOnBalls=90, hitByPitch=10, homeRuns=35,
                    battersFaced=1800, hits=380, atBats=1600, earnedRuns=180, inningsPitched="450.0")
    assert P.blend_hitter_probs_with_bullpen(row, pen_stat, seed=1) is None


def test_blend_none_when_starter_not_projectable():
    # {"gamesStarted": 1} — real dict, so it survives the fixture's own `opp_stat or dict(...)`
    # fallback (an empty {} would be falsy and get silently replaced, a real mistake caught while
    # writing this test) — but still genuinely fails project_pitcher's own gs>=3 starter gate.
    row = _blendable_row(opp_stat={"gamesStarted": 1, "inningsPitched": "4.0", "battersFaced": 18})
    pen_stat = dict(strikeOuts=300, baseOnBalls=90, hitByPitch=10, homeRuns=35,
                    battersFaced=1800, hits=380, atBats=1600, earnedRuns=180, inningsPitched="450.0")
    assert P.blend_hitter_probs_with_bullpen(row, pen_stat, seed=1) is None
    print("✓ blend_hitter_probs_with_bullpen correctly returns None when the opposing starter can't be projected")


def test_blend_none_when_bullpen_stat_too_thin():
    row = _blendable_row()
    thin_pen_stat = dict(strikeOuts=5, baseOnBalls=2, homeRuns=1, battersFaced=20, hits=6)  # < 40 BF floor
    assert P.blend_hitter_probs_with_bullpen(row, thin_pen_stat, seed=1) is None
    print("✓ blend_hitter_probs_with_bullpen correctly returns None for a bullpen sample too thin to trust")


def test_blend_vs_sp_vs_pen_sum_to_exp_pa():
    row = _blendable_row(lineup_idx=0, exp_pa=4.55)
    pen_stat = dict(strikeOuts=300, baseOnBalls=90, hitByPitch=10, homeRuns=35,
                    battersFaced=1800, hits=380, atBats=1600, earnedRuns=180, inningsPitched="450.0")
    result = P.blend_hitter_probs_with_bullpen(row, pen_stat, seed=1)
    assert result is not None
    assert round(result["vs SP"] + result["vs Pen"], 2) == 4.55


def test_blend_is_deterministic_with_same_seed():
    row = _blendable_row()
    pen_stat = dict(strikeOuts=300, baseOnBalls=90, hitByPitch=10, homeRuns=35,
                    battersFaced=1800, hits=380, atBats=1600, earnedRuns=180, inningsPitched="450.0")
    r1 = P.blend_hitter_probs_with_bullpen(row, pen_stat, seed=42)
    r2 = P.blend_hitter_probs_with_bullpen(row, pen_stat, seed=42)
    assert r1 == r2


# ----------------------------------------------------------------- apply_bullpen_blend_to_top_plays
def _hr_play(player_id, conviction, side="Over"):
    return {"Player": f"P{player_id}", "PlayerId": player_id, "Market": "Batter HR",
           "Side": side, "Line": 0.5, "ModelProb": 0.30, "Fair": -100,
           "Conviction": conviction, "Why": "some reason"}


def _pitcher_play(conviction):
    return {"Player": "Some Pitcher", "PlayerId": 999, "Market": "Pitcher Strikeouts",
           "Side": "Over", "Line": 5.5, "ModelProb": 0.55, "Fair": -110,
           "Conviction": conviction, "Why": "projects X K"}


def _bad_starter_row(pid, opp_id, lineup_idx=0):
    r = _blendable_row(lineup_idx=lineup_idx, exp_pa=4.55,
                       opp_stat=dict(gamesStarted=15, inningsPitched="70.0", battersFaced=380,
                                    strikeOuts=55, baseOnBalls=40, homeRuns=22, hits=110))
    r["_pid"] = pid
    r["_opp_id"] = opp_id
    return r


_GOOD_PEN_STAT = dict(strikeOuts=300, baseOnBalls=90, hitByPitch=10, homeRuns=35,
                      battersFaced=1800, hits=380, atBats=1600, earnedRuns=180, inningsPitched="450.0")


def test_apply_blend_updates_top_candidate_and_preserves_side():
    play = _hr_play(1, conviction=4.25)
    row = _bad_starter_row(1, opp_id=114)
    calls = []

    def fake_get_bullpen(team_id, exclude_pid):
        calls.append(team_id)
        return _GOOD_PEN_STAT

    out = P.apply_bullpen_blend_to_top_plays([play], {1: row}, fake_get_bullpen, seed=7)
    assert out[0]["_bullpen_blended"] is True
    assert out[0]["_pre_blend_conviction"] == 4.25
    assert out[0]["Conviction"] != 4.25   # actually recomputed, not left untouched
    assert out[0]["Side"] == "Over"        # side preserved, not re-derived
    assert "bullpen-blended" in out[0]["Why"]
    assert calls == [114]
    print("✓ apply_bullpen_blend_to_top_plays correctly updates a top candidate and preserves its existing side")


def test_apply_blend_respects_top_n_limit():
    plays = [_hr_play(i, conviction=10 - i) for i in range(5)]   # 5 plays, descending conviction
    rows = {i: _bad_starter_row(i, opp_id=100 + i) for i in range(5)}
    calls = []

    def fake_get_bullpen(team_id, exclude_pid):
        calls.append(team_id)
        return _GOOD_PEN_STAT

    P.apply_bullpen_blend_to_top_plays(plays, rows, fake_get_bullpen, seed=1, top_n=2)
    blended = [p for p in plays if p.get("_bullpen_blended")]
    assert len(blended) == 2   # only the top 2 by conviction got touched
    assert set(calls) == {100, 101}   # only the top 2 hitters' opponents were ever looked up
    print("✓ apply_bullpen_blend_to_top_plays respects top_n, never fetching bullpen data beyond it")


def test_apply_blend_never_touches_non_hitter_markets():
    plays = [_pitcher_play(conviction=5.0)]
    out = P.apply_bullpen_blend_to_top_plays(plays, {}, lambda tid, ex: _GOOD_PEN_STAT, seed=1)
    assert "_bullpen_blended" not in out[0]
    assert out[0]["Conviction"] == 5.0
    print("✓ apply_bullpen_blend_to_top_plays never touches pitcher-market plays")


def test_apply_blend_leaves_play_unchanged_when_no_matching_row():
    play = _hr_play(1, conviction=4.25)
    out = P.apply_bullpen_blend_to_top_plays([play], {}, lambda tid, ex: _GOOD_PEN_STAT, seed=1)
    assert "_bullpen_blended" not in out[0]
    assert out[0]["Conviction"] == 4.25


def test_apply_blend_leaves_play_unchanged_when_no_opp_id():
    play = _hr_play(1, conviction=4.25)
    row = _bad_starter_row(1, opp_id=None)
    out = P.apply_bullpen_blend_to_top_plays([play], {1: row}, lambda tid, ex: _GOOD_PEN_STAT, seed=1)
    assert "_bullpen_blended" not in out[0]


def test_apply_blend_leaves_play_unchanged_when_bullpen_lookup_returns_none():
    play = _hr_play(1, conviction=4.25)
    row = _bad_starter_row(1, opp_id=114)
    out = P.apply_bullpen_blend_to_top_plays([play], {1: row}, lambda tid, ex: None, seed=1)
    assert "_bullpen_blended" not in out[0]
    assert out[0]["Conviction"] == 4.25
    print("✓ apply_bullpen_blend_to_top_plays leaves a play untouched when the bullpen lookup itself fails")


def test_apply_blend_leaves_play_unchanged_when_no_real_exposure():
    # A hitter with zero real bullpen exposure (the common case) — blend_hitter_probs_with_
    # bullpen itself returns None, and this must be handled the same as any other None case.
    row = _blendable_row(lineup_idx=0, exp_pa=3.0,
                         opp_stat=dict(gamesStarted=30, inningsPitched="220.0", battersFaced=900,
                                      strikeOuts=200, baseOnBalls=50, homeRuns=15, hits=180))
    row["_pid"] = 1
    row["_opp_id"] = 114
    play = _hr_play(1, conviction=4.25)
    out = P.apply_bullpen_blend_to_top_plays([play], {1: row}, lambda tid, ex: _GOOD_PEN_STAT, seed=1)
    assert "_bullpen_blended" not in out[0]
    assert out[0]["Conviction"] == 4.25
    print("✓ apply_bullpen_blend_to_top_plays correctly leaves the common no-exposure case untouched")


def test_apply_blend_resorts_by_updated_conviction():
    # Play A starts with LOWER conviction but gets no real blend adjustment (no bullpen data
    # available for its opponent); Play B starts with HIGHER conviction but its blend correctly
    # lowers it. After blending, A should end up ranked ABOVE B.
    play_a = _hr_play(1, conviction=3.0)
    play_b = _hr_play(2, conviction=5.0)
    row_a = _bad_starter_row(1, opp_id=None)   # no opp_id -> never touched, stays at 3.0
    row_b = _bad_starter_row(2, opp_id=114)    # gets blended down

    out = P.apply_bullpen_blend_to_top_plays([play_a, play_b], {1: row_a, 2: row_b},
                                             lambda tid, ex: _GOOD_PEN_STAT, seed=7)
    assert out[0]["PlayerId"] == 1   # A is now ranked first after B's conviction dropped
    print("✓ apply_bullpen_blend_to_top_plays correctly re-sorts when blending changes the ranking")


# ----------------------------------------------------------------- conviction_to_grade
def test_conviction_to_grade_thresholds():
    assert P.conviction_to_grade(3.5) == {"letter": "A", "tier": "Top Lean", "conviction": 3.5}
    assert P.conviction_to_grade(3.0) == {"letter": "A", "tier": "Top Lean", "conviction": 3.0}
    assert P.conviction_to_grade(2.99) == {"letter": "B", "tier": "Strong Lean", "conviction": 2.99}
    assert P.conviction_to_grade(2.0) == {"letter": "B", "tier": "Strong Lean", "conviction": 2.0}
    assert P.conviction_to_grade(1.99) == {"letter": "C", "tier": "Lean", "conviction": 1.99}
    assert P.conviction_to_grade(1.5) == {"letter": "C", "tier": "Lean", "conviction": 1.5}
    assert P.conviction_to_grade(1.49) == {"letter": "D", "tier": "Watch", "conviction": 1.49}
    assert P.conviction_to_grade(1.2) == {"letter": "D", "tier": "Watch", "conviction": 1.2}
    print("✓ conviction_to_grade correctly applies threshold boundaries")


def test_conviction_to_grade_none_below_floor():
    assert P.conviction_to_grade(1.19) is None
    assert P.conviction_to_grade(0.5) is None
    assert P.conviction_to_grade(0.0) is None
    print("✓ conviction_to_grade returns None below the real floor, not a fabricated low grade")


def test_conviction_to_grade_none_for_none_input():
    assert P.conviction_to_grade(None) is None


# ----------------------------------------------------------------- organize_graded_picks
def _pick(player, team, game, conviction, market="Batter HR"):
    return {"Player": player, "Team": team, "Game": game, "Market": market, "Side": "Over",
           "Line": 0.5, "ModelProb": 0.3, "Fair": -100, "Conviction": conviction, "Why": "x"}


def test_organize_graded_picks_groups_by_game_and_player():
    plays = [
        _pick("A", "TB", "TB @ BOS", 3.5),
        _pick("B", "BOS", "TB @ BOS", 2.0),
        _pick("C", "NYY", "SEA @ NYY", 4.0),
    ]
    result = P.organize_graded_picks(plays)
    assert len(result) == 2
    games = {g["game"]: g for g in result}
    assert len(games["TB @ BOS"]["players"]) == 2
    assert len(games["SEA @ NYY"]["players"]) == 1
    print("✓ organize_graded_picks correctly groups plays by game and by player within each game")


def test_organize_graded_picks_sorts_games_by_best_conviction():
    plays = [
        _pick("A", "TB", "Game Low", 1.3),
        _pick("B", "NYY", "Game High", 4.5),
    ]
    result = P.organize_graded_picks(plays)
    assert result[0]["game"] == "Game High"
    assert result[1]["game"] == "Game Low"
    print("✓ organize_graded_picks sorts games with the most interesting (highest conviction) first")


def test_organize_graded_picks_sorts_players_within_game():
    plays = [
        _pick("Low Player", "TB", "TB @ BOS", 1.3),
        _pick("High Player", "BOS", "TB @ BOS", 3.8),
    ]
    result = P.organize_graded_picks(plays)
    assert result[0]["players"][0]["player"] == "High Player"
    assert result[0]["players"][1]["player"] == "Low Player"


def test_organize_graded_picks_filters_ungraded_plays():
    plays = [
        _pick("Real Play", "TB", "TB @ BOS", 2.0),
        _pick("Too Weak", "TB", "TB @ BOS", 1.0),   # below the 1.2 floor
    ]
    result = P.organize_graded_picks(plays)
    all_players = [p["player"] for g in result for p in g["players"]]
    assert "Real Play" in all_players
    assert "Too Weak" not in all_players
    print("✓ organize_graded_picks correctly excludes plays below the real grading floor")


def test_organize_graded_picks_empty_when_nothing_graded():
    plays = [_pick("A", "TB", "TB @ BOS", 1.0), _pick("B", "TB", "TB @ BOS", 0.8)]
    assert P.organize_graded_picks(plays) == []


def test_organize_graded_picks_each_play_carries_grade():
    plays = [_pick("A", "TB", "TB @ BOS", 3.2)]
    result = P.organize_graded_picks(plays)
    play = result[0]["players"][0]["plays"][0]
    assert play["_grade"] == {"letter": "A", "tier": "Top Lean", "conviction": 3.2}


def test_organize_graded_picks_multiple_plays_per_player_sorted():
    plays = [
        _pick("Multi Play", "TB", "TB @ BOS", 1.5, market="Batter Total Hits"),
        _pick("Multi Play", "TB", "TB @ BOS", 3.0, market="Batter HR"),
    ]
    result = P.organize_graded_picks(plays)
    player_plays = result[0]["players"][0]["plays"]
    assert player_plays[0]["Market"] == "Batter HR"        # higher conviction first
    assert player_plays[1]["Market"] == "Batter Total Hits"
    print("✓ organize_graded_picks sorts a single player's own multiple plays by conviction too")


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
