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
