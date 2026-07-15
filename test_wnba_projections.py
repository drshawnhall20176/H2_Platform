"""
test_wnba_projections.py — offline tests for the WNBA bootstrap projection model + its
compatibility with odds_api.compute_edges (the actual integration point Edge Board depends on).

    python test_wnba_projections.py     # or: pytest test_wnba_projections.py
"""

import numpy as np

import wnba_projections as WP
import odds_api as O


def _row(name, team, opp, game, log, game_date="2026-07-13T23:00:00Z"):
    return {"Player": name, "Team": team, "Opp": opp, "GameLabel": game,
           "_game_log": log, "_game_date": game_date}


def _log(pts, reb, ast, fg3m):
    return {"pts": pts, "reb": reb, "ast": ast, "fg3m": fg3m, "min": 30}


# ----------------------------------------------------------------- _dist
def test_dist_normalizes_to_probability():
    samples = np.array([1, 1, 2, 3, 3, 3])
    dist = WP._dist(samples)
    assert abs(dist.sum() - 1.0) < 1e-9
    assert dist[3] == 3 / 6      # value 3 appeared 3 of 6 times


def test_dist_empty_returns_empty():
    assert WP._dist(np.array([], dtype=np.int64)).size == 0


# ----------------------------------------------------------------- simulate_player_stat
def test_simulate_player_stat_converges_to_sample_mean():
    rng = np.random.default_rng(7)
    values = [10, 12, 14, 16, 18]   # mean 14
    sim = WP.simulate_player_stat(values, sims=50000, rng=rng)
    assert len(sim) == 50000
    assert abs(sim.mean() - 14) < 0.5     # bootstrap mean should converge close to the sample mean
    assert sim.min() >= 0


def test_simulate_player_stat_empty_input():
    rng = np.random.default_rng(1)
    assert WP.simulate_player_stat([], sims=100, rng=rng).size == 0


# ----------------------------------------------------------------- build_projection_index
def test_build_projection_index_covers_all_four_markets():
    log = [_log(20, 5, 4, 2)] * 8
    rows = [_row("A. Player", "Atlanta Dream", "Chicago Sky", "Chicago Sky @ Atlanta Dream", log)]
    index = WP.build_projection_index(rows, meta=[], sims=5000, seed=3)

    nm = WP.normalize_name("A. Player")
    for mkey in ("player_points", "player_rebounds", "player_assists", "player_threes"):
        assert (nm, mkey) in index, f"missing {mkey} in index"
        entry = index[(nm, mkey)]
        assert abs(entry["dist"].sum() - 1.0) < 1e-9
        assert entry["ctx"]["player"] == "A. Player"
        assert entry["ctx"]["team"] == "Atlanta Dream"
        assert entry["ctx"]["opp"] == "Chicago Sky"
    print("✓ all 4 Core markets present in the index with valid distributions and context")


def test_build_projection_index_skips_players_with_no_log():
    rows = [_row("No Log", "Atlanta Dream", "Chicago Sky", "Chicago Sky @ Atlanta Dream", [])]
    index = WP.build_projection_index(rows, meta=[], sims=1000, seed=1)
    assert index == {}


# ----------------------------------------------------------------- default_board_from_index
def test_default_board_uses_expected_display_names_and_lines():
    # Realistic game-to-game variance including one off night (8 pts) below the 12.5 default
    # line, so this exercises a genuine bootstrap probability rather than the (also correct,
    # but less interesting) deterministic p=1.0 case when every historical game clears the line.
    log = [_log(p, 3, 2, 4) for p in (22, 28, 24, 30, 8, 26, 23, 27, 25, 21)]
    rows = [_row("Sharp Shooter", "Las Vegas Aces", "Seattle Storm", "Seattle Storm @ Las Vegas Aces", log)]
    index = WP.build_projection_index(rows, meta=[], sims=8000, seed=5)
    board = WP.default_board_from_index(index)

    markets = {b["Market"] for b in board}
    assert markets == {"Points", "Rebounds", "Assists", "Threes Made"}
    pts_row = next(b for b in board if b["Market"] == "Points")
    assert pts_row["Line"] == 12.5          # default line from _MARKET_SPEC
    assert pts_row["Side"] == "Over"        # 9 of 10 games clear a 12.5 line
    assert 0.85 <= pts_row["ModelProb"] <= 0.95   # true bootstrap prob = 9/10, loose band for sim noise
    assert pts_row["FairDec"] is not None and pts_row["FairAm"] is not None
    print("✓ default board produces correct market labels, lines, and a sane favored side")


