"""Nov 18: two legs on one player are correlated by the market pair, measured (research/rho_nested.py) -- and the
same-game parlay pricer and the Slip Lab use the same numbers (one correlation model)."""
import props_engine as PE
import slip_sim as SIM


def _leg(player, market, side="Over", sport="NBA", team="LAL"):
    return {"sport": sport, "game": "g", "player": player, "team": team, "market": market, "side": side, "p": 0.5}


def test_pairs_are_measured_not_one_number():
    assert SIM.same_player_rho("NBA", "Points", "PRA") == 0.89
    assert SIM.same_player_rho("NBA", "Pts+Reb+Ast", "Points") == 0.89          # display names normalise
    assert SIM.same_player_rho("NBA", "Rebounds", "Threes Made") == 0.08
    assert SIM.same_player_rho("NHL", "Goals", "Points") == 0.93
    assert SIM.same_player_rho("NHL", "Goals", "Assists") == 0.02
    assert SIM.same_player_rho("NBA", "Points", "Points") == SIM.SAME_MARKET_RHO
    assert SIM.same_player_rho("NBA", "Blocks", "Points") == SIM.OVERLAP_BASE   # unmeasured, no shared stats


def test_slip_sim_and_sgp_agree():
    a, b = _leg("A", "Points"), _leg("A", "PRA", side="Under")
    R = SIM.correlation_matrix([a, b])
    assert abs(R[0, 1] + 0.89) < 1e-6
    assert abs(PE.leg_correlation(a, b) + 0.89) < 1e-9
    t = _leg("B", "Points")
    assert abs(PE.leg_correlation(a, t) - SIM.same_game_rho("NBA", True)) < 1e-9
    r = PE.sgp([dict(a, sport=None), dict(_leg("A", "PRA"), sport=None)], -110, sport="NBA", n_sims=20000)
    assert r["lift"] > 1.4                  # 0.89 correlated: both hit far more often than 25%
