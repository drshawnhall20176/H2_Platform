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