# ----------------------------------------------------------------- full odds_api integration
def test_compute_edges_works_with_wnba_projections_module():
    # This is the actual integration point Edge Board relies on: odds_api.compute_edges accepts
    # a projections_module and must work identically for WNBA as it already does for MLB.
    log = [_log(18, 6, 5, 2)] * 8
    rows = [_row("Edge Case Player", "New York Liberty", "Connecticut Sun",
                 "Connecticut Sun @ New York Liberty", log)]
    index = WP.build_projection_index(rows, meta=[], sims=10000, seed=9)

    offers = [
        {"market": "player_points", "player": "Edge Case Player", "point": 15.5,
         "over": {"fd": -120}, "under": {"fd": 100}},
        {"market": "player_assists", "player": "Nobody Here", "point": 4.5,
         "over": {"fd": -110}, "under": {"fd": -110}},
    ]
    edges, stats = O.compute_edges(index, offers, projections_module=WP)
    assert stats["matched"] == 1 and stats["unmatched"] == 1
    assert all("EV%" in e for e in edges)
    matched = edges[0]
    assert matched["Player"] == "Edge Case Player"
    assert matched["Team"] == "New York Liberty"
    assert matched["Game"] == "Connecticut Sun @ New York Liberty"
    assert matched["Market"] == "player_points"
    print("✓ odds_api.compute_edges works end-to-end with wnba_projections as the projections_module")


# ----------------------------------------------------------------- _favored_side
def test_favored_side_picks_over_when_prob_above_ref():
    side, prob, ref = WP._favored_side(0.65, 0.5)
    assert side == "Over" and prob == 0.65 and ref == 0.5


def test_favored_side_picks_under_when_prob_below_ref():
    side, prob, ref = WP._favored_side(0.35, 0.5)
    assert side == "Under" and prob == 0.65 and ref == 0.5


# ----------------------------------------------------------------- _player_reasons
def test_player_reasons_reports_hit_rate_and_average():
    values = [20, 18, 22, 19, 21]   # avg 20, all clear a 15.5 line
    why = WP._player_reasons(values, 15.5, "Over")
    assert "cleared 15.5 in 5 of last 5 games" in why
    assert "avg 20.0" in why


def test_player_reasons_handles_empty_log():
    assert WP._player_reasons([], 10.5, "Over") == "no recent-game data available"


# ----------------------------------------------------------------- build_best_bets
def test_build_best_bets_covers_all_four_markets_and_ranks_by_conviction():
    log_hot = [_log(p, 3, 2, 4) for p in (28, 30, 26, 29, 31, 27, 30, 28, 29, 27)]   # very consistent scorer
    rows = [_row("Hot Scorer", "Las Vegas Aces", "Seattle Storm", "Seattle Storm @ Las Vegas Aces", log_hot)]
    plays = WP.build_best_bets(rows, sims=8000, seed=3)

    assert {p["Market"] for p in plays} == {"Points", "Rebounds", "Assists", "Threes Made"}
    assert all(p["Player"] == "Hot Scorer" for p in plays)
    # plays sorted by Conviction, descending
    assert all(plays[i]["Conviction"] >= plays[i + 1]["Conviction"] for i in range(len(plays) - 1))
    pts_play = next(p for p in plays if p["Market"] == "Points")
    assert pts_play["Side"] == "Over"          # a ~28ppg scorer clears the 12.5 default line
    assert pts_play["Conviction"] > 1.0         # meaningfully above the 0.5 reference
    assert "cleared 12.5" in pts_play["Why"]
    print("✓ build_best_bets covers all 4 markets, ranks by conviction, includes recent-form reasoning")


def test_build_best_bets_skips_players_with_no_game_log():
    rows = [_row("No Log", "Atlanta Dream", "Chicago Sky", "Chicago Sky @ Atlanta Dream", [])]
    assert WP.build_best_bets(rows, sims=1000, seed=1) == []


# ----------------------------------------------------------------- explain_miss
def test_explain_miss_no_row_means_not_on_slate():
    assert "never saw this player" in WP.explain_miss(None, "Points")


def test_explain_miss_catchable_when_trending_up():
    # last 3 games well above the fuller-sample average -> catchable
    log = [_log(v, 3, 2, 1) for v in (30, 28, 26, 15, 14, 16, 15, 14, 13, 15)]
    row = {"_game_log": log}
    why = WP.explain_miss(row, "Points")
    assert why.startswith("Catchable")


def test_explain_miss_genuine_outlier_when_no_uptick():
    log = [_log(v, 3, 2, 1) for v in (15, 16, 14, 15, 15, 14, 16, 15, 14, 15)]   # flat, consistent
    row = {"_game_log": log}
    why = WP.explain_miss(row, "Points")
    assert why.startswith("Genuine outlier")


def test_curate_selections_is_reachable_via_wnba_projections():
    # Regression test for a real bug caught by a full-pipeline integration check: Media Room and
    # Podcast Studio call sport.projections.curate_selections(...) uniformly regardless of active
    # sport. curate_selections is genuinely sport-agnostic (already lives in projections.py) but
    # must be re-exported here too, or WNBA pages crash with AttributeError.
    assert hasattr(WP, "curate_selections")
    plays = [{"Market": "Points", "Conviction": 2.0}, {"Market": "Points", "Conviction": 1.5},
             {"Market": "Rebounds", "Conviction": 1.8}]
    out = WP.curate_selections(plays, n=5, per_market_cap=1, rank_key="Conviction")
    assert len(out) == 2   # capped at 1 per market
    print("✓ curate_selections is reachable via wnba_projections (re-exported from projections.py)")


# ----------------------------------------------------------------- _clip_prob
def test_clip_prob_bounds_extremes():
    assert WP._clip_prob(1.0) == 0.98
    assert WP._clip_prob(0.0) == 0.02
    assert WP._clip_prob(1.5) == 0.98   # already out of [0,1] -> still clamped
    assert WP._clip_prob(-0.5) == 0.02


def test_clip_prob_leaves_normal_values_alone():
    assert WP._clip_prob(0.5) == 0.5
    assert WP._clip_prob(0.73) == 0.73


def test_build_best_bets_never_produces_a_none_fair_price():
    # Regression test for a real production crash: a perfectly consistent player (cleared every
    # line in all 10 recent games) drove prob_over to exactly 1.0, so prob_to_american returned
    # None, which broke Best Bets' strict "{:+d}" format string on the Fair column.
    log = [_log(30, 3, 2, 4)] * 10   # identical every game -> would hit prob_over == 1.0 uncapped
    rows = [_row("Perfectly Consistent", "Las Vegas Aces", "Seattle Storm",
                "Seattle Storm @ Las Vegas Aces", log)]
    plays = WP.build_best_bets(rows, sims=8000, seed=5)
    assert plays, "should still produce plays, just capped probabilities"
    for p in plays:
        assert p["Fair"] is not None
        assert 0.0 < p["ModelProb"] < 1.0
        format(p["Fair"], "+d")   # must not raise — this exact call crashed in production
    print("✓ build_best_bets never produces a None Fair price, even for a maximally consistent player")


def test_default_board_from_index_never_produces_prob_at_the_boundary():
    log = [_log(30, 3, 2, 4)] * 10
    rows = [_row("Perfectly Consistent", "Las Vegas Aces", "Seattle Storm",
                "Seattle Storm @ Las Vegas Aces", log)]
    index = WP.build_projection_index(rows, meta=[], sims=8000, seed=5)
    board = WP.default_board_from_index(index)
    for b in board:
        assert 0.0 < b["ModelProb"] < 1.0
        assert b["FairAm"] is not None
    print("✓ default_board_from_index also stays clear of the 0/1 probability boundary")


# ----------------------------------------------------------------- build_hot_hand_board
def test_build_hot_hand_board_tags_plus_matchup_correctly():
    rows = [{"Player": "Star", "Team": "Atlanta Dream", "Opp": "Chicago Sky",
            "GameLabel": "Chicago Sky @ Atlanta Dream", "PTS": 20.0, "REB": 5.0, "AST": 3.0,
            "FG3M": 2.0, "_opp_id": 19}]
    # Two opponents on the slate, pace-adjusted: Chicago Sky allows 99pts/90poss = 110/100poss;
    # Washington Mystics allows 68pts/85poss = 80/100poss. Baseline = (110+80)/2 = 95/100poss.
    # Chicago's rate (110) is well above baseline (95) -> plus matchup, on the RATE, not raw pts.
    opp_allowed = {
        19: {"pts": 99.0, "reb": 34.0, "ast": 19.0, "fg3m": 8.0, "poss": 90.0},   # Chicago Sky
        16: {"pts": 68.0, "reb": 30.0, "ast": 16.0, "fg3m": 6.0, "poss": 85.0},   # Washington Mystics
    }
    board = WP.build_hot_hand_board(rows, opp_allowed)
    pts_row = next(b for b in board if b["Market"] == "Points")
    assert pts_row["Opp Allows"] == 99.0            # raw per-game, unchanged/still shown for context
    assert pts_row["Opp Pace"] == 90.0
    assert pts_row["Opp Allows /100 Poss"] == 110.0  # 99 / 90 * 100
    assert pts_row["Slate Avg /100 Poss"] == 95.0    # (110 + 80) / 2
    assert pts_row["Matchup Factor"] > 1.08
    assert pts_row["Tag"] == "🟢 Plus matchup"
    assert pts_row["Matchup Score"] > pts_row["Recent Avg"]   # boosted above raw recent form
    print("✓ build_hot_hand_board correctly identifies and tags a plus matchup, pace-adjusted")


def test_build_hot_hand_board_pace_adjustment_flips_a_naive_raw_read():
    # The exact conflation the pace fix targets: a fast-paced team can look like a bad defense on
    # RAW allowed totals while actually being average or better per possession, and vice versa.
    # Team 19 allows more raw points but does so over far more possessions (just plays fast) —
    # its true per-possession rate is actually BELOW the slate average, unlike the raw number.
    rows = [{"Player": "Star", "Team": "Atlanta Dream", "Opp": "Fast Team",
            "GameLabel": "Fast Team @ Atlanta Dream", "PTS": 20.0, "REB": 5.0, "AST": 3.0,
            "FG3M": 2.0, "_opp_id": 19}]
    opp_allowed = {
        19: {"pts": 90.0, "reb": 34.0, "ast": 19.0, "fg3m": 8.0, "poss": 100.0},  # fast pace: 90/100poss = 90.0
        16: {"pts": 80.0, "reb": 30.0, "ast": 16.0, "fg3m": 6.0, "poss": 80.0},   # slow pace: 80/80poss = 100.0
    }
    # Raw totals alone (90 vs 80) would flag team 19 as the worse (higher-allowing) defense.
    # Pace-adjusted (90.0 vs 100.0 per-100-poss), team 19 is actually the TIGHTER defense.
    board = WP.build_hot_hand_board(rows, opp_allowed)
    pts_row = next(b for b in board if b["Market"] == "Points")
    assert pts_row["Opp Allows"] == 90.0             # raw number alone looks like the "worse" defense
    assert pts_row["Opp Allows /100 Poss"] == 90.0    # 90 / 100 * 100
    assert pts_row["Slate Avg /100 Poss"] == 95.0     # (90 + 100) / 2
    assert pts_row["Matchup Factor"] < 1.0            # correctly reads as a TOUGHER matchup, not easier
    print("✓ build_hot_hand_board's pace adjustment correctly reverses a naive raw-total read")


def test_build_hot_hand_board_neutral_when_no_opponent_data():
    rows = [{"Player": "Star", "Team": "Atlanta Dream", "Opp": "Unknown Team",
            "GameLabel": "Unknown Team @ Atlanta Dream", "PTS": 20.0, "REB": 5.0, "AST": 3.0,
            "FG3M": 2.0, "_opp_id": 999}]
    board = WP.build_hot_hand_board(rows, opp_allowed={})   # no data for any opponent
    pts_row = next(b for b in board if b["Market"] == "Points")
    assert pts_row["Matchup Factor"] == 1.0
    assert pts_row["Tag"] == "🟡 Neutral"
    assert pts_row["Matchup Score"] == pts_row["Recent Avg"]   # no fabricated boost/penalty
    print("✓ build_hot_hand_board stays neutral (no fabricated signal) when opponent data is missing")


def test_build_hot_hand_board_covers_all_players_and_markets():
    rows = [
        {"Player": "A", "Team": "T1", "Opp": "T2", "GameLabel": "T2 @ T1",
         "PTS": 15.0, "REB": 4.0, "AST": 2.0, "FG3M": 1.0, "_opp_id": 2},
        {"Player": "B", "Team": "T2", "Opp": "T1", "GameLabel": "T2 @ T1",
         "PTS": 12.0, "REB": 6.0, "AST": 5.0, "FG3M": 0.5, "_opp_id": 1},
    ]
    opp_allowed = {1: {"pts": 80.0, "reb": 32.0, "ast": 18.0, "fg3m": 7.0, "poss": 92.0},
                  2: {"pts": 78.0, "reb": 30.0, "ast": 17.0, "fg3m": 6.5, "poss": 90.0}}
    board = WP.build_hot_hand_board(rows, opp_allowed)
    assert len(board) == 8   # 2 players x 4 markets
    assert {b["Player"] for b in board} == {"A", "B"}
    assert {b["Market"] for b in board} == {"Points", "Rebounds", "Assists", "Threes Made"}
    print("✓ build_hot_hand_board covers every player across every market")


# ----------------------------------------------------------------- build_hot_hand_board: rest/B2B
def test_build_hot_hand_board_surfaces_own_team_back_to_back():
    rows = [{"Player": "Star", "Team": "Atlanta Dream", "Opp": "Chicago Sky",
            "GameLabel": "Chicago Sky @ Atlanta Dream", "PTS": 20.0, "REB": 5.0, "AST": 3.0,
            "FG3M": 2.0, "_opp_id": 19, "_team_id": 20}]
    team_rest = {20: {"rest_days": 1, "is_back_to_back": True,
                      "last_game_date": "2026-07-14", "last_opp_name": "New York Liberty"}}
    board = WP.build_hot_hand_board(rows, opp_allowed={}, team_rest=team_rest)
    pts_row = next(b for b in board if b["Market"] == "Points")
    assert pts_row["Rest Days"] == 1
    assert pts_row["B2B"] is True
    print("✓ build_hot_hand_board surfaces the PLAYER'S OWN team's back-to-back status")


def test_build_hot_hand_board_rest_is_the_players_own_team_not_the_opponents():
    # Player's team (20) is well-rested; the OPPONENT (19) is on a back-to-back — the Rest column
    # must reflect team 20 (her own team), not team 19, since fatigue is about her legs.
    rows = [{"Player": "Star", "Team": "Atlanta Dream", "Opp": "Chicago Sky",
            "GameLabel": "Chicago Sky @ Atlanta Dream", "PTS": 20.0, "REB": 5.0, "AST": 3.0,
            "FG3M": 2.0, "_opp_id": 19, "_team_id": 20}]
    team_rest = {20: {"rest_days": 3, "is_back_to_back": False, "last_game_date": None, "last_opp_name": None},
                19: {"rest_days": 1, "is_back_to_back": True, "last_game_date": None, "last_opp_name": None}}
    board = WP.build_hot_hand_board(rows, opp_allowed={}, team_rest=team_rest)
    pts_row = next(b for b in board if b["Market"] == "Points")
    assert pts_row["Rest Days"] == 3
    assert pts_row["B2B"] is False
    print("✓ build_hot_hand_board's Rest column reflects the player's own team, not the opponent's")


def test_build_hot_hand_board_rest_unknown_when_team_rest_omitted():
    rows = [{"Player": "Star", "Team": "Atlanta Dream", "Opp": "Chicago Sky",
            "GameLabel": "Chicago Sky @ Atlanta Dream", "PTS": 20.0, "REB": 5.0, "AST": 3.0,
            "FG3M": 2.0, "_opp_id": 19, "_team_id": 20}]
    board = WP.build_hot_hand_board(rows, opp_allowed={})   # no team_rest passed at all
    pts_row = next(b for b in board if b["Market"] == "Points")
    assert pts_row["Rest Days"] is None
    assert pts_row["B2B"] is False
    print("✓ build_hot_hand_board reports Rest as honestly unknown (not fabricated) when team_rest isn't supplied")


# ----------------------------------------------------------------- build_matchup_profile
def test_build_matchup_profile_covers_all_markets():
    row = {"PTS": 20.0, "REB": 5.0, "AST": 3.0, "FG3M": 2.0}
    profile = WP.build_matchup_profile(row, h2h_log=[], opp_recent_allowed={}, opp_season_allowed={})
    assert {p["Market"] for p in profile} == {"Points", "Rebounds", "Assists", "Threes Made"}
    print("✓ build_matchup_profile covers all 4 markets")


def test_build_matchup_profile_honest_empty_h2h():
    row = {"PTS": 20.0, "REB": 5.0, "AST": 3.0, "FG3M": 2.0}
    profile = WP.build_matchup_profile(row, h2h_log=[], opp_recent_allowed={}, opp_season_allowed={})
    pts = next(p for p in profile if p["Market"] == "Points")
    assert pts["H2H Games"] == 0
    assert pts["H2H Avg"] is None   # never fabricated when teams haven't met
    print("✓ build_matchup_profile honestly reports zero H2H games rather than guessing")


def test_build_matchup_profile_computes_h2h_average():
    row = {"PTS": 20.0, "REB": 5.0, "AST": 3.0, "FG3M": 2.0}
    h2h = [{"pts": 25.0, "reb": 4.0, "ast": 2.0, "fg3m": 3.0},
          {"pts": 19.0, "reb": 6.0, "ast": 4.0, "fg3m": 1.0}]
    profile = WP.build_matchup_profile(row, h2h_log=h2h, opp_recent_allowed={}, opp_season_allowed={})
    pts = next(p for p in profile if p["Market"] == "Points")
    assert pts["H2H Games"] == 2
    assert pts["H2H Avg"] == 22.0
    print("✓ build_matchup_profile correctly averages head-to-head games")


def test_build_matchup_profile_tags_defense_trend_correctly():
    row = {"PTS": 20.0, "REB": 5.0, "AST": 3.0, "FG3M": 2.0}
    # opponent has been allowing MORE lately than their season norm -> looser defense
    looser = WP.build_matchup_profile(row, h2h_log=[],
                                      opp_recent_allowed={"pts": 90.0},
                                      opp_season_allowed={"pts": 80.0})
    pts = next(p for p in looser if p["Market"] == "Points")
    assert pts["Defense Trend"] > 1.08
    assert pts["Trend Tag"] == "📈 Looser lately"

    # opponent has tightened up recently -> lower trend
    tighter = WP.build_matchup_profile(row, h2h_log=[],
                                       opp_recent_allowed={"pts": 70.0},
                                       opp_season_allowed={"pts": 80.0})
    pts2 = next(p for p in tighter if p["Market"] == "Points")
    assert pts2["Defense Trend"] < 0.92
    assert pts2["Trend Tag"] == "📉 Tighter lately"
    print("✓ build_matchup_profile correctly tags looser/tighter defensive trends")


def test_build_matchup_profile_neutral_when_no_season_allowed_data():
    row = {"PTS": 20.0, "REB": 5.0, "AST": 3.0, "FG3M": 2.0}
    profile = WP.build_matchup_profile(row, h2h_log=[], opp_recent_allowed={"pts": 90.0},
                                       opp_season_allowed={})   # no season data -> can't compute a trend
    pts = next(p for p in profile if p["Market"] == "Points")
    assert pts["Defense Trend"] == 1.0
    assert pts["Trend Tag"] == "➡️ Steady"


# ----------------------------------------------------------------- season baseline
def test_build_matchup_profile_reports_season_avg_alongside_recent_and_h2h():
    row = {"PTS": 24.0, "REB": 5.0, "AST": 3.0, "FG3M": 2.0}   # recent form running hot
    season_log = [{"pts": p, "reb": 5, "ast": 3, "fg3m": 2} for p in (18, 20, 19, 21, 20)]  # season norm ~19.6
    profile = WP.build_matchup_profile(row, h2h_log=[], opp_recent_allowed={}, opp_season_allowed={},
                                       season_log=season_log)
    pts = next(p for p in profile if p["Market"] == "Points")
    assert pts["Season Avg"] == 19.6
    assert pts["Recent Avg"] == 24.0   # confirms Season Avg is a genuinely separate baseline
    print("✓ build_matchup_profile reports Season Avg as a real, separate baseline from Recent Avg")


def test_build_matchup_profile_season_avg_none_without_season_log():
    row = {"PTS": 20.0, "REB": 5.0, "AST": 3.0, "FG3M": 2.0}
    profile = WP.build_matchup_profile(row, h2h_log=[], opp_recent_allowed={}, opp_season_allowed={})
    pts = next(p for p in profile if p["Market"] == "Points")
    assert pts["Season Avg"] is None


# ----------------------------------------------------------------- H2H spread / high variance
def test_build_matchup_profile_flags_high_variance_h2h():
    row = {"PTS": 20.0, "REB": 5.0, "AST": 3.0, "FG3M": 2.0}
    season_log = [{"pts": 20, "reb": 5, "ast": 3, "fg3m": 2}] * 10   # season avg 20
    # wild H2H swing: 4 and 32 across 2 games — spread of 28, way more than 75% of season avg (15)
    h2h = [{"pts": 32, "reb": 5, "ast": 3, "fg3m": 2}, {"pts": 4, "reb": 5, "ast": 3, "fg3m": 2}]
    profile = WP.build_matchup_profile(row, h2h_log=h2h, opp_recent_allowed={}, opp_season_allowed={},
                                       season_log=season_log)
    pts = next(p for p in profile if p["Market"] == "Points")
    assert pts["High Variance"] is True
    assert pts["H2H Spread"] == "4\u201332"
    print("✓ build_matchup_profile flags a wide H2H swing as high variance, with the actual spread shown")


def test_build_matchup_profile_no_variance_flag_for_consistent_h2h():
    row = {"PTS": 20.0, "REB": 5.0, "AST": 3.0, "FG3M": 2.0}
    season_log = [{"pts": 20, "reb": 5, "ast": 3, "fg3m": 2}] * 10
    h2h = [{"pts": 19, "reb": 5, "ast": 3, "fg3m": 2}, {"pts": 21, "reb": 5, "ast": 3, "fg3m": 2}]
    profile = WP.build_matchup_profile(row, h2h_log=h2h, opp_recent_allowed={}, opp_season_allowed={},
                                       season_log=season_log)
    pts = next(p for p in profile if p["Market"] == "Points")
    assert pts["High Variance"] is False


def test_build_matchup_profile_no_spread_with_fewer_than_two_h2h_games():
    row = {"PTS": 20.0, "REB": 5.0, "AST": 3.0, "FG3M": 2.0}
    h2h = [{"pts": 20, "reb": 5, "ast": 3, "fg3m": 2}]   # only 1 meeting -> no spread to report
    profile = WP.build_matchup_profile(row, h2h_log=h2h, opp_recent_allowed={}, opp_season_allowed={})
    pts = next(p for p in profile if p["Market"] == "Points")
    assert pts["H2H Spread"] is None
    assert pts["High Variance"] is False


# ----------------------------------------------------------------- suppressed-market detection
def test_build_matchup_profile_flags_the_one_suppressed_market():
    row = {"PTS": 20.0, "REB": 5.0, "AST": 3.0, "FG3M": 2.0}
    season_log = [{"pts": 20, "reb": 5, "ast": 3, "fg3m": 2}] * 10
    # Threes specifically get shut down (0.5 vs season avg 2 -> ratio 0.25); everything else ~normal.
    h2h = [{"pts": 19, "reb": 5, "ast": 3, "fg3m": 0}, {"pts": 21, "reb": 5, "ast": 3, "fg3m": 1}]
    profile = WP.build_matchup_profile(row, h2h_log=h2h, opp_recent_allowed={}, opp_season_allowed={},
                                       season_log=season_log)
    threes = next(p for p in profile if p["Market"] == "Threes Made")
    others = [p for p in profile if p["Market"] != "Threes Made"]
    assert threes["Suppressed"] is True
    assert all(not p["Suppressed"] for p in others)
    print("✓ build_matchup_profile correctly isolates the one market that's distinctly suppressed")


def test_build_matchup_profile_no_suppression_flag_when_everything_dips_evenly():
    # If EVERY market is a little lower vs this opponent, that's not a targeted effect on one
    # skill — it's more likely just a tougher game/team overall. Nothing should be flagged.
    row = {"PTS": 20.0, "REB": 5.0, "AST": 3.0, "FG3M": 2.0}
    season_log = [{"pts": 20, "reb": 5, "ast": 3, "fg3m": 2}] * 10
    h2h = [{"pts": 17, "reb": 4.3, "ast": 2.6, "fg3m": 1.7}]   # all ~85% of season norm, evenly
    profile = WP.build_matchup_profile(row, h2h_log=h2h, opp_recent_allowed={}, opp_season_allowed={},
                                       season_log=season_log)
    assert all(not p["Suppressed"] for p in profile)
    print("✓ build_matchup_profile does not flag suppression when every market dips evenly (not a targeted effect)")


def test_build_matchup_profile_no_suppression_when_all_low_but_not_distinctly_separated():
    # A tougher variant of the evenly-dipping case: every market IS below the 0.75 absolute
    # threshold this time, but they're all close to each other (within 0.15) — still not a
    # targeted single-market effect, just a genuinely tough game across the board.
    row = {"PTS": 20.0, "REB": 5.0, "AST": 3.0, "FG3M": 2.0}
    season_log = [{"pts": 20, "reb": 5, "ast": 3, "fg3m": 2}] * 10
    h2h = [{"pts": 13, "reb": 3.2, "ast": 1.9, "fg3m": 1.3}]   # all ~62-65% of season norm
    profile = WP.build_matchup_profile(row, h2h_log=h2h, opp_recent_allowed={}, opp_season_allowed={},
                                       season_log=season_log)
    assert all(not p["Suppressed"] for p in profile)
    print("✓ build_matchup_profile requires distinct separation, not just a low absolute ratio, to flag suppression")


def test_build_matchup_profile_no_suppression_flag_without_enough_data():
    row = {"PTS": 20.0, "REB": 5.0, "AST": 3.0, "FG3M": 2.0}
    profile = WP.build_matchup_profile(row, h2h_log=[], opp_recent_allowed={}, opp_season_allowed={})
    assert all(not p["Suppressed"] for p in profile)   # no h2h/season data at all -> nothing to flag


# ----------------------------------------------------------------- trend-chart helpers
def test_default_line_returns_the_model_only_board_default():
    assert WP.default_line("player_points") == 12.5
    assert WP.default_line("player_threes") == 1.5


def test_default_line_none_for_unknown_market():
    assert WP.default_line("not_a_real_market") is None


def test_market_list_covers_all_four_core_markets():
    lst = WP.market_list()
    assert {mkey for mkey, _col, _disp in lst} == {"player_points", "player_rebounds",
                                                    "player_assists", "player_threes"}
    # spot-check one full tuple
    assert ("player_points", "PTS", "Points") in lst


def test_stat_key_for_maps_row_columns_to_game_log_keys():
    assert WP.stat_key_for("PTS") == "pts"
    assert WP.stat_key_for("FG3M") == "fg3m"


def test_build_trend_series_reverses_to_chronological_order():
    log = [{"date": "2026-07-14", "pts": 30}, {"date": "2026-07-10", "pts": 20},
          {"date": "2026-07-08", "pts": 18}]   # most-recent-first, per get_player_recent_games
    trend = WP.build_trend_series(log)
    assert [g["date"] for g in trend] == ["2026-07-08", "2026-07-10", "2026-07-14"]  # oldest -> newest
    print("✓ build_trend_series reverses most-recent-first into chronological (plotting) order")


def test_build_trend_series_empty_log():
    assert WP.build_trend_series([]) == []


def test_market_lines_for_player_works_with_wnba_projections_module():
    # market_lines_for_player takes projections_module explicitly (Matchup Lab passes P, the
    # active sport's own module) so WNBA name normalization is used, not MLB's default.
    offers = [{"market": "player_points", "player": "A'ja Wilson", "point": 22.5,
              "over": {"fd": -115}, "under": {"fd": -105}}]
    lines = O.market_lines_for_player(offers, "A'ja Wilson", projections_module=WP)
    assert lines == {"player_points": 22.5}
    print("✓ market_lines_for_player works correctly when passed wnba_projections as the projections_module")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
